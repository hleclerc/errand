"""The page's server: one HTML page ( `page.py` ), then JSON that the page asks for every 2 s -- what
`errand tui` shows, built by the same code ( `tui.rows`, `tui.screen.detail_rows`, `tui.actions` ).

    GET  /?o=CODE           a code used once ( `errand web` ): a cookie, then back to /
    GET  /                  the page; without the cookie, a form that asks for the token
    GET  /job?key=[&path=]  the same page for one run: its outputs left, the one chosen right
    POST /login             the token typed in that form: the cookie
    GET  /state?tab=&q=&folded=&opened=&shown=     the rows of a tab ( `tui.rows.build` ), the counts
    GET  /detail?key=       what the detail of a row says: facts, step, views, outputs, console
    GET  /peek?key=&path=   the beginning of a file of the row, to show it
    GET  /ls?key=&path=     a directory of the row, one level
    GET  /file?key=&path=[&download=1]             a whole file of the row ( at most 64 MB ), sandboxed
    POST /act   { op, key, label, path, sure }     kill, forget, watch, rename, refresh, edit, reveal; kill
                                                   and forget answer what they would do until `sure`

A path is reached only through a row: one of its facts that is a path, one of its outputs, or under them.

Anything without the cookie, for another `Host`, or posted from another page ( `Origin` ), is refused.
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

LINGER = 30.0             # seconds the machines are still asked after the last request
WHOLE  = 64 << 20         # at most this much of a file is sent
PEEK   = 16384            # bytes of an output shown beside it
PEEK_MOST = 4 << 20       # at most, for a tab that shows only it
FRESH  = 1.5              # seconds a reading of a run's files and output is kept
KEPT   = 256 << 20        # bytes of other machines' files kept here, the least recently looked at going first
IMAGES = ( ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg" )
PAGES  = ( ".html", ".htm", ".pdf" )


class Web:
    """What the server knows: its token, its machines while a page asks, when it was last asked."""

    def __init__( self, machines_of = None, linger = LINGER, reload_page = False ):
        self.token    = secrets.token_urlsafe( 48 )            # 384 bits
        self.reload_page = reload_page      # `errand web dev`: page.py read again at each load
        self.linger   = linger
        self.last     = 0.0                 # time.monotonic() of the last request
        self.port     = None
        self._of      = machines_of
        self._list    = None
        self._lock    = threading.Lock()
        self._held    = None                # the lock file, for as long as this serves
        self._httpd   = None
        self._read    = { }                 # row key -> ( when, what `_read` said )
        self._files   = { }                 # ( machine, path, size ) -> bytes: files of other machines, kept
        self._caches  = ( set(), set(), 30.0, False )   # the caches tab as the page last asked it: folded, opened, days, all

    # ── life ─────────────────────────────────────────────────────────────────

    @classmethod
    def start( cls, cache: Path, port = None, machines_of = None, linger = LINGER, reload_page = False ):
        """Serve from threads, if nobody serves from `cache` yet -> the Web, or None."""
        from ..agents.endpoint import hold
        from . import LOCK, SAID, port_of_user
        cache.mkdir( parents = True, exist_ok = True )
        held = hold( cache / LOCK )
        if held is None:
            return None
        web = cls( machines_of, linger, reload_page )
        web._held = held
        try:
            httpd = _bind( web, port_of_user() if port is None else port )
        except Exception:
            held.close()
            raise
        web._httpd, web.port = httpd, httpd.server_address[ 1 ]
        path = cache / SAID
        tmp = path.with_suffix( ".tmp" )
        fd = os.open( str( tmp ), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 )
        with os.fdopen( fd, "w" ) as f:
            json.dump( { "port": web.port, "token": web.token, "pid": os.getpid() }, f )
        tmp.replace( path )
        threading.Thread( target = httpd.serve_forever, kwargs = { "poll_interval": 0.5 }, daemon = True ).start()
        threading.Thread( target = web._reap, daemon = True ).start()
        return web

    def stop( self ):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        self._let_go()
        if self._held is not None:
            self._held.close()
            self._held = None

    def used( self, within: float ) -> bool:
        """Asked lately: the agent counts it as use."""
        return self.last > 0 and time.monotonic() - self.last <= within

    # ── the machines, while a page asks ──────────────────────────────────────

    def machines( self ) -> list:
        with self._lock:
            self.last = time.monotonic()
            if self._list is None:
                self._list = ( self._of or _watched )()
            return self._list

    def machine( self, name: str ):
        m = next( ( m for m in self.machines() if m.name == name ), None )
        if m is None:
            raise LookupError( f"no machine {name!r}" )
        return m

    def _let_go( self ):
        with self._lock:
            for m in self._list or [ ]:
                m.stopped = True
                m.wake.set()
            self._list = None

    def _reap( self ):
        while self._held is not None:
            time.sleep( min( 5.0, self.linger / 3 ) )
            if self._list is not None and not self.used( self.linger ):
                self._let_go()

    # ── what is asked ────────────────────────────────────────────────────────

    def state( self, q: dict ) -> dict:
        from ..tui import rows as R
        ms = self.machines()
        tab = q.get( "tab" ) if q.get( "tab" ) in R.TABS else "runs"
        folded = { ( "day", w[ 4 : ] ) if w.startswith( "day:" ) else ( "cache", w[ 6 : ] ) if w.startswith( "cache:" ) else w
                   for w in _set( q.get( "folded" ) ) }
        opened = _set( q.get( "opened" ) )
        try:
            days = max( 0.001, float( q.get( "days" ) or 30 ) )
        except ValueError:
            days = 30.0
        every = q.get( "all" ) in ( "1", "true" )
        if tab == "caches":
            from ..tui import caches as K
            K.want( ms, entries = [ o[ 8 : ] for o in opened if o.startswith( "entries:" ) ], days = days )
            self._caches = ( folded, opened, days, every )
        rows = R.build( ms, tab = tab, folded = folded, opened = opened, query = q.get( "q", "" ),
                        shown = int( q.get( "shown" ) or 50 ), days = days, every = every )
        running = waiting = 0
        for m in ms:
            for p in ( m.table or { } ).get( "procs", [ ] ):
                if p.get( "vm" ) or p.get( "kind" ) == "agent":
                    continue
                waiting += bool( p.get( "waiting" ) )
                running += not p.get( "waiting" )
        return { "rows": [ _row( r ) for r in rows ], "tab": tab,
                 "here": next( ( m.name for m in ms if m.here ), None ),
                 "counts": { "running": running, "waiting": waiting, "machines": len( ms ),
                             "off": sum( 1 for m in ms if getattr( m, "dormant", False ) ) } }

    def find( self, key: str ):
        """The row `key` names, and its machine: rows rebuilt with everything shown."""
        from ..tui import rows as R
        ms = self.machines()
        folded, opened, days, all_ = self._caches
        every = R.build( ms, tab = "machines", shown = 1 << 30 ) + R.build( ms, tab = "runs", shown = 1 << 30 ) \
            + R.build( ms, tab = "caches", folded = folded, opened = opened, days = days, every = all_ )
        row = next( ( r for r in every if _key( r ) == key ), None )
        if row is None:
            raise LookupError( "not there any more" )
        machine = row.data[ 0 ] if isinstance( row.data, tuple ) else None
        return row, next( ( m for m in ms if m.name == machine ), None )

    def detail( self, key: str ) -> dict:
        """The detail of a row, as `errand tui` draws it ( `detail_rows` ), as rows of JSON."""
        from ..tui.screen import _read, detail_rows
        row, m = self.find( key )
        got = None
        if row.kind in ( "proc", "run" ):
            when, got = self._read.get( key, ( 0.0, None ) )
            if got is None or time.monotonic() - when > FRESH:
                try:
                    got = _read( m, row.data[ 1 ] )
                except Exception as err:
                    got = { "error": _said( err ) }
                self._read[ key ] = ( time.monotonic(), got )
        rows = detail_rows( row, m, got ) if m is not None or row.kind not in ( "proc", "run" ) else [ ]
        out = [ ]
        for r in rows:
            d = { "kind": r.kind, "label": r.label, "detail": r.detail }
            if r.kind == "plain" and isinstance( r.data, tuple ):
                d[ "k" ], d[ "v" ] = str( r.data[ 0 ] ), str( r.data[ 1 ] )
            elif r.kind == "output":
                d[ "machine" ], d[ "path" ] = r.data
            elif r.kind == "cend":
                d[ "status" ] = r.data
            out.append( d )
        what = row.data[ 1 ] if isinstance( row.data, tuple ) and isinstance( row.data[ 1 ], dict ) else { }
        return { "file": _entry_file( what ) if row.kind in ( "proc", "run" ) else None, "title": row.label, "kind": row.kind, "machine": m.name if m else None, "rows": out,
                 "started": what.get( "started" ), "duration": what.get( "duration" ),
                 "now": m.now() if m else time.time(),
                 "console": ( got or { } ).get( "path" ), "here": bool( m and m.here ),
                 "can": _can( row, m ) }

    # ── the paths of a row: what may be read, listed, opened ────────────────

    def roots( self, key: str ):
        """The machine of row `key`, and the directories and files the page may reach through it: its
        facts that are paths ( project, leaf, … ), its outputs. Nothing else of the machine."""
        d = self.detail( key )
        if not d.get( "machine" ):
            raise LookupError( "this row is on no machine" )
        out = { r[ "v" ] for r in d[ "rows" ] if r.get( "v", "" ).startswith( "/" ) and " " not in r[ "v" ] }
        if d.get( "file" ):
            out.add( d[ "file" ] )
        # what it runs: the file of its command ( `run /path/script.sh` ), wherever it is
        out |= { w for r in d[ "rows" ] if r.get( "k" ) == "what" for w in r[ "v" ].split() if w.startswith( "/" ) }
        out |= { r[ "path" ] for r in d[ "rows" ] if r[ "kind" ] == "output" and r.get( "path" ) }
        if d.get( "console" ):
            out.add( d[ "console" ] )
        return self.machine( d[ "machine" ] ), out, d

    def reach( self, key: str, path: str ):
        """( machine, path ) when `path` is one of row `key`'s, or under one; ValueError otherwise."""
        import posixpath
        m, roots, _ = self.roots( key )
        path = posixpath.normpath( str( path or "" ) )
        if not path.startswith( "/" ) or not any( path == r or path.startswith( r.rstrip( "/" ) + "/" ) for r in roots ):
            raise ValueError( "not a path of this row" )
        return m, path

    def listing( self, key: str, path: str ) -> dict:
        """A directory of the row, one level ( `look.entries` ); an older agent: its files, two levels."""
        m, path = self.reach( key, path )
        got = m.ask( { "op": "ls", "path": path, "dirs": True } )
        if "entries" in got:
            entries = got[ "entries" ]
        else:
            entries = [ { "name": f[ "name" ], "dir": False, "size": f[ "size" ], "mtime": f[ "mtime" ] } for f in got.get( "files", [ ] ) ]
        now = m.now()
        return { "path": path, "machine": m.name, "here": m.here,
                 "entries": [ { **e, "age": now - e[ "mtime" ] } for e in entries ] }

    def peek( self, key: str, path: str, size = PEEK ) -> dict:
        """The beginning of an output, to show beside it: text, or what it is when it is not. `size`: how much
        ( a tab that shows only it reads more, up to `PEEK_MOST` )."""
        m, path = self.reach( key, path )
        size = max( 1, min( int( size or PEEK ), PEEK_MOST ) )
        name = path.rsplit( "/", 1 )[ -1 ].lower()
        got = m.ask( { "op": "tail", "path": path, "offset": 0, "size": size } )
        if got.get( "missing" ):
            raise FileNotFoundError( "not there any more" )
        size = got.get( "size", 0 )
        if name.endswith( IMAGES ):
            return { "kind": "image", "size": size }
        if name.endswith( PAGES ):
            return { "kind": "page", "size": size }
        text = got.get( "data" ) or ""
        if "\x00" in text or text.count( "�" ) > max( 8, len( text ) // 50 ):
            return { "kind": "binary", "size": size }
        if got.get( "end", 0 ) < size and "\n" in text:
            text = text.rsplit( "\n", 1 )[ 0 ]                   # a line cut in two is not shown
        return { "kind": "text", "text": text, "size": size, "more": max( 0, size - got.get( "end", 0 ) ) }

    def file( self, key: str, path: str, write ):
        """A whole file, as its bytes ( an image, a PDF stay what they are ). One of another machine is kept
        here while it does not change ( its size ): a page of 16 MB is fetched once, not at each look."""
        import base64
        m, path = self.reach( key, path )
        first = m.ask( { "op": "tail", "path": path, "offset": 0, "size": 1 } ) if not m.here else None
        if first is not None and first.get( "missing" ):
            raise FileNotFoundError( f"{path}: not there" )
        kept = ( m.name, path, first[ "size" ] ) if first is not None else None
        with self._lock:
            got = self._files.get( kept ) if kept else None
            if got is not None:
                self._files[ kept ] = self._files.pop( kept )            # the most recent, last
        if got is not None:
            write( got )
            return
        chunks = [ ]
        offset = 0
        while offset < WHOLE:
            got = m.ask( { "op": "tail", "path": path, "offset": offset, "raw": True } )
            if got.get( "missing" ):
                raise FileNotFoundError( f"{path}: not there" )
            chunks.append( base64.b64decode( got[ "b64" ] ) if "b64" in got else got[ "data" ].encode( "utf-8" ) )
            if got[ "end" ] == got[ "offset" ] or got[ "end" ] >= got[ "size" ]:
                break
            offset = got[ "end" ]
        whole = b"".join( chunks )
        if kept is not None and len( whole ) == kept[ 2 ]:
            with self._lock:
                self._files[ kept ] = whole
                while sum( len( v ) for v in self._files.values() ) > KEPT and len( self._files ) > 1:
                    self._files.pop( next( iter( self._files ) ) )
        write( whole )

    def act( self, body: dict ) -> dict:
        """What a button or a key asks ( `tui.actions` ). Kill and forget say first what they would do."""
        from ..tui import actions as A
        op = body.get( "op" )
        if op == "refresh":
            for m in self.machines():
                m.history_at = 0.0
                m.wake.set()
            self._read.clear()
            return { "said": "asking again" }
        row, m = self.find( str( body.get( "key", "" ) ) )
        if op == "cache_hold":                   # ADR 0022: h
            from ..tui import caches as K
            r = K.hold_plan( row, self.machines() )
            if not body.get( "sure" ):
                return { "confirm": { "title": r.title, "lines": r.lines, "verb": "hold", "danger": False } }
            return { "said": K.send( r ) }
        if op == "cache_remove":                 # ADR 0022: i, u, d, D
            from ..tui import caches as K
            r = K.plan( row, str( body.get( "how" ) ), self.machines(), self._caches[ 2 ] )
            if not body.get( "sure" ):
                return { "confirm": { "title": r.title, "lines": r.lines, "verb": "remove", "danger": True } }
            said = K.send( r )
            K.want( self.machines(), days = self._caches[ 2 ], force = True )
            return { "said": said }
        if op == "kill":
            plan = A.kill_plan( row, m )
            if not body.get( "sure" ):
                return { "confirm": { "title": plan.title, "lines": plan.lines, "verb": "kill", "danger": True } }
            return { "said": A.send( plan ) }
        if m is None:
            raise ValueError( "on a machine, or on something that runs on one" )
        if op == "forget":
            if m.here:
                raise ValueError( "this machine is always shown: nothing to forget" )
            if not body.get( "sure" ):
                return { "confirm": { "title": f"forget {m.name}?", "lines": A.forget_lines( m ), "verb": "forget",
                                      "danger": False } }
            return { "said": A.forget( m, self.machines() ) }
        if op == "watch":
            return { "said": A.toggle_watch( m ) }
        if op == "rename":
            if "label" not in body:
                return { "prompt": { "title": A.rename_title( m ), "text": m.name } }
            return { "said": A.rename( m, str( body[ "label" ] ) ) }
        if op == "edit":
            return { "said": self.edit( str( body.get( "key", "" ) ), body.get( "path" ) ) }
        if op == "reveal":
            return { "said": self.reveal( str( body.get( "key", "" ) ), body.get( "path" ) ) }
        raise ValueError( f"no action {op!r}" )

    def reveal( self, key: str, path ) -> str:
        """A path of the row shown by this machine's file manager ( Finder, … ): a directory opened, a file
        selected in its own. Only on this machine: another's has no window here."""
        import subprocess
        import sys
        m, path = self.reach( key, path )
        if not m.here:
            raise ValueError( f"on {m.name}: its files have no window here ( click shows them, d downloads one )" )
        if sys.platform == "darwin":
            argv = [ "open", path ] if os.path.isdir( path ) else [ "open", "-R", path ]
        else:
            argv = [ "xdg-open", path if os.path.isdir( path ) else os.path.dirname( path ) ]
        try:
            subprocess.Popen( argv, stdin = subprocess.DEVNULL, stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL,
                              start_new_session = True )
        except OSError as err:
            raise ValueError( f"{argv[ 0 ]}: {err}" )
        return f"{path.rsplit( '/', 1 )[ -1 ]} shown in {'the Finder' if sys.platform == 'darwin' else 'the file manager'}"

    def edit( self, key: str, path ) -> str:
        """An output of the row `key` -- its console when `path` is None -- in an editor of this machine,
        the one the browser is on ( 127.0.0.1 ): `$ERRAND_WEB_EDITOR`, else the system's text editor
        ( `open -t`, `xdg-open` ). A file of another machine: a copy, fetched here first."""
        import shlex
        import subprocess
        import sys
        _, _, d = self.roots( key )
        if not ( path or d.get( "console" ) ):
            raise ValueError( "e: on an output of the row chosen" )
        m, path = self.reach( key, path or d.get( "console" ) )
        if m.here and os.path.isdir( path ):
            return self.reveal( key, path )                 # a folder: in its own window
        if m.here:
            local = path
        else:
            from ..tui.screen import _fetch
            local = str( _fetch( m, path ) )
        editor = os.environ.get( "ERRAND_WEB_EDITOR" )
        argv = shlex.split( editor ) if editor else ( [ "open", "-t" ] if sys.platform == "darwin" else [ "xdg-open" ] )
        try:
            subprocess.Popen( [ *argv, local ], stdin = subprocess.DEVNULL, stdout = subprocess.DEVNULL,
                              stderr = subprocess.DEVNULL, start_new_session = True )
        except OSError as err:
            raise ValueError( f"{argv[ 0 ]}: {err}" )
        name = path.rsplit( "/", 1 )[ -1 ]
        return f"{name} opened in {argv[ 0 ]}" + ( "" if m.here else f" ( a copy: {m.name} keeps its own )" )


def _entry_file( what: dict ) -> str | None:
    """The file of a run's entry, where it is on its machine: its record says it from the project's root
    ( `result.yaml`: `file` ); else its directory does ( `errand-outputs/runs/<file>/<entry>/<when>` ).
    A command run as it is ( `run /path/script.sh` ): its first absolute path."""
    import posixpath
    project, leaf = what.get( "project" ), what.get( "leaf" ) or ""
    if what.get( "file" ) and project:
        return posixpath.join( project, what[ "file" ] )
    if "/runs/" in leaf and project:
        rel = leaf.split( "/runs/", 1 )[ 1 ].split( "/" )[ : -2 ]       # the entry's name and the moment, off
        if rel and "." in rel[ -1 ]:
            return posixpath.join( project, *rel )
    words = [ w for w in str( what.get( "what" ) or "" ).split() if w.startswith( "/" ) ]
    return words[ 0 ] if words else None


def _can( row, m ) -> dict:
    """The buttons the detail shows for `row`."""
    from ..tui import actions as A
    can = { }
    try:
        A.kill_plan( row, m )
        can[ "kill" ] = True
    except ValueError:
        pass
    if row.kind in ( "cache", "cachefs" ):          # ADR 0022
        can[ "caches" ] = [ "dead", "unused" ]
        if row.kind == "cachefs" and not row.data[ 1 ].get( "guest" ):
            can[ "hold" ] = True
    elif row.kind == "centry":
        can[ "caches" ] = [ "flagged", "everywhere" ]
    if m is not None and row.kind in ( "machine", "broken", "dormant" ):      # a machine's, not its runs'
        can[ "rename" ] = True
        if not m.here:
            can[ "forget" ] = True
            can[ "watch" ] = "watch" if getattr( m, "dormant", False ) else "unwatch"
    return can


def _watched( ) -> list:
    """This machine and its ledger's, each asked by its own thread ( `tui.machines` )."""
    from ..tui.machines import watched
    ms = watched()
    for m in ms:
        m.watch()
    return ms


def _set( s ) -> set:
    return { w for w in ( s or "" ).split( "," ) if w }


def _key( row ) -> str:
    from ..tui import rows as R
    return json.dumps( R.key( row ) )


def _row( r ) -> dict:
    machine, what = r.data if isinstance( r.data, tuple ) else ( None, None )
    fold = ( machine if r.kind in ( "machine", "broken" ) else f"day:{what}" if r.kind == "day" else
             machine if r.kind == "group" else f"cache:{what[ 'cache' ]}" if r.kind == "cache" else
             f"entries:{what[ 'cache' ]}" if r.kind == "centries" else None ) if r.open is not None else None
    return { "key": _key( r ), "label": r.label, "detail": r.detail, "kind": r.kind, "mark": r.mark or "",
             "depth": r.depth, "open": r.open, "fold": fold, "machine": machine,
             "meters": [ [ n, round( f, 3 ) ] for n, f in r.meters ], "hits": list( r.hits ) }


def _said( err ) -> str:
    s = str( err ).strip()
    return s.splitlines()[ -1 ] if s else type( err ).__name__


# ── HTTP ─────────────────────────────────────────────────────────────────────

def _bind( web: Web, port: int ) -> ThreadingHTTPServer:
    class Handler( _Handler ):
        pass
    Handler.web = web
    try:
        httpd = ThreadingHTTPServer( ( "127.0.0.1", port ), Handler )
    except OSError:
        httpd = ThreadingHTTPServer( ( "127.0.0.1", 0 ), Handler )       # taken: any free one
    httpd.daemon_threads = True
    return httpd


class _Handler( BaseHTTPRequestHandler ):
    web : Web = None
    server_version = "errand-web"

    def log_message( self, *args ):          # the agent's log is not a web log
        pass

    @property
    def cookie( self ) -> str:
        return f"errand_web_{self.web.port}"

    def _host_ok( self ) -> bool:
        host = ( self.headers.get( "Host" ) or "" ).strip()
        return host in ( f"127.0.0.1:{self.web.port}", f"localhost:{self.web.port}" )

    def _allowed( self ) -> bool:
        if not self._host_ok():
            return False
        for part in ( self.headers.get( "Cookie" ) or "" ).split( ";" ):
            name, _, value = part.strip().partition( "=" )
            if name == self.cookie and hmac.compare_digest( value, self.web.token ):
                self.web.last = time.monotonic()        # a page asking: the agent is in use
                return True
        return False

    def _same_origin( self ) -> bool:
        """An action comes from the page itself: a page elsewhere cannot post here in its name."""
        origin = self.headers.get( "Origin" )
        return origin is None or origin in ( f"http://127.0.0.1:{self.web.port}", f"http://localhost:{self.web.port}" )

    def _send( self, code, body: bytes, kind = "application/json", extra = ( ) ):
        self.send_response( code )
        self.send_header( "Content-Type", kind )
        self.send_header( "Content-Length", str( len( body ) ) )
        self.send_header( "Cache-Control", "no-store" )
        self.send_header( "X-Content-Type-Options", "nosniff" )
        self.send_header( "Referrer-Policy", "no-referrer" )
        for k, v in extra:
            self.send_header( k, v )
        self.end_headers()
        self.wfile.write( body )

    def _json( self, obj, code = 200 ):
        self._send( code, json.dumps( obj ).encode() )

    def _logged_in( self ):
        self._send( 303, b"", "text/plain", [ ( "Location", "/" ),
            ( "Set-Cookie", f"{self.cookie}={self.web.token}; HttpOnly; SameSite=Strict; Path=/" ) ] )

    def do_GET( self ):
        url = urlsplit( self.path )
        q = { k: v[ -1 ] for k, v in parse_qs( url.query ).items() }
        if not self._host_ok():
            self._send( 403, b"not for this address\n", "text/plain" )
            return
        if url.path == "/" and "o" in q:
            from . import spend
            if spend( q[ "o" ] ):
                self._logged_in()
            else:
                from .page import LOGIN
                self._send( 403, LOGIN.replace( "{said}", "this link was used already, or is too old" ).encode(),
                            "text/html; charset=utf-8" )
            return
        if not self._allowed():
            if url.path in ( "/", "/job" ):
                from .page import LOGIN
                self._send( 401, LOGIN.replace( "{said}", "" ).encode(), "text/html; charset=utf-8" )
            else:
                self._send( 403, b"no token: `errand web` opens the page\n", "text/plain" )
            return
        try:
            if url.path in ( "/", "/job" ):             # the page; `/job?key=`: one run, as a page of its own
                from . import page
                if self.web.reload_page:
                    import importlib
                    importlib.reload( page )
                self._send( 200, page.PAGE.encode(), "text/html; charset=utf-8",
                            [ ( "Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; "
                                "style-src 'unsafe-inline'; img-src 'self' data:; frame-src 'self'; frame-ancestors 'none'" ) ] )
            elif url.path == "/state":
                self._json( self.web.state( q ) )
            elif url.path == "/detail":
                self._json( self.web.detail( q.get( "key", "" ) ) )
            elif url.path == "/peek":
                self._json( self.web.peek( q.get( "key", "" ), q.get( "path", "" ), q.get( "size" ) or PEEK ) )
            elif url.path == "/ls":
                self._json( self.web.listing( q.get( "key", "" ), q.get( "path", "" ) ) )
            elif url.path == "/file":
                chunks = [ ]
                path = q.get( "path", "" )
                self.web.file( q.get( "key", "" ), path, chunks.append )
                kind = mimetypes.guess_type( path )[ 0 ] or "text/plain"
                if not kind.startswith( ( "image/", "text/html", "application/pdf" ) ):
                    kind = "text/plain"                 # what the browser shows: a yaml, a script are text to read
                if kind.startswith( "text/" ):
                    kind += "; charset=utf-8"
                name = quote( path.rsplit( "/", 1 )[ -1 ] )
                how = "attachment" if q.get( "download" ) else "inline"
                # A run's page is served apart from this one: its scripts run, never as this page.
                self._send( 200, b"".join( chunks ), kind,
                            [ ( "Content-Security-Policy", "sandbox allow-scripts allow-popups allow-downloads" ),
                              ( "Content-Disposition", f"{how}; filename*=UTF-8''{name}" ) ] )
            else:
                self._send( 404, b"nothing here\n", "text/plain" )
        except LookupError as err:
            self._json( { "error": _said( err ) }, 404 )
        except ValueError as err:
            self._json( { "error": _said( err ) }, 403 if "not a path" in str( err ) else 400 )
        except Exception as err:
            self._json( { "error": _said( err ) }, 500 )

    def do_POST( self ):
        url = urlsplit( self.path )
        if not self._host_ok() or not self._same_origin():
            self._send( 403, b"not from this page\n", "text/plain" )
            return
        size = min( int( self.headers.get( "Content-Length" ) or 0 ), 1 << 16 )
        raw = self.rfile.read( size )
        if url.path == "/login":
            typed = parse_qs( raw.decode( errors = "replace" ) ).get( "token", [ "" ] )[ -1 ].strip()
            if typed and hmac.compare_digest( typed, self.web.token ):
                self._logged_in()
            else:
                from .page import LOGIN
                time.sleep( 1.0 )                                  # one guess a second
                self._send( 403, LOGIN.replace( "{said}", "not the token" ).encode(), "text/html; charset=utf-8" )
            return
        if not self._allowed():
            self._send( 403, b"no token\n", "text/plain" )
            return
        try:
            body = json.loads( raw or b"{}" )
            if url.path != "/act":
                self._send( 404, b"nothing here\n", "text/plain" )
                return
            self._json( self.web.act( body ) )
        except ( ValueError, LookupError ) as err:
            self._json( { "error": _said( err ) }, 400 )
        except Exception as err:
            self._json( { "error": _said( err ) }, 500 )
