"""What a page served as it is ( `errand.Static` ) may ask for: the SERVICES its directory names ( ADR 0026 ), each on the
machine the person chooses, as the packages there describe them ( ADR 0027 ).

    <view>/services.json        written by the producer, format 2: { "format": 2, "services": { name: { version, protocol,
                                optional, package: { name, version }, described: <the package's entry, copied> } } }
                                ( format 1, ADR 0026: { name: { protocol, optional, install } }, no version, still read )

    GET  .errand/services                    per service: version, protocol, optional, text, `on` ( the machine chosen ) and
                                             that machine's state, why, store, found, lines
    GET  .errand/machines                    the machines offered, in order, each with what is known of it yet
    GET  .errand/machines/<M>[?refresh=1]    M's diagnosis ( its agent's `services` look, kept until refresh )
    POST .errand/services/<name>  {"on": M}  the choice of machine, kept per view
    POST .errand/copy             {"on": M}  the view's files copied into errand's cache on M, kept up to date
    POST .errand/machines/<M>/paths  {"tool", "path"}    a place for M's agent to look ( never run )
    ANY  .errand/svc/<name>/<p>              relayed to `name#version` on the machine chosen, ensured there first, as `<p>`,
                                             with `X-Errand-Root: <the store as that machine sees it, percent-encoded>`

A page starts only what BOTH sides name: a service its `services.json` lists AND the machine declares under that exact
`name#version` ( `~/.config/errand/services.py`, then what `errand serve install` wrote -- never a project's files ). Nothing
in a page or in a `services.json` declares a command: the lines are for a PERSON to type. The one thing a page triggers by
itself is the copy of its own files into errand's cache on a machine of the user's: data, nothing run.

The relay works at the HTTP level: the request's head rewritten ( its path, `Host`, `X-Errand-Root`, `Connection: close`
or the client's `Upgrade` ), then bytes both ways until the service closes; the answer's head rewritten the same way
( `Connection: close`, but for a `101 Switching Protocols`, after which the WebSocket's frames pass as they are ). On this
machine the connection goes through the service's announced port, so the keeper counts it as a use ( ADR 0018 ); on
another, through a `forward` of that machine's agent ( one channel per connection ).
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path
from urllib.parse import quote, unquote

FILE = "services.json"
HOP = { "host", "connection", "keep-alive", "proxy-connection", "x-errand-root" }
LOOK_TIMEOUT = 10.0              # a machine whose agent says nothing within this is `unreachable`
KEPT = 300.0                     # a diagnosis is reused this long, unless refreshed
KEPT_HERE = 2.0                  # ( this machine's: cheap, and its states change as services start and stop )

_lock = threading.Lock()
_machine = { "stamp": None, "names": { } }
_looks: dict = { }               # ( vid, M ) -> ( when, answer )
_forwards: dict = { }            # ( M, key ) -> a listening socket here ( `serve.forward` )
_copies: dict = { }              # ( vid, M ) -> { state, done, error, last_asked }


# ── what the directory asks for ──────────────────────────────────────────────

def asked( view_dir ) -> dict:
    """the services the directory names: { name: { version, protocol, optional, text, package, described } }"""
    try:
        got = json.loads( ( Path( view_dir ) / FILE ).read_text() )
    except ( OSError, ValueError ):
        return { }
    if not isinstance( got, dict ):
        return { }
    if got.get( "format" ) == 2 and isinstance( got.get( "services" ), dict ):
        out = { }
        for k, v in got[ "services" ].items():
            v = v if isinstance( v, dict ) else { }
            desc = v.get( "described" ) if isinstance( v.get( "described" ), dict ) else { }
            out[ str( k ) ] = { "version": str( v[ "version" ] ) if v.get( "version" ) else None,
                                "protocol": v.get( "protocol" ), "optional": bool( v.get( "optional", True ) ),
                                "text": str( v.get( "text" ) or desc.get( "text" ) or "" ),
                                "package": v.get( "package" ) if isinstance( v.get( "package" ), dict ) else { },
                                "described": desc }
        return out
    out = { }                                                    # ( format 1: a name, a recipe that is not read any more )
    for k, v in got.items():
        v = v if isinstance( v, dict ) else { }
        out[ str( k ) ] = { "version": None, "protocol": v.get( "protocol" ), "optional": bool( v.get( "optional", True ) ),
                            "text": str( ( v.get( "install" ) or { } ).get( "text" ) or "" ), "package": { }, "described": { } }
    return out


def key_of( name: str, want: dict ) -> str:
    return f"{name}#{want[ 'version' ]}" if want.get( "version" ) else name


# ── this machine's declarations ──────────────────────────────────────────────

def machine( ) -> dict:
    """the services this machine declares in the user's file and installed, read again when they change -> { key: Service }"""
    from .. import serve as S
    from .. import install
    stamps = [ ]
    for f in ( S.user_file(), install.installed_file() ):
        try:
            stamps.append( f.stat().st_mtime_ns )
        except OSError:
            stamps.append( None )
    stamp = tuple( stamps ) if any( s is not None for s in stamps ) else None
    f = S.user_file()
    with _lock, S.declaring:
        if stamp != _machine[ "stamp" ]:
            names = { }
            if stamp is not None:
                import runpy
                S.services.clear()
                try:
                    if f.is_file():
                        runpy.run_path( str( f ), run_name = "errand_services" )
                    names = dict( S.services )
                    for svc in names.values():
                        if getattr( svc, "source", None ) is None:
                            svc.source = "services.py"
                except Exception as err:            # ( a broken file: no service, and said )
                    names = { }
                    _machine[ "error" ] = f"{f}: {err}"
                else:
                    _machine.pop( "error", None )
                for name, svc in install.services().items():        # ( installed ones: after the user's file )
                    names.setdefault( name, svc )
            _machine.update( stamp = stamp, names = names )
        return dict( _machine[ "names" ] )


