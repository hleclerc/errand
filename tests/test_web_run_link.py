"""A run's page from the terminal ( ADR 0017 §5 ): `/r/<id>` by the run's directory, a cookie that lasts 30 days on a
token that outlives the agent, a code used once on any page, the link said under a run's head and `--open`."""
import contextlib
import http.client
import os
import shutil
import tempfile
import time
from pathlib import Path

from errand import test

from _record import from_histories
from_histories()


@contextlib.contextmanager
def scratch( ):
    d = tempfile.mkdtemp( dir = "/tmp" )
    was = { k: os.environ.get( k ) for k in ( "ERRAND_CACHE_DIR", "ERRAND_OPEN", "ERRAND_OUTPUT" ) }
    os.environ[ "ERRAND_CACHE_DIR" ] = str( Path( d ) / "cache" )
    try:
        yield Path( d )
    finally:
        for k, v in was.items():
            if v is None:
                os.environ.pop( k, None )
            else:
                os.environ[ k ] = v
        shutil.rmtree( d, ignore_errors = True )


def get( port, path, cookie = None ):
    c = http.client.HTTPConnection( "127.0.0.1", port, timeout = 30 )
    c.request( "GET", path, headers = { "Host": f"127.0.0.1:{port}", **( { "Cookie": cookie } if cookie else { } ) } )
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict( r.getheaders() ), data


def machine( leaf: Path ):
    from errand.tui.machines import Machine
    leaf.mkdir( parents = True )
    ( leaf / "result.yaml" ).write_text( "status: PASS\n" )
    now = time.time()
    m = Machine( "box" )
    m.table = { "time": now, "procs": [ ] }
    m.read_at = now
    m.history = { "runs": [ { "leaf": str( leaf ), "project": "/p", "what": "a.py::b", "started": now - 60, "status": "PASS",
                              "duration": 1.0 } ], "more": 0 }
    return [ m ]


if test( "/r/<id>: a run's page by its directory, behind the cookie; a code used once on it; the cookie lasts 30 days" ):
    from urllib.parse import quote, unquote
    from errand import web as W
    from errand.agents.seen import ident
    from errand.web.server import Web
    with scratch() as base:
        leaf = base / "runs" / "a.py" / "b" / "2026-11-19_10h00m00"
        ms = machine( leaf )
        w = Web.start( base / "cache", port = 0, machines_of = lambda: ms )
        try:
            token = w.token
            assert ( base / "cache" / "web-token" ).stat().st_mode & 0o077 == 0
            path = f"/r/{ident( str( leaf ) )}"
            assert W.run_link( str( leaf ) ) == f"http://127.0.0.1:{w.port}{path}"
            code, _, page = get( w.port, path )
            assert code == 401 and b'name="token"' in page, code
            code, headers, _ = get( w.port, f"{path}?o={W.once()}" )
            assert code == 303 and headers[ "Location" ] == path, ( code, headers )
            assert f"Max-Age={30 * 86400}" in headers[ "Set-Cookie" ], headers[ "Set-Cookie" ]
            cookie = headers[ "Set-Cookie" ].split( ";" )[ 0 ]
            code, headers, _ = get( w.port, path, cookie )
            assert code == 303 and headers[ "Location" ].startswith( "/job?key=" ), ( code, headers )
            assert str( leaf ) in unquote( headers[ "Location" ] )
            code, headers, page = get( w.port, headers[ "Location" ], cookie )
            assert code == 200 and f"Max-Age={30 * 86400}" in headers[ "Set-Cookie" ], "each page sets it again"
            code, _, page = get( w.port, "/r/0123456789abcdef", cookie )
            assert code == 200 and b"refresh" in page, "a run not said yet: a page that asks again"
            # a code with the cookie already there: the same page, no error
            code, headers, _ = get( w.port, f"/job?key={quote( 'x' )}&o=spent", cookie )
            assert code == 303 and headers[ "Location" ] == f"/job?key={quote( 'x' )}", headers
        finally:
            port = w.port
            w.stop()
        w = Web.start( base / "cache", port = port, machines_of = lambda: ms )     # ( the port of its user, as for real )
        try:
            assert w.token == token and w.port == port, "the token outlives the agent: the cookie still opens the page"
            assert get( w.port, path, cookie )[ 0 ] == 303
        finally:
            w.stop()

