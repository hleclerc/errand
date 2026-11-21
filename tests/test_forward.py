"""`errand serve forward` ( ADR 0018 step 6 ): a port here, each connection a channel to a service through an agent."""
import contextlib
import json
import os
import socket
import sys
import tempfile
import urllib.request
from pathlib import Path

from errand import test

TOY = r'''
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H( BaseHTTPRequestHandler ):
    def log_message( self, *a ): pass
    def do_GET( self ):
        if self.path == "/big":
            b = os.urandom( 3 << 20 )
        else:
            b = json.dumps( { "path": self.path } ).encode()
        self.send_response( 200 ); self.send_header( "Content-Length", str( len( b ) ) ); self.end_headers(); self.wfile.write( b )
    def do_POST( self ):
        b = self.rfile.read( int( self.headers[ "Content-Length" ] ) )[ ::-1 ]
        self.send_response( 200 ); self.send_header( "Content-Length", str( len( b ) ) ); self.end_headers(); self.wfile.write( b )
ThreadingHTTPServer( ( "127.0.0.1", int( os.environ[ "PORT" ] ) ), H ).serve_forever()
'''


@contextlib.contextmanager
def place( ):
    """a cache, a config, a queue of our own; a toy service declared; a local agent, reached directly ( no hub )"""
    keys = ( "ERRAND_CACHE_DIR", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "ERRAND_SERVE_NO_AGENT", "PYTHONPATH", "ERRAND_AGENT" )
    before = { k: os.environ.get( k ) for k in keys }
    with tempfile.TemporaryDirectory( dir = "/tmp" ) as tmp:
        tmp = Path( tmp ).resolve()
        ( tmp / "run" ).mkdir()
        ( tmp / "config" / "errand" ).mkdir( parents = True )
        ( tmp / "toy.py" ).write_text( TOY )
        ( tmp / "config" / "errand" / "services.py" ).write_text(
            f"import errand\nerrand.services[ 'toy' ] = errand.Service( [ {sys.executable!r}, {str( tmp / 'toy.py' )!r} ], idle = '10s' )\n" )
        os.environ.update( ERRAND_CACHE_DIR = str( tmp / "cache" ), XDG_RUNTIME_DIR = str( tmp / "run" ),
                           XDG_CONFIG_HOME = str( tmp / "config" ), ERRAND_SERVE_NO_AGENT = "1", ERRAND_AGENT = "direct",
                           PYTHONPATH = os.pathsep.join( p for p in sys.path if p ) )
        from errand import agents, serve as S
        target = { "kind": "local", "dir": str( tmp / "agent" ), "keep_alive": 20 }
        try:
            yield tmp, target, S
        finally:
            for st in S.running():
                S.stop( st[ "name" ], wait = 15 )
            with contextlib.suppress( Exception ):
                agents.open( target ).open( { "op": "stop", "force": True } ).reply( 10 )
            for k, v in before.items():
                os.environ.pop( k, None ) if v is None else os.environ.__setitem__( k, v )


if test( "a forwarded port: requests, bodies, several connections, a large answer; the service started over there" ):
    with place() as ( tmp, target, S ):
        said = [ ]
        lst = S.forward( target, "toy", echo = said.append )
        base = f"http://127.0.0.1:{lst.getsockname()[ 1 ]}"
        assert json.loads( urllib.request.urlopen( base + "/a?b=1", timeout = 60 ).read() ) == { "path": "/a?b=1" }
        assert S.state( "toy" )[ "state" ] not in ( "stopped", "failed" ), "ensured by the agent"
        req = urllib.request.Request( base + "/rev", data = b"abcdef", method = "POST" )
        assert urllib.request.urlopen( req, timeout = 30 ).read() == b"fedcba"
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor( 8 ) as ex:
            got = list( ex.map( lambda i: json.loads( urllib.request.urlopen( f"{base}/{i}", timeout = 30 ).read() )[ "path" ], range( 16 ) ) )
        assert got == [ f"/{i}" for i in range( 16 ) ], said
        assert not said, said
        assert len( urllib.request.urlopen( base + "/big", timeout = 60 ).read() ) == 3 << 20
        lst.close()


if test( "only a declared service: another name is refused, the connection closed" ):
    with place() as ( tmp, target, S ):
        said = [ ]
        lst = S.forward( target, "nobody", echo = said.append )
        with socket.create_connection( lst.getsockname(), timeout = 30 ) as c:
            c.sendall( b"GET / HTTP/1.0\r\n\r\n" )
            try:
                assert c.recv( 100 ) == b""
            except ConnectionResetError:                      # ( closed with our request unread: a reset, as good )
                pass
        assert said and "no service 'nobody'" in said[ 0 ], said
        lst.close()
