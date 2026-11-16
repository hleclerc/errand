"""The page's server: one HTML page ( `page.py` ), then JSON that the page asks for every 2 s.

    GET  /?t=TOKEN          the token becomes a cookie, then back to /
    GET  /                  the page
    GET  /state?q=&folded=&opened=&shown=     the rows of the list ( `tui.rows.build` )
    GET  /detail?key=       the detail of a row: facts, files, the end of its output
    GET  /file?machine=&path=                 a whole file of a run ( at most 64 MB ), as text
    POST /stop   { key }    a process or a VM stopped ( `look.kill`: cancel line, INT, TERM, KILL )

Anything without the token, or for another `Host`, is refused ( 403 ).
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

LINGER = 30.0             # seconds the machines are still asked after the last request
WHOLE  = 64 << 20         # at most this much of a file is sent


class Web:
    """What the server knows: its token, its machines while a page asks, when it was last asked."""

    def __init__( self, machines_of = None, linger = LINGER ):
        self.token    = secrets.token_urlsafe( 24 )
        self.linger   = linger
        self.last     = 0.0                 # time.monotonic() of the last request
        self.port     = None
        self._of      = machines_of
        self._list    = None
        self._lock    = threading.Lock()
        self._held    = None                # the lock file, for as long as this serves
        self._httpd   = None

    # ── life ─────────────────────────────────────────────────────────────────

    @classmethod
    def start( cls, cache: Path, port = None, machines_of = None, linger = LINGER ):
        """Serve from threads, if nobody serves from `cache` yet -> the Web, or None."""
        from ..agents.endpoint import hold
        from . import LOCK, SAID, port_of_user
        cache.mkdir( parents = True, exist_ok = True )
        held = hold( cache / LOCK )
        if held is None:
            return None
        web = cls( machines_of, linger )
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
        rows = R.build( ms, folded = _set( q.get( "folded" ) ), opened = _set( q.get( "opened" ) ),
                        query = q.get( "q", "" ), shown = int( q.get( "shown" ) or 50 ) )
        return { "rows": [ _row( r ) for r in rows ], "here": next( ( m.name for m in ms if m.here ), None ) }

    def find( self, key: str ):
        """The row `key` names, and its machine: rows rebuilt with everything shown."""
        from ..tui import rows as R
        ms = self.machines()
        every = R.build( ms, opened = { m.name for m in ms }, shown = 1 << 30 )
        row = next( ( r for r in every if _key( r ) == key ), None )
        if row is None:
            raise LookupError( "not there any more" )
        machine = row.data[ 0 ] if isinstance( row.data, tuple ) else None
        return row, next( ( m for m in ms if m.name == machine ), None )

    def detail( self, key: str ) -> dict:
        from ..tui import rows as R
        from ..tui.screen import _read
        row, m = self.find( key )
        out = { "title": row.label, "kind": row.kind, "facts": R.facts( row, m ) if m else [ ] }
        try:
            R.stop_request( row, m )
            out[ "stop" ] = True
        except ValueError as err:
            out[ "stop" ] = str( err ) if row.kind in ( "proc", "vm" ) else False
        if row.kind in ( "proc", "run" ):
            try:
                got = _read( m, row.data[ 1 ] )
                now = m.now()
                out.update( out = got.get( "out" ) or "", source = got.get( "source" ), path = got.get( "path" ),
                            files = [ { "name": f[ "name" ], "size": f[ "size" ], "age": now - f[ "mtime" ], "path": f[ "path" ] }
                                      for f in got.get( "files" ) or [ ] ] )
            except Exception as err:
                out[ "error" ] = _said( err )
        out[ "machine" ] = m.name if m else None
        return out

    def stop_row( self, key: str ) -> dict:
        from ..tui import rows as R
        row, m = self.find( key )
        req, said = R.stop_request( row, m )
        m.ask( req, timeout = 30 )
        m.wake.set()
        return { "ok": True, "said": f"stopping {said}: INT, then TERM, then KILL" }

    def file( self, machine: str, path: str, write ):
        m = next( ( m for m in self.machines() if m.name == machine ), None )
        if m is None:
            raise LookupError( f"no machine {machine!r}" )
        offset = 0
        while offset < WHOLE:
            got = m.ask( { "op": "tail", "path": path, "offset": offset } )
            if got.get( "missing" ):
                raise FileNotFoundError( f"{path}: not there" )
            write( got[ "data" ].encode( "utf-8" ) )
            if got[ "end" ] == got[ "offset" ] or got[ "end" ] >= got[ "size" ]:
                break
            offset = got[ "end" ]


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
    return { "key": _key( r ), "label": r.label, "detail": r.detail, "kind": r.kind, "mark": r.mark or "",
             "depth": r.depth, "open": r.open, "machine": r.data[ 0 ] if isinstance( r.data, tuple ) else None }


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

    def _allowed( self ) -> bool:
        host = ( self.headers.get( "Host" ) or "" ).strip()
        if host not in ( f"127.0.0.1:{self.web.port}", f"localhost:{self.web.port}" ):
            return False
        for part in ( self.headers.get( "Cookie" ) or "" ).split( ";" ):
            name, _, value = part.strip().partition( "=" )
            if name == self.cookie and hmac.compare_digest( value, self.web.token ):
                self.web.last = time.monotonic()        # a page asking: the agent is in use
                return True
        return False

    def _send( self, code, body: bytes, kind = "application/json", extra = ( ) ):
        self.send_response( code )
        self.send_header( "Content-Type", kind )
        self.send_header( "Content-Length", str( len( body ) ) )
        self.send_header( "Cache-Control", "no-store" )
        for k, v in extra:
            self.send_header( k, v )
        self.end_headers()
        self.wfile.write( body )

    def _json( self, obj, code = 200 ):
        self._send( code, json.dumps( obj ).encode() )

    def do_GET( self ):
        url = urlsplit( self.path )
        q = { k: v[ -1 ] for k, v in parse_qs( url.query ).items() }
        if "t" in q and url.path == "/":
            if hmac.compare_digest( q[ "t" ], self.web.token ):
                self._send( 303, b"", "text/plain", [ ( "Location", "/" ),
                    ( "Set-Cookie", f"{self.cookie}={self.web.token}; HttpOnly; SameSite=Strict; Path=/" ) ] )
            else:
                self._send( 403, b"wrong token: `errand web` gives the right one\n", "text/plain" )
            return
        if not self._allowed():
            self._send( 403, b"no token: open the URL `errand web` prints\n", "text/plain" )
            return
        try:
            if url.path == "/":
                from .page import PAGE
                self._send( 200, PAGE.encode(), "text/html; charset=utf-8" )
            elif url.path == "/state":
                self._json( self.web.state( q ) )
            elif url.path == "/detail":
                self._json( self.web.detail( q.get( "key", "" ) ) )
            elif url.path == "/file":
                chunks = [ ]
                self.web.file( q.get( "machine", "" ), q.get( "path", "" ), chunks.append )
                self._send( 200, b"".join( chunks ), "text/plain; charset=utf-8" )
            else:
                self._send( 404, b"nothing here\n", "text/plain" )
        except LookupError as err:
            self._json( { "error": _said( err ) }, 404 )
        except Exception as err:
            self._json( { "error": _said( err ) }, 500 )

    def do_POST( self ):
        if not self._allowed():
            self._send( 403, b"no token\n", "text/plain" )
            return
        try:
            size = int( self.headers.get( "Content-Length" ) or 0 )
            body = json.loads( self.rfile.read( size ) or b"{}" )
            if urlsplit( self.path ).path != "/stop":
                self._send( 404, b"nothing here\n", "text/plain" )
                return
            self._json( self.web.stop_row( str( body.get( "key", "" ) ) ) )
        except ( ValueError, LookupError ) as err:
            self._json( { "error": _said( err ) }, 400 )
        except Exception as err:
            self._json( { "error": _said( err ) }, 500 )
