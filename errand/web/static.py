"""The views a run opens as they are ( `errand.Static`, ADR 0017 §5 ): a directory carrying its own page ( a scene
store: `foam.sviz/index.html`, its manifest, its frames ), served from the copy here, on a server of its own beside
`errand web`.

    address     127.0.0.1, port `web.port_of_user() + 2` ( `+ 1` is `errand web dev` ), any free one when taken
    URL         http://127.0.0.1:<port>/<token>/<id>/          the token IN THE PATH, kept in `static-token` ( 0600 )
    what        only the directories registered in `static-views.json` ( { id: local path } ), read at each request:
                files, read-only, never above their directory; `index.html` for the directory itself
    .errand/    reserved in every view: the services its `services.json` asks for, and a relay to them ( ADR 0026,
                `page_services` ) -- the only thing a page can make run, and only what this machine declares

Why not `errand web` itself: its preview is a sandboxed iframe ( an opaque origin ), which cannot read the files beside
a page with the cookie, and `allow-same-origin` there would let a run's page post to `/act`. On this origin, the page
needs no cookie and reaches nothing of errand: a token in the path, as `sviz` does.

The id of a view is the same for whoever computes it ( `view_id` ): the side that drives a run registers the copy
it brought back ( `cli.views` ), the page of the run finds it from the run's leaf and the view's path in it.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import secrets
import threading
from pathlib import Path

from .. import bootstrap

TOKEN = "static-token"
VIEWS = "static-views.json"
SAID  = "static.json"


def port( ) -> int:
    from . import port_of_user
    return port_of_user() + 2


def view_id( leaf: str, rel: str ) -> str:
    """a view by its run ( its directory over there, `seen.ident` ) and its path in it"""
    from ..agents.seen import ident
    return hashlib.sha1( f"{ident( leaf )}/{rel.strip( '/' )}".encode() ).hexdigest()[ : 16 ]


def token( cache: Path | None = None ) -> str:
    """the token of the URLs, the same from one start to the next ( its user's only )"""
    cache = Path( cache or bootstrap.local_cache() )
    path = cache / TOKEN
    try:
        got = path.read_text().strip()
        if len( got ) >= 32:
            return got
    except OSError:
        pass
    cache.mkdir( parents = True, exist_ok = True )
    fresh = secrets.token_urlsafe( 24 )
    tmp = path.with_name( f".{TOKEN}.{os.getpid()}.tmp" )
    fd = os.open( str( tmp ), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 )
    with os.fdopen( fd, "w" ) as f:
        f.write( fresh )
    try:
        os.link( tmp, path )                          # the first one written wins: two at once agree
    except FileExistsError:
        pass
    finally:
        tmp.unlink( missing_ok = True )
    return path.read_text().strip()


def registered( cache: Path | None = None ) -> dict:
    try:
        return json.loads( ( Path( cache or bootstrap.local_cache() ) / VIEWS ).read_text() )
    except ( OSError, ValueError ):
        return { }


ORIGINS = "static-origins.json"


def origins( cache: Path | None = None ) -> dict:
    """{ vid: { machine, path } }: where a view's directory was written ( the run's machine ), when it is known"""
    try:
        return json.loads( ( Path( cache or bootstrap.local_cache() ) / ORIGINS ).read_text() )
    except ( OSError, ValueError ):
        return { }


def register( vid: str, local_dir, cache: Path | None = None, origin: dict | None = None ):
    """the directory `local_dir` served as view `vid`; `origin`: { machine, path } of the directory the run wrote"""
    cache = Path( cache or bootstrap.local_cache() )
    local_dir = str( Path( local_dir ).resolve() )
    if origin and origins( cache ).get( vid ) != origin:
        got = origins( cache )
        got[ vid ] = origin
        cache.mkdir( parents = True, exist_ok = True )
        tmp = cache / f".{ORIGINS}.{os.getpid()}.{threading.get_ident()}.tmp"
        tmp.write_text( json.dumps( got, indent = 1 ) )
        os.replace( tmp, cache / ORIGINS )
    views = registered( cache )
    if views.get( vid ) == local_dir:
        return
    views[ vid ] = local_dir
    cache.mkdir( parents = True, exist_ok = True )
    tmp = cache / f".{VIEWS}.{os.getpid()}.{threading.get_ident()}.tmp"
    tmp.write_text( json.dumps( views, indent = 1 ) )
    os.replace( tmp, cache / VIEWS )


def serving( cache: Path | None = None ) -> bool:
    """whether the server said in `static.json` is there"""
    try:
        pid = json.loads( ( Path( cache or bootstrap.local_cache() ) / SAID ).read_text() )[ "pid" ]
        os.kill( int( pid ), 0 )
        return True
    except ( OSError, ValueError, KeyError, TypeError ):
        return False


def url( vid: str, index: str = "index.html", cache: Path | None = None ) -> str:
    """where view `vid` opens: at the port the server says, else at its user's ( the one it takes when it starts )"""
    cache = Path( cache or bootstrap.local_cache() )
    try:
        p = json.loads( ( cache / SAID ).read_text() )[ "port" ]
    except ( OSError, ValueError, KeyError ):
        p = port()
    return f"http://127.0.0.1:{p}/{token( cache )}/{vid}/" + ( "" if index == "index.html" else index )


# ── the server ───────────────────────────────────────────────────────────────

def start( cache: Path | None = None, at = None ):
    """Served from a thread of this process ( the host agent, beside `errand web` ) -> the server, or None when the
    port and any other are refused. `at`: a port ( 0: any; the tests )."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    cache = Path( cache or bootstrap.local_cache() )
    tok = token( cache )

    class Handler( BaseHTTPRequestHandler ):
        server_version = "errand-static"

        def log_message( self, *args ):
            pass

        def _send( self, code, body = b"", kind = "text/plain; charset=utf-8", head = False ):
            self.send_response( code )
            self.send_header( "Content-Type", kind )
            self.send_header( "Content-Length", str( len( body ) ) )
            self.send_header( "Cache-Control", "no-store" )
            self.send_header( "X-Content-Type-Options", "nosniff" )
            self.send_header( "Referrer-Policy", "no-referrer" )
            self.end_headers()
            if not head:
                self.wfile.write( body )

        def _route( self, head ):
            host = ( self.headers.get( "Host" ) or "" ).split( ":" )[ 0 ]
            if host not in ( "127.0.0.1", "localhost" ):
                return self._send( 403, b"not for this address", head = head )
            parts = self.path.split( "?" )[ 0 ].split( "/" )[ 1: ]
            if not parts or not secrets.compare_digest( parts[ 0 ], tok ):
                return self._send( 404, b"not found", head = head )
            if len( parts ) < 2 or parts[ 1 ] not in ( views := registered( cache ) ):
                return self._send( 404, b"no such view here", head = head )
            if len( parts ) >= 3 and parts[ 2 ] == ".errand":           # what the page asks errand for ( ADR 0026 )
                from . import page_services
                return page_services.answer( self, str( Path( views[ parts[ 1 ] ] ).resolve() ), parts[ 3: ], head, parts[ 1 ] )
            if self.command not in ( "GET", "HEAD" ):
                return self._send( 405, b"files are read only", head = head )
            if len( parts ) == 2:                               # ( the files are read relative to the page )
                self.send_response( 301 )
                self.send_header( "Location", self.path.split( "?" )[ 0 ] + "/" )
                self.send_header( "Content-Length", "0" )
                self.end_headers()
                return
            root = Path( views[ parts[ 1 ] ] ).resolve()
            from urllib.parse import unquote
            rel = unquote( "/".join( parts[ 2: ] ) ) or "index.html"
            f = ( root / rel ).resolve()
            if root not in f.parents or not f.is_file():
                return self._send( 404, b"not found", head = head )
            kind = mimetypes.guess_type( f.name )[ 0 ] or "application/octet-stream"
            if kind.startswith( "text/" ) or kind in ( "application/json", "application/javascript" ):
                kind += "; charset=utf-8"
            return self._send( 200, f.read_bytes(), kind, head )

        def do_GET( self ):
            self._route( False )

        def do_HEAD( self ):
            self._route( True )

        def do_POST( self ):                                   # ( only `.errand/svc/...`: relayed to a service )
            self._route( False )

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST

    httpd = None
    for p in ( ( at, ) if at is not None else ( port(), 0 ) ):
        try:
            httpd = ThreadingHTTPServer( ( "127.0.0.1", p ), Handler )
            break
        except OSError:
            continue
    if httpd is None:
        return None
    httpd.daemon_threads = True
    path = cache / SAID
    tmp = path.with_suffix( ".tmp" )
    tmp.write_text( json.dumps( { "port": httpd.server_address[ 1 ], "pid": os.getpid() } ) )
    tmp.replace( path )
    threading.Thread( target = httpd.serve_forever, kwargs = { "poll_interval": 0.5 }, daemon = True ).start()
    return httpd