if test( "under a run's head: its page's address; `--open`: a tab for each of the first 4 runs, then the main page once" ):
    import io
    import webbrowser
    from errand.agents.seen import ident
    from errand.cli import render as Rd
    from errand.web.server import Web
    with scratch() as base:
        w = Web.start( base / "cache", port = 0, machines_of = lambda: [ ] )
        opened, was = [ ], webbrowser.open
        webbrowser.open = lambda url, *a, **k: opened.append( url )
        try:
            os.environ[ "ERRAND_OUTPUT" ] = "spaces"
            os.environ.pop( "ERRAND_OPEN", None )
            out = io.StringIO()
            Rd.Renderer( out = out, err = io.StringIO() ).head( "solve", "s.py:3", { "n": "3" }, leaf = "/over/there/leaf" )
            assert f"http://127.0.0.1:{w.port}/r/{ident( '/over/there/leaf' )}" in out.getvalue(), out.getvalue()
            assert not opened, "nothing opened without --open"
            os.environ[ "ERRAND_OPEN" ] = "1"
            Rd._OPENED[ 0 ] = 0
            for i in range( 6 ):
                Rd.Renderer( out = io.StringIO(), err = io.StringIO() ).head( f"c{i}", "s.py:3", leaf = f"/l/{i}" )
            assert len( opened ) == 5 and all( "/r/" in u for u in opened[ :4 ] ), opened
            assert opened[ 4 ].startswith( f"http://127.0.0.1:{w.port}/?o=" ), opened[ 4 ]
            assert all( "o=" in u for u in opened ), "a code used once: no cookie needed"
            # nobody serves the page: the link is said all the same, at its user's port, and the host agent woken aside
            from errand import web as W
            w.stop()
            woken, was_wake = [ ], W._wake
            W._wake = lambda: woken.append( 1 )
            try:
                out = io.StringIO()
                os.environ[ "ERRAND_OPEN" ] = "0"
                Rd.Renderer( out = out, err = io.StringIO() ).head( "solve", "s.py:3", leaf = "/y" )
                assert f"http://127.0.0.1:{W.port_of_user()}/r/{ident( '/y' )}" in out.getvalue() and woken, out.getvalue()
            finally:
                W._wake = was_wake
            w = Web.start( base / "cache", port = 0, machines_of = lambda: [ ] )
            os.environ[ "ERRAND_OUTPUT" ] = "plain"
            out = io.StringIO()
            os.environ[ "ERRAND_OPEN" ] = "0"
            Rd.Renderer( out = out, err = io.StringIO() ).head( "solve", "s.py:3", leaf = "/x" )
            assert "PAGE: http://" in out.getvalue(), out.getvalue()
        finally:
            webbrowser.open = was
            w.stop()

if test( "`errand run --open` and `-O` are options of run; the case's folder here is said once under its head" ):
    import io
    from errand.cli.parsing import build_parser, misplaced
    from errand.cli import render as Rd
    p = build_parser()
    for flag in ( "--open", "-O" ):
        known, _ = p.parse_known_args( [ flag ] )
        assert known.open and misplaced( p, known, "run" ) is None, flag
    assert misplaced( p, p.parse_known_args( [ "-O" ] )[ 0 ], "list" ), "an option of run only"
    with scratch() as base:
        os.environ[ "ERRAND_OUTPUT" ] = "spaces"
        os.environ[ "ERRAND_OPEN" ] = "0"
        out = io.StringIO()
        r = Rd.Renderer( out = out, err = io.StringIO() )
        r.local_root = str( base )
        r.mark( { "op": "head", "name": "solve", "site": "s.py:3", "leaf": "/data/x/errand-outputs/runs/a/leaf",
                  "rel": "errand-outputs/runs/a/leaf" } )
        assert out.getvalue().count( ( base / "errand-outputs/runs/a/leaf" ).as_uri() + "/" ) == 1, out.getvalue()

if test( "a page served by a host agent of older sources is handed over to the one of these, when the old one runs nothing" ):
    import json
    import signal
    from errand import bootstrap
    from errand import web as W
    with scratch() as base:
        def gone( pid, within = 20 ):
            end = time.monotonic() + within
            while time.monotonic() < end:
                try:
                    os.kill( pid, 0 )
                except OSError:
                    return True
                time.sleep( 0.1 )
            return False
        try:
            assert W.main( echo = lambda *a: None, browse = False ) == 0
            old = W.said()
            assert old[ "sources" ] == bootstrap.sources_key() and Path( old[ "agent" ] ).name == W.host_agent_dir().name, old
            said = base / "cache" / "web.json"
            rec = json.loads( said.read_text() )
            rec[ "sources" ] = "older"                               # as an agent started before errand changed
            said.write_text( json.dumps( rec ) )
            assert W._older( W.said() )
            new = W.ensure()
            assert new and new[ "sources" ] == bootstrap.sources_key() and new[ "pid" ] != old[ "pid" ], ( old, new )
            assert gone( old[ "pid" ] ), "the old agent went: it ran nothing"
        finally:
            rec = W.said()
            if rec:
                os.kill( rec[ "pid" ], signal.SIGTERM )
                gone( rec[ "pid" ] )