# ── per view: the choice, the paths given, the copies ────────────────────────

def _state_file( name: str ) -> Path:
    from .. import serve as S
    return S.home() / name


def _read( name: str ) -> dict:
    try:
        return json.loads( _state_file( name ).read_text() )
    except ( OSError, ValueError ):
        return { }


def _write( name: str, what: dict ):
    f = _state_file( name )
    tmp = f.with_name( f".{f.name}.{os.getpid()}.{threading.get_ident()}.tmp" )
    tmp.write_text( json.dumps( what, indent = 1 ) )
    os.replace( tmp, f )


def chosen( vid: str ) -> dict:
    return ( _read( "choices.json" ).get( vid ) or { } ) if vid else { }


def given_paths( m: str ) -> dict:
    return _read( "paths.json" ).get( m ) or { }


def _origin( vid ) -> dict:
    from . import static
    return static.origins().get( vid ) or { } if vid else { }


# ── the machines offered ─────────────────────────────────────────────────────

def offered( vid: str | None ) -> list:
    """here, the machine the run wrote the store on, then every machine of the ledger"""
    from .. import reach
    ms = reach.known()
    origin = _origin( vid ).get( "machine" )
    names = [ m[ "name" ] for m in ms ]
    if origin and not reach.is_here( origin ) and origin not in names and not any( origin in m.get( "names", [ ] ) for m in ms ):
        ms.append( { "name": origin, "here": False } )
    if origin:
        ms.sort( key = lambda m: ( not m[ "here" ], not ( m[ "name" ] == origin or origin in m.get( "names", [ ] ) ) ) )
    return ms


def _store( view_dir, vid, m: str ) -> dict:
    """what M is told of the store: where to look for it, which files to check, its size"""
    from .. import reach
    root = Path( view_dir )
    check, size, files = [ ], 0, 0
    for f in sorted( root.rglob( "*" ) ):
        if f.is_file():
            files += 1
            size += f.stat().st_size
    for rel in ( FILE, "index.html", "manifest.json" ):
        if ( root / rel ).is_file():
            check.append( [ rel, ( root / rel ).stat().st_size ] )
    origin = _origin( vid )
    paths, is_origin = [ ], False
    if origin.get( "path" ) and origin.get( "machine" ) == m:
        paths.append( origin[ "path" ] )
        is_origin = True
    paths.append( str( root ) )                          # ( a machine that shares this file system )
    return { "paths": paths, "original": is_origin, "copy": f"views/{vid}" if vid else None, "check": check,
             "size": size, "files": files }


