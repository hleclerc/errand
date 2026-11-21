"""A page asks for its services ( ADR 0026, 0027 ): `services.json` in the view ( format 2: `name#version` ), `.errand/services`,
the machine chosen per service, `.errand/machines`, the copy, the relay `.errand/svc/` here and through another machine's agent."""
import contextlib
import http.client
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

from errand import test

TOY = r'''
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H( BaseHTTPRequestHandler ):
    def log_message( self, *a ): pass
    def do_GET( self ):
        if self.headers.get( "Upgrade" ):                       # ( a WebSocket, roughly: the switch, then echo in capitals )
            self.send_response( 101 ); self.send_header( "Upgrade", "websocket" ); self.send_header( "Connection", "Upgrade" )
            self.end_headers(); self.wfile.flush()
            c = self.connection
            for chunk in iter( lambda: c.recv( 4096 ), b"" ):
                c.sendall( chunk.upper() )
            self.close_connection = True
            return
        body = json.dumps( { "path": self.path, "root": self.headers.get( "X-Errand-Root" ), "host": self.headers.get( "Host" ) } ).encode()
        self.send_response( 200 ); self.send_header( "Content-Type", "application/json" )
        self.send_header( "Content-Length", str( len( body ) ) ); self.end_headers(); self.wfile.write( body )
    def do_POST( self ):
        b = self.rfile.read( int( self.headers[ "Content-Length" ] ) )[ ::-1 ]
        self.send_response( 200 ); self.send_header( "Content-Length", str( len( b ) ) ); self.end_headers(); self.wfile.write( b )
ThreadingHTTPServer( ( "127.0.0.1", int( os.environ[ "PORT" ] ) ), H ).serve_forever()
'''


@contextlib.contextmanager
def place( far = False ):
    """a cache, a queue, a config of our own; a view `v` with its `services.json`; the static server on a free port;
    `far`: a second machine, `far`, reached through a local agent ( the same files: a machine sharing this file system )"""
    keys = ( "ERRAND_CACHE_DIR", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "ERRAND_SERVE_NO_AGENT", "PYTHONPATH", "ERRAND_AGENT" )
    before = { k: os.environ.get( k ) for k in keys }
    with tempfile.TemporaryDirectory( dir = "/tmp" ) as tmp:
        tmp = Path( tmp ).resolve()
        ( tmp / "run" ).mkdir()
        ( tmp / "config" / "errand" ).mkdir( parents = True )
        os.environ.update( ERRAND_CACHE_DIR = str( tmp / "cache" ), XDG_RUNTIME_DIR = str( tmp / "run" ),
                           XDG_CONFIG_HOME = str( tmp / "config" ), ERRAND_SERVE_NO_AGENT = "1", ERRAND_AGENT = "direct",
                           PYTHONPATH = os.pathsep.join( p for p in sys.path if p ) )
        ( tmp / "toy.py" ).write_text( TOY )
        cmd = repr( [ sys.executable, str( tmp / "toy.py" ) ] )
        ( tmp / "config" / "errand" / "services.py" ).write_text(
            f"import errand\nerrand.services[ 'toy#v1' ] = errand.Service( {cmd}, idle = '5s' )\n"
            f"errand.services[ 'other#v1' ] = errand.Service( {cmd}, idle = '5s' )\n" )
        view = tmp / "a view é"
        view.mkdir()
        ( view / "index.html" ).write_text( "<html>page</html>" )
        ( view / "services.json" ).write_text( json.dumps( { "format": 2, "services": {
            "toy":   { "version": "v1", "protocol": 1 },
            "ghost": { "version": "g1", "protocol": 2, "package": { "name": "ghostpkg", "version": "1.0" },
                       "described": { "text": "a service nobody declared", "package": { "pip": "ghostpkg" } } } } } ) )
        from errand import agents, reach, serve as S
        from errand.web import page_services, static
        page_services._machine.update( stamp = None, names = { } )
        page_services._looks.clear()
        static.register( "v", view, tmp / "cache" )
        httpd = static.start( tmp / "cache", at = 0 )
        target = { "kind": "local", "dir": str( tmp / "agent" ), "keep_alive": 30 }
        known = reach.known
        if far:
            reach.known = lambda: [ { "name": reach.here_name(), "here": True },
                                    { "name": "far", "here": False, "target": target, "names": [ "far" ] } ]
        try:
            yield tmp, view, httpd.server_address[ 1 ], static.token( tmp / "cache" ), S
        finally:
            reach.known = known
            httpd.shutdown()
            for lst in page_services._forwards.values():
                lst.close()
            page_services._forwards.clear()
            for st in S.running():
                S.stop( st[ "name" ], wait = 15 )
            if far:
                with contextlib.suppress( Exception ):
                    agents.open( target ).open( { "op": "stop", "force": True } ).reply( 10 )
            for k, v in before.items():
                os.environ.pop( k, None ) if v is None else os.environ.__setitem__( k, v )


def call( port, method, path, body = None ):
    c = http.client.HTTPConnection( "127.0.0.1", port, timeout = 60 )
    c.request( method, path, body = body, headers = { "Host": f"127.0.0.1:{port}" } )
    r = c.getresponse()
    out = r.read()
    c.close()
    return r.status, out


