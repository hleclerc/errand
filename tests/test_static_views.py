"""Views opened as they are ( `errand.Static`, ADR 0017 §5 ): a directory that carries its page, served from the copy
here on a server of its own ( `web.static` ) and framed by the run's page -- not said in the terminal, where the run's
page is."""
import contextlib
import http.client
import json
import os
import shutil
import tempfile
from pathlib import Path

from errand import test


@contextlib.contextmanager
def scratch( ):
    d = Path( tempfile.mkdtemp( dir = "/tmp" ) ).resolve()
    was = os.environ.get( "ERRAND_CACHE_DIR" )
    os.environ[ "ERRAND_CACHE_DIR" ] = str( d / "cache" )
    try:
        yield d
    finally:
        os.environ.pop( "ERRAND_CACHE_DIR", None ) if was is None else os.environ.__setitem__( "ERRAND_CACHE_DIR", was )
        shutil.rmtree( d, ignore_errors = True )


def get( port, path ):
    c = http.client.HTTPConnection( "127.0.0.1", port, timeout = 10 )
    c.request( "GET", path, headers = { "Host": f"127.0.0.1:{port}" } )
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, dict( r.getheaders() ), body


def store( d: Path ) -> Path:
    s = d / "leaf" / "foam.sviz"
    ( s / "frames" ).mkdir( parents = True )
    ( s / "index.html" ).write_text( "<html>page</html>" )
    ( s / "manifest.json" ).write_text( json.dumps( { "complete": False, "frames": [ { "file": "frames/000000.bin" } ] } ) )
    ( s / "frames" / "000000.bin" ).write_bytes( b"\x01\x02" )
    ( d / "secret.txt" ).write_text( "no" )
    return s


if test( "the journal says what opens a view; its summary keeps it" ):
    import errand
    from errand import steps
    with scratch() as d:
        journal = d / steps.FILE
        was = os.environ.get( steps.ENV )
        os.environ[ steps.ENV ] = str( journal )
        try:
            errand.view( str( d ), last = "manifest.json", open = errand.Static( "index.html" ) )
        finally:
            os.environ.pop( steps.ENV, None ) if was is None else os.environ.__setitem__( steps.ENV, was )
        e = json.loads( journal.read_text().splitlines()[ -1 ] )
        assert e[ "open" ] == [ { "static": "index.html" } ], e
        assert steps.summarize( steps.parse( journal.read_bytes() ) )[ "views" ][ 0 ][ "open" ] == [ { "static": "index.html" } ]

if test( "the static server: a registered directory by its id, behind the token in the path; nothing else" ):
    from errand.web import static as S
    with scratch() as d:
        s = store( d )
        httpd = S.start( at = 0 )
        try:
            port = httpd.server_address[ 1 ]
            vid = S.view_id( "/over/there/leaf", "foam.sviz" )
            assert vid == S.view_id( "/over/there/leaf", "/foam.sviz/" ) and len( vid ) == 16
            S.register( vid, s )
            u = S.url( vid )
            tok = S.token()
            assert u == f"http://127.0.0.1:{port}/{tok}/{vid}/", u
            assert ( Path( os.environ[ "ERRAND_CACHE_DIR" ] ) / S.TOKEN ).stat().st_mode & 0o077 == 0
            code, headers, body = get( port, f"/{tok}/{vid}/" )
            assert code == 200 and body == b"<html>page</html>" and headers[ "Content-Type" ].startswith( "text/html" )
            assert get( port, f"/{tok}/{vid}/frames/000000.bin" )[ 2 ] == b"\x01\x02"
            assert get( port, f"/{tok}/{vid}" )[ 0 ] == 301, "the directory: relative paths need its slash"
            assert get( port, f"/wrong/{vid}/" )[ 0 ] == 404
            assert get( port, f"/{tok}/0123456789abcdef/" )[ 0 ] == 404
            assert get( port, f"/{tok}/{vid}/../../secret.txt" )[ 0 ] == 404
            assert get( port, f"/{tok}/{vid}/%2e%2e/%2e%2e/secret.txt" )[ 0 ] == 404
            assert get( port, f"/{tok}/{vid}/frames" )[ 0 ] == 404, "a directory inside is no file"
        finally:
            httpd.shutdown()
            httpd.server_close()

if test( "a Static view: its copy here registered, nothing said; the run's page frames it" ):
    from errand.cli.views import Views
    from errand.tui.screen import outputs
    from errand.web import static as S
    import errand.web as W
    with scratch() as d:
        s = store( d )
        said = [ ]

        class Render:
            leaf = "/data/runs/leaf"

            def view( self, link ):
                said.append( link )

        was = W._wake
        W._wake = lambda: None
        try:
            v = Views( d, None, say = said.append )                           # the run is here: only said
            mark = { "op": "view", "path": "leaf/foam.sviz", "dir": True, "last": [ "manifest.json" ], "open": [ { "static": "index.html" } ] }
            v( mark, render = Render() )
            v( mark, render = Render() )
        finally:
            W._wake = was
        vid = S.view_id( "/data/runs/leaf", "foam.sviz" )
        assert said == [ ] and S.registered()[ vid ] == str( s ), "registered for the run's page, not said: the page shows it"

        class M:
            name, here = "box", False

            def now( self ):
                import time
                return time.time()

            def ask( self, q ):
                from errand.agents import look
                return look.tail( Path( q[ "path" ].replace( "/data/runs/leaf", str( d / "leaf" ) ) ), q.get( "offset" ), q.get( "size" ) )

        files = [ { "name": n, "size": 1, "mtime": 1.0, "path": f"/data/runs/leaf/{n}" }
                  for n in ( "foam.sviz/manifest.json", "foam.sviz/index.html" ) ]
        step = { "views": [ { "view": "/data/runs/leaf/foam.sviz", "open": [ { "static": "index.html" } ] } ] }
        rich, _ = outputs( M(), { "leaf": "/data/runs/leaf" }, step, files )
        assert len( rich ) == 1 and rich[ 0 ].data == ( "box", "/data/runs/leaf/foam.sviz", S.url( vid ) ), rich[ 0 ].data
        assert rich[ 0 ].detail.startswith( "1 frames  running" ), rich[ 0 ].detail