def _request( view_dir, vid, m: str ) -> dict:
    """the `look` sent to M: each service with the description to propose from ( a package here first, else the store's )"""
    from .. import packages as P
    here_provs = { }
    try:
        for p in P.providers():
            for n, v in p.provided().items():
                here_provs.setdefault( ( n, v ), p )
    except Exception:
        pass
    services = { }
    for name, want in asked( view_dir ).items():
        p = here_provs.get( ( name, want[ "version" ] ) )
        services[ name ] = { "version": want[ "version" ], "protocol": want[ "protocol" ], "package": want[ "package" ],
                             "described": p.services()[ name ] if p else want[ "described" ],
                             "described_by": "here" if p else "store" }
        if p:
            services[ name ][ "described" ] = { **services[ name ][ "described" ], "package": p.data.get( "package" ) or { } }
    return { "do": "look", "machine": m, "services": services, "paths": given_paths( m ), "store": _store( view_dir, vid, m ) }


def look( view_dir, vid, m: str, refresh = False ) -> dict:
    """M's diagnosis, kept `KEPT` seconds ( `refresh`: asked again )"""
    from .. import reach
    k = ( vid or str( view_dir ), m )
    with _lock:
        got = _looks.get( k )
    if got and not refresh and time.monotonic() - got[ 0 ] < ( KEPT_HERE if reach.is_here( m ) else KEPT ):
        return got[ 1 ]
    box = { }

    def ask():
        box[ "a" ] = reach.ask( m, _request( view_dir, vid, m ), timeout = LOOK_TIMEOUT )

    t = threading.Thread( target = ask, daemon = True )
    t.start()
    t.join( LOOK_TIMEOUT + 1 )
    a = box.get( "a" ) or { "error": f"{m}: its agent said nothing within {LOOK_TIMEOUT:.0f} s", "unreachable": True }
    if a.get( "error" ):
        a = { "unreachable": True, "error": a[ "error" ], "services": { } }
    if a.get( "store" ) and a[ "store" ].get( "seen" ) == "none":
        c = _copies.get( k )
        if c:
            a[ "store" ][ "copying" ] = c
    with _lock:
        _looks[ k ] = ( time.monotonic(), a )
    return a


def _entry( want: dict, a: dict, name: str ) -> dict:
    if a.get( "unreachable" ):
        return { "state": "unreachable", "why": a.get( "error", "" ), "found": [ ], "lines": [ ], "store": { } }
    e = dict( ( a.get( "services" ) or { } ).get( name ) or { "state": "unknown", "why": "", "found": [ ], "lines": [ ] } )
    e[ "store" ] = a.get( "store" ) or { }
    if e.get( "state" ) in ( "ready", "running", "installable" ) and e[ "store" ].get( "seen" ) == "none":
        e[ "needs_copy" ] = True
    return e


ORDER = { "running": 0, "ready": 0, "installable": 1, "unverified": 2, "wrong version": 2, "unknown": 3, "unavailable": 4,
          "unreachable": 5 }


def default_machine( view_dir, vid, name: str ) -> str:
    """the first machine of the order where it is ready, else installable, here first; only machines already looked at"""
    ms = offered( vid )
    with _lock:
        known = { m: a for ( v, m ), ( t, a ) in _looks.items() if v == ( vid or str( view_dir ) ) }
    best, rank = ms[ 0 ][ "name" ], 9
    for m in ms:
        a = known.get( m[ "name" ] )
        if a is None:
            continue
        r = ORDER.get( _entry( { }, a, name ).get( "state" ), 9 )
        if r < rank:
            best, rank = m[ "name" ], r
    return best


def on( view_dir, vid, name: str ) -> str:
    return chosen( vid or str( view_dir ) ).get( name ) or default_machine( view_dir, vid, name )