if test( "a page sees its services on the machine chosen ( here by default ): ready, or the lines to type" ):
    with place() as ( tmp, view, port, tok, S ):
        code, body = call( port, "GET", f"/{tok}/v/.errand/services" )
        got = json.loads( body )
        assert code == 200 and set( got ) == { "toy", "ghost" }, got        # ( `other`: declared, but not asked for )
        toy, ghost = got[ "toy" ], got[ "ghost" ]
        assert toy[ "state" ] == "ready" and toy[ "version" ] == "v1" and toy[ "store" ][ "seen" ] != "none", toy
        assert ghost[ "state" ] == "installable" and ghost[ "text" ] == "a service nobody declared", ghost
        fetch, install = ghost[ "lines" ]
        assert "pip:ghostpkg==1.0" in fetch[ "command" ] and not fetch[ "unknown_source" ] and fetch[ "described_by" ] == "store"
        assert install[ "command" ].endswith( " ghost#g1" ), install
        assert call( port, "GET", f"/wrong/v/.errand/services" )[ 0 ] == 404
        ms = json.loads( call( port, "GET", f"/{tok}/v/.errand/machines" )[ 1 ] )
        assert ms[ 0 ][ "here" ] and ms[ 0 ][ "known" ], ms


if test( "only what both sides name is relayed; files stay read only; a choice only among the machines offered" ):
    with place() as ( tmp, view, port, tok, S ):
        assert call( port, "GET", f"/{tok}/v/.errand/svc/other/x" )[ 0 ] == 403, "declared here, not asked for"
        assert call( port, "GET", f"/{tok}/v/.errand/svc/ghost/x" )[ 0 ] == 403, "asked for, declared nowhere"
        assert call( port, "PUT", f"/{tok}/v/index.html", b"no" )[ 0 ] == 405
        assert call( port, "POST", f"/{tok}/v/.errand/services/toy", b'{"on": "elsewhere"}' )[ 0 ] == 403
        assert call( port, "POST", f"/{tok}/v/.errand/copy", b'{"on": "elsewhere"}' )[ 0 ] == 403
        assert not S.running(), "nothing started"


if test( "the relay: the service ensured, the path, the view's directory, a body, a WebSocket" ):
    with place() as ( tmp, view, port, tok, S ):
        code, body = call( port, "GET", f"/{tok}/v/.errand/svc/toy/field/a%20b?x=1&y=2" )
        got = json.loads( body )
        assert code == 200 and got[ "path" ] == "/field/a%20b?x=1&y=2", got
        from urllib.parse import unquote
        assert unquote( got[ "root" ] ) == str( view ), got
        assert S.state( "toy#v1" )[ "state" ] in ( "busy", "idle", "running" ), S.state( "toy#v1" )
        import time
        time.sleep( 2.1 )                                      # ( this machine's diagnosis is kept 2 s )
        assert json.loads( call( port, "GET", f"/{tok}/v/.errand/services" )[ 1 ] )[ "toy" ][ "state" ] == "running"
        assert call( port, "POST", f"/{tok}/v/.errand/svc/toy/rev", b"abcdef" ) == ( 200, b"fedcba" )
        with socket.create_connection( ( "127.0.0.1", port ), timeout = 30 ) as c:
            c.sendall( ( f"GET /{tok}/v/.errand/svc/toy/ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                         "Connection: Upgrade\r\n\r\n" ).encode() )
            buf = b""
            while b"\r\n\r\n" not in buf:
                buf += c.recv( 4096 )
            head, _, rest = buf.partition( b"\r\n\r\n" )
            assert head.startswith( b"HTTP/1.0 101" ) and b"Connection: Upgrade" in head, head
            c.sendall( b"frames pass" )
            while len( rest ) < 11:
                rest += c.recv( 4096 )
            assert rest == b"FRAMES PASS", rest


if test( "another machine chosen: its agent's diagnosis, the relay through it, the store copied there by the page" ):
    with place( far = True ) as ( tmp, view, port, tok, S ):
        ms = json.loads( call( port, "GET", f"/{tok}/v/.errand/machines" )[ 1 ] )
        assert [ m[ "name" ] for m in ms ][ 1: ] == [ "far" ], ms
        got = json.loads( call( port, "GET", f"/{tok}/v/.errand/machines/far" )[ 1 ] )
        assert not got[ "unreachable" ] and got[ "services" ][ "toy" ][ "state" ] == "ready", got
        assert got[ "store" ][ "seen" ] == "shared" and got[ "store" ][ "path" ] == str( view ), got[ "store" ]
        assert call( port, "POST", f"/{tok}/v/.errand/services/toy", b'{"on": "far"}' )[ 0 ] == 200
        assert json.loads( call( port, "GET", f"/{tok}/v/.errand/services" )[ 1 ] )[ "toy" ][ "on" ] == "far"
        code, body = call( port, "GET", f"/{tok}/v/.errand/svc/toy/over?there=1" )
        got = json.loads( body )
        from urllib.parse import unquote
        assert code == 200 and got[ "path" ] == "/over?there=1" and unquote( got[ "root" ] ) == str( view ), ( code, body )
        assert call( port, "POST", f"/{tok}/v/.errand/machines/far/paths", b'{"tool": "painter", "path": "/opt/p"}' )[ 0 ] == 200
        assert json.loads( call( port, "POST", f"/{tok}/v/.errand/copy", b'{"on": "far"}' )[ 1 ] )[ "state" ] in ( "copying", "copied" )
        import time
        from errand.web import page_services as PS
        deadline = time.monotonic() + 60
        while PS._copies[ ( "v", "far" ) ][ "state" ] == "copying" and time.monotonic() < deadline:
            time.sleep( 0.2 )
        assert PS._copies[ ( "v", "far" ) ][ "state" ] == "copied", PS._copies
        assert ( tmp / "cache" / "views" / "v" / "index.html" ).read_text() == "<html>page</html>"