def status( view_dir, vid: str | None = None ) -> dict:
    """`GET .errand/services`: each service the directory asks for, on the machine chosen"""
    out = { }
    for name, want in asked( view_dir ).items():
        m = on( view_dir, vid, name )
        e = _entry( want, look( view_dir, vid, m ), name )
        out[ name ] = { "version": want[ "version" ], "protocol": want[ "protocol" ], "optional": want[ "optional" ],
                        "text": want[ "text" ], "on": m, **e }
    if _machine.get( "error" ):
        out[ ".error" ] = _machine[ "error" ]
    return out


def machines_list( view_dir, vid ) -> list:
    """`GET .errand/machines`: in order, with each service's state where it is known ( `known: false` before )"""
    with _lock:
        known = { m: a for ( v, m ), ( t, a ) in _looks.items() if v == ( vid or str( view_dir ) ) }
    out = [ ]
    for m in offered( vid ):
        a = known.get( m[ "name" ] )
        row = { "name": m[ "name" ], "here": m[ "here" ], "known": a is not None,
                "origin": _origin( vid ).get( "machine" ) in ( m[ "name" ], *m.get( "names", [ ] ) ) }
        if a is not None:
            row[ "services" ] = { n: { k: e.get( k ) for k in ( "state", "why" ) }
                                  for n in asked( view_dir ) for e in [ _entry( { }, a, n ) ] }
        out.append( row )
    return out


# ── the copy of a view on another machine ────────────────────────────────────

def copy( view_dir, vid: str, m: str ) -> dict:
    """the view's files pushed into errand's cache on M, again while the page asks about M ( `_keep_copy` )"""
    from .. import reach
    if not vid:
        return { "error": "a view without an id cannot be copied" }
    if reach.is_here( m ):
        return { "error": "this machine serves the view: nothing to copy" }
    k = ( vid, m )
    with _lock:
        c = _copies.get( k )
        if c and c.get( "state" ) == "copying":
            return c
        _copies[ k ] = c = { "state": "copying", "done": 0.0, "last_asked": time.monotonic() }
    threading.Thread( target = _keep_copy, args = ( view_dir, vid, m ), daemon = True ).start()
    return c


def _keep_copy( view_dir, vid, m ):
    from .. import agents, reach, sync as SY
    from ..agents import syncop
    k = ( vid, m )
    while True:
        c = _copies[ k ]
        try:
            got = reach.ask( m, { "do": "copy_into", "vid": vid } )
            if got.get( "error" ):
                raise RuntimeError( got[ "error" ] )
            syncop.push( agents.open( reach.target( m ), noted = False ), view_dir, got[ "root" ],
                         SY.Selection( [ ], False, [ ] ), where = m, say = lambda *a, **kw: None )
            c.update( state = "copied", done = 1.0, at = time.time() )
            c.pop( "error", None )
            with _lock:
                _looks.pop( k, None )                          # ( M sees it now: looked at again )
        except Exception as err:
            c.update( state = "failed", error = f"{type( err ).__name__}: {err}" )
            return
        # ( kept up to date while the page asks: every 10 s, as long as it asked within the last minute )
        time.sleep( 10 )
        if time.monotonic() - c.get( "last_asked", 0 ) > 60:
            c[ "state" ] = "copied"
            return


def _asked_now( vid ):
    with _lock:
        for ( v, m ), c in _copies.items():
            if v == vid:
                c[ "last_asked" ] = time.monotonic()


# ── the relay ────────────────────────────────────────────────────────────────

def refused( view_dir, name: str, vid: str | None = None ) -> str | None:
    """why `name` cannot be reached from this view on this machine ( None: it can )"""
    want = asked( view_dir ).get( name )
    if want is None:
        return f"this directory's {FILE} does not name {name!r}"
    key = key_of( name, want )
    if key not in machine():
        return f"this machine declares no service {key!r}"
    return None


def _pump( src, dst, limit = None ):
    """bytes from `src` ( a file with `read1`, or a socket ) to the socket `dst`, until EOF ( or `limit` bytes )"""
    left = limit
    try:
        while left is None or left > 0:
            n = 65536 if left is None else min( 65536, left )
            chunk = src.read1( n ) if hasattr( src, "read1" ) else src.recv( n )
            if not chunk:
                break
            dst.sendall( chunk )
            if left is not None:
                left -= len( chunk )
    except OSError:
        pass


def _head( sock ) -> tuple[ bytes, bytes ]:
    """the answer's head ( up to the blank line ) and what came after it"""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv( 65536 )
        if not chunk:
            break
        buf += chunk
        if len( buf ) > 1 << 20:
            raise OSError( "an answer's head over 1 MB" )
    head, _, rest = buf.partition( b"\r\n\r\n" )
    return head, rest


def _upstream( view_dir, vid, name: str ) -> tuple:
    """( host, port, the store's directory as the service's machine sees it ) for `name` on the machine chosen"""
    from .. import reach, serve as S
    want = asked( view_dir )[ name ]
    key = key_of( name, want )
    m = on( view_dir, vid, name )
    if reach.is_here( m ):
        why = refused( view_dir, name, vid )
        if why:
            raise PermissionError( why )
        st = S.ensure( key, cwd = str( S.home() ) )
        host, port = S.address( st ).rsplit( ":", 1 )
        return host, int( port ), str( view_dir )
    a = look( view_dir, vid, m )
    seen = ( a.get( "store" ) or { } )
    if not seen.get( "path" ):
        raise LookupError( f"{m} has no copy of this store: copy it there first" )
    with _lock:
        lst = _forwards.get( ( m, key ) )
    if lst is None:
        lst = S.forward( reach.target( m ), key )
        with _lock:
            _forwards[ ( m, key ) ] = lst
    return "127.0.0.1", lst.getsockname()[ 1 ], seen[ "path" ]


def relay( h, view_dir, name: str, rest: str, vid: str | None = None ):
    """the request `h` ( a `BaseHTTPRequestHandler` ) to the service `name` as `/rest`, its answer back"""
    try:
        host, port, root = _upstream( view_dir, vid, name )
        up = socket.create_connection( ( host, int( port ) ), timeout = 30 )
    except PermissionError as err:
        return h._send( 403, str( err ).encode() )
    except Exception as err:
        return h._send( 503, f"service {name!r}: {err}".encode() )
    up.settimeout( None )
    upgrade = ( h.headers.get( "Upgrade" ) or "" ).strip()
    lines = [ f"{h.command} /{rest} {h.request_version}" ]
    for k, v in h.headers.items():
        if k.lower() not in HOP and not ( k.lower() == "upgrade" and not upgrade ):
            lines.append( f"{k}: {v}" )
    lines += [ f"Host: {host}:{port}", f"X-Errand-Root: {quote( str( root ), safe = '/' )}",
               "Connection: Upgrade" if upgrade else "Connection: close" ]
    h.close_connection = True
    try:
        up.sendall( ( "\r\n".join( lines ) + "\r\n\r\n" ).encode( "latin-1", "replace" ) )
        size = h.headers.get( "Content-Length" )
        if upgrade:
            body = threading.Thread( target = _pump, args = ( h.rfile, up ), daemon = True )
            body.start()
        elif size is not None:
            _pump( h.rfile, up, int( size ) )
        elif "chunked" in ( h.headers.get( "Transfer-Encoding" ) or "" ).lower():
            threading.Thread( target = _pump, args = ( h.rfile, up ), daemon = True ).start()
        head, after = _head( up )
        if not head:
            return h._send( 502, f"service {name!r} answered nothing".encode() )
        first, *fields = head.decode( "latin-1" ).split( "\r\n" )
        switching = first.split( " " )[ 1 : 2 ] == [ "101" ]
        kept = [ f for f in fields if f.split( ":", 1 )[ 0 ].strip().lower() not in ( "connection", "keep-alive" ) ]
        kept.append( "Connection: Upgrade" if switching else "Connection: close" )
        h.wfile.write( ( "\r\n".join( [ first, *kept ] ) + "\r\n\r\n" ).encode( "latin-1" ) + after )
        _pump( up, h.connection )
    except OSError:
        pass
    finally:
        try:
            up.close()
        except OSError:
            pass


# ── the routes ───────────────────────────────────────────────────────────────

def _body( h ) -> dict:
    try:
        n = int( h.headers.get( "Content-Length" ) or 0 )
        got = json.loads( h.rfile.read( n ) or b"{}" ) if 0 < n < 1 << 16 else { }
        return got if isinstance( got, dict ) else { }
    except ( ValueError, OSError ):
        return { }


def _json( h, what, head = False, code = 200 ):
    return h._send( code, json.dumps( what, indent = 1 ).encode(), "application/json; charset=utf-8", head )


def answer( h, view_dir, parts: list, head: bool, vid: str | None = None ):
    """`<view>/.errand/...` -> the status, the machines, a choice, a copy, a path, or the relay"""
    from .. import reach
    get = h.command in ( "GET", "HEAD" )
    query = h.path.split( "?", 1 )[ 1 ] if "?" in h.path else ""
    if vid:
        _asked_now( vid )
    if parts == [ "services" ] and get:
        return _json( h, status( view_dir, vid ), head )
    if parts == [ "machines" ] and get:
        return _json( h, machines_list( view_dir, vid ), head )
    if len( parts ) == 2 and parts[ 0 ] == "machines" and get:
        m = unquote( parts[ 1 ] )
        if m not in [ x[ "name" ] for x in offered( vid ) ] and not reach.is_here( m ):
            return h._send( 404, f"{m}: not a machine offered".encode(), head = head )
        a = look( view_dir, vid, m, refresh = "refresh=1" in query.split( "&" ) )
        return _json( h, { "name": m, "store": a.get( "store" ) or { }, "platform": a.get( "platform" ),
                           "cards": a.get( "cards" ) or [ ], "unreachable": bool( a.get( "unreachable" ) ),
                           "error": a.get( "error" ),
                           "services": { n: _entry( w, a, n ) for n, w in asked( view_dir ).items() } }, head )
    if len( parts ) == 2 and parts[ 0 ] == "services" and h.command == "POST":
        name, m = unquote( parts[ 1 ] ), str( _body( h ).get( "on" ) or "" )
        if name not in asked( view_dir ):
            return h._send( 404, f"this directory's {FILE} does not name {name!r}".encode() )
        if m not in [ x[ "name" ] for x in offered( vid ) ]:
            return h._send( 403, f"{m!r}: not a machine offered".encode() )
        with _lock:
            got = _read( "choices.json" )
            got.setdefault( vid or str( view_dir ), { } )[ name ] = m
            _write( "choices.json", got )
        return _json( h, { "ok": True, "on": m } )
    if parts == [ "copy" ] and h.command == "POST":
        m = str( _body( h ).get( "on" ) or "" )
        if m not in [ x[ "name" ] for x in offered( vid ) ]:
            return h._send( 403, f"{m!r}: not a machine offered".encode() )
        return _json( h, copy( view_dir, vid, m ) )
    if len( parts ) == 3 and parts[ 0 ] == "machines" and parts[ 2 ] == "paths" and h.command == "POST":
        m, b = unquote( parts[ 1 ] ), _body( h )
        tool, path = str( b.get( "tool" ) or "" ), str( b.get( "path" ) or "" )
        if not tool or not path or "\n" in path:
            return h._send( 400, b"{ tool, path }" )
        with _lock:
            got = _read( "paths.json" )
            lst = got.setdefault( m, { } ).setdefault( tool, [ ] )
            if path not in lst:
                lst.append( path )
            _write( "paths.json", got )
            _looks.pop( ( vid or str( view_dir ), m ), None )
        return _json( h, { "ok": True } )
    if len( parts ) >= 2 and parts[ 0 ] == "svc":
        name = parts[ 1 ]
        if name not in asked( view_dir ):
            return h._send( 403, f"this directory's {FILE} does not name {name!r}".encode(), head = head )
        rest = "/".join( parts[ 2: ] )
        return relay( h, view_dir, name, rest + ( f"?{query}" if "?" in h.path else "" ), vid )
    return h._send( 404, b"not found", head = head )
