"""`errand web`: the view of `errand tui` as a page, served by the host agent.

The server is driven over real HTTP, on a machine whose table is given ( the rows ) and on this
machine itself ( the files, the output, a real process stopped ); then a real host agent, in a cache
directory of its own, started by `errand web` and serving its page.
"""
import contextlib
import http.client
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from errand import test


@contextlib.contextmanager
def scratch( ):
    d = tempfile.mkdtemp( dir = "/tmp" )
    was = os.environ.get( "ERRAND_CACHE_DIR" )
    os.environ[ "ERRAND_CACHE_DIR" ] = str( Path( d ) / "cache" )
    try:
        yield Path( d )
    finally:
        if was is None:
            os.environ.pop( "ERRAND_CACHE_DIR", None )
        else:
            os.environ[ "ERRAND_CACHE_DIR" ] = was
        shutil.rmtree( d, ignore_errors = True )


def gone( pid, within = 10 ):
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill( pid, 0 )
        except OSError:
            return True
        time.sleep( 0.05 )
    return False


def get( port, path, cookie = None, host = None, method = "GET", body = None ):
    c = http.client.HTTPConnection( "127.0.0.1", port, timeout = 30 )
    headers = { "Host": host or f"127.0.0.1:{port}" }
    if cookie:
        headers[ "Cookie" ] = cookie
    if body is not None:
        body = json.dumps( body ).encode()
        headers[ "Content-Type" ] = "application/json"
    c.request( method, path, body = body, headers = headers )
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict( r.getheaders() ), data


def machines( base: Path, pgid: int ):
    """This machine, its table given: a process with a leaf, a VM, a guest's process; a run done."""
    from errand.tui.machines import Machine
    from errand.agents.procs import started
    leaf = base / "leaf"
    leaf.mkdir()
    ( leaf / "output.txt" ).write_text( "".join( f"step {i}\n" for i in range( 100 ) ) )
    ( leaf / "result.yaml" ).write_text( "status: PASS\n" )
    now = time.time()
    m = Machine( "box" )
    m.table = { "time": now, "procs": [
        { "id": "a1", "project": "/home/h/sdot-ffi", "what": "run test_x.py::solve", "env": "lin", "started": now - 700,
          "state": "running", "pgid": pgid, "since": started( pgid ), "leaf": str( leaf ) },
        { "id": "b2", "project": "/home/h/otrec", "what": "run grid", "started": now - 90, "state": "running",
          "waiting": { "what": "slurm job 81234 pending", "since": now - 120 } } ],
        "vms": [ { "name": "3fa2c1aa77", "state": "ready", "cpus": 8, "ram": "16G", "keeper": 5 } ],
        "guests": [ { "vm": "3fa2c1aa77", "procs": [ { "id": "g", "project": "C:/w/sdot-ffi", "what": "run ping",
                                                        "started": now - 30, "state": "running" } ] } ] }
    m.read_at = now
    m.history = { "runs": [ { "leaf": str( leaf ), "project": "/home/h/sdot-ffi", "what": "a.py::b", "started": now - 3600,
                              "status": "PASS", "duration": 12.3 } ], "more": 0 }
    return [ m ]


def post( port, path, cookie = None, body = None, origin = None, form = None ):
    c = http.client.HTTPConnection( "127.0.0.1", port, timeout = 30 )
    headers = { "Host": f"127.0.0.1:{port}" }
    if cookie:
        headers[ "Cookie" ] = cookie
    if origin:
        headers[ "Origin" ] = origin
    if form is not None:
        from urllib.parse import urlencode
        data = urlencode( form ).encode()
        headers[ "Content-Type" ] = "application/x-www-form-urlencoded"
    else:
        data = json.dumps( body or { } ).encode()
        headers[ "Content-Type" ] = "application/json"
    c.request( "POST", path, body = data, headers = headers )
    r = c.getresponse()
    out = r.read()
    c.close()
    return r.status, dict( r.getheaders() ), out


if test( "the server: a code used once or the token typed, then a cookie; the rows of a tab, a run's detail, its files, kill" ):
    from errand.web.server import Web
    from errand import web as W
    with scratch() as base:
        p = subprocess.Popen( [ "sh", "-c", "sleep 60 & wait" ], start_new_session = True )
        try:
            ms = machines( base, p.pid )
            ( base / "leaf" / "plot.png" ).write_bytes( b"\x89PNG\r\n\x1a\n" + bytes( range( 256 ) ) )
            w = Web.start( base / "cache", port = 0, machines_of = lambda: ms, linger = 3 )
            assert w is not None and w.port and len( w.token ) >= 64, "a long token"
            assert Web.start( base / "cache", port = 0 ) is None, "a second server from the same cache"
            said = base / "cache" / "web.json"
            assert said.stat().st_mode & 0o077 == 0, oct( said.stat().st_mode )
            got = W.said()
            assert got[ "port" ] == w.port and w.token not in got[ "url" ], "no token in a URL"

            # without the cookie: a form for the token; a code opens it once
            code, _, page = get( w.port, "/" )
            assert code == 401 and b'name="token"' in page and b"<script" not in page, code
            assert get( w.port, "/state" )[ 0 ] == 403, "rows without a token"
            assert get( w.port, f"/?t={w.token}" )[ 0 ] == 401, "the token in a URL is no way in"
            once = W.once()
            code, headers, _ = get( w.port, f"/?o={once}" )
            assert code == 303 and headers[ "Location" ] == "/", ( code, headers )
            cookie = headers[ "Set-Cookie" ].split( ";" )[ 0 ]
            assert "HttpOnly" in headers[ "Set-Cookie" ] and "SameSite=Strict" in headers[ "Set-Cookie" ]
            assert get( w.port, f"/?o={once}" )[ 0 ] == 403, "a code used twice"
            assert post( w.port, "/login", form = { "token": "wrong" } )[ 0 ] == 403
            code, headers, _ = post( w.port, "/login", form = { "token": w.token } )
            assert code == 303 and headers[ "Set-Cookie" ].split( ";" )[ 0 ] == cookie, ( code, headers )
            assert get( w.port, "/", cookie, host = f"evil.example:{w.port}" )[ 0 ] == 403, "another Host served"
            code, headers, page = get( w.port, "/", cookie )
            assert code == 200 and b"<title>errand</title>" in page and "frame-ancestors 'none'" in headers[ "Content-Security-Policy" ]

            st = lambda q: json.loads( get( w.port, "/state?" + q, cookie )[ 2 ] )
            got = [ ( r[ "depth" ], r[ "kind" ], r[ "label" ].split()[ 0 ] ) for r in st( "tab=machines" )[ "rows" ] ]
            assert got == [ ( 0, "machine", "box" ), ( 1, "vm", "windows" ), ( 2, "proc", "sdot-ffi" ) ], got
            whole = st( "tab=runs" )
            rows = whole[ "rows" ]
            assert whole[ "counts" ] == { "running": 1, "waiting": 1, "machines": 1, "off": 0 }, whole[ "counts" ]
            got = [ ( r[ "kind" ], r[ "mark" ] ) for r in rows ]
            assert got == [ ( "day", "" ), ( "proc", "run" ), ( "proc", "run" ), ( "day", "" ), ( "proc", "wait" ),
                            ( "day", "" ), ( "run", "ok" ) ], [ r[ "label" ] for r in rows ]
            assert "waiting: slurm job 81234 pending" in rows[ 4 ][ "detail" ]
            found = st( "tab=runs&q=slurm" )[ "rows" ]
            assert [ r[ "kind" ] for r in found ] == [ "day", "proc" ] and "grid" in found[ 1 ][ "label" ], found
            day = rows[ 0 ][ "fold" ]
            assert day == "day:running", rows[ 0 ]
            assert [ r[ "kind" ] for r in st( "tab=runs&folded=" + day )[ "rows" ] ][ : 2 ] == [ "day", "day" ], "a day folded"
            assert [ r[ "kind" ] for r in st( "tab=machines&folded=box" )[ "rows" ] ] == [ "machine" ], "a machine folded"
            assert st( "tab=machines" )[ "rows" ][ 0 ][ "fold" ] == "box"

            from urllib.parse import quote
            proc = next( r[ "key" ] for r in rows if r[ "kind" ] == "proc" and "test_x" in r[ "label" ] )
            d = json.loads( get( w.port, "/detail?key=" + quote( proc ), cookie )[ 2 ] )
            facts = { r[ "k" ]: r[ "v" ] for r in d[ "rows" ] if "k" in r }
            assert facts.get( "env" ) == "lin", facts
            outs = [ ( r[ "label" ], r.get( "path" ) ) for r in d[ "rows" ] if r[ "kind" ] == "output" ]
            names = [ n for n, _ in outs ]
            assert names.index( "plot.png" ) < names.index( "console" ), outs      # ( what is made to be looked at first )
            lines = [ r[ "label" ] for r in d[ "rows" ] if r[ "kind" ] == "out" ]
            assert lines[ -1 ].endswith( "step 99" ) and d[ "can" ].get( "kill" ) and d[ "console" ], d
            png = next( pth for n, pth in outs if n == "plot.png" )
            on = lambda what, path: f"/{what}?key={quote( proc )}&path={quote( path )}"
            assert json.loads( get( w.port, on( "peek", png ), cookie )[ 2 ] )[ "kind" ] == "image"
            pk = json.loads( get( w.port, on( "peek", d[ "console" ] ), cookie )[ 2 ] )
            assert pk[ "kind" ] == "text" and pk[ "text" ].startswith( "step 0\n" ), pk
            code, headers, body = get( w.port, on( "file", png ), cookie )
            assert code == 200 and body == ( base / "leaf" / "plot.png" ).read_bytes(), "an image, as its bytes"
            assert headers[ "Content-Type" ] == "image/png" and headers[ "Content-Security-Policy" ].startswith( "sandbox" ), headers
            code, _, whole = get( w.port, on( "file", d[ "console" ] ), cookie )
            assert code == 200 and whole.decode().startswith( "step 0\n" ) and whole.decode().endswith( "step 99\n" )
            # a path is reached through its row: its leaf and what is under it, nothing else
            listed = json.loads( get( w.port, on( "ls", str( base / "leaf" ) ), cookie )[ 2 ] )
            assert { e[ "name" ] for e in listed[ "entries" ] } >= { "output.txt", "plot.png" }, listed
            for elsewhere in ( "/etc/passwd", str( base / "leaf" / ".." / ".." ), str( base ) ):
                assert get( w.port, on( "file", elsewhere ), cookie )[ 0 ] == 403, elsewhere
                assert get( w.port, on( "ls", elsewhere ), cookie )[ 0 ] == 403, elsewhere
            assert get( w.port, "/detail?key=nope", cookie )[ 0 ] == 404
            ( base / "leaf" / "conf.yaml" ).write_text( "a: 1\n" )
            code, headers, _ = get( w.port, on( "file", str( base / "leaf" / "conf.yaml" ) ), cookie )
            assert code == 200 and headers[ "Content-Type" ].startswith( "text/plain" ), "a yaml downloaded, not shown"
            code, _, page = get( w.port, "/job?key=" + quote( proc ), cookie )
            assert code == 200 and b"const JOB" in page and get( w.port, "/job?key=x" )[ 0 ] == 401, "a run's own page"
            big = json.loads( get( w.port, on( "peek", d[ "console" ] ) + "&size=100", cookie )[ 2 ] )
            assert big[ "more" ] > 0 and len( big[ "text" ] ) <= 100, "the size asked"

            guest = next( r[ "key" ] for r in rows if r[ "kind" ] == "proc" and "ping" in r[ "label" ] )
            code, _, out = post( w.port, "/act", cookie, { "op": "kill", "key": guest } )
            assert code == 400 and "guest" in json.loads( out )[ "error" ], out
            assert post( w.port, "/act", body = { "op": "kill", "key": proc } )[ 0 ] == 403, "killed without a token"
            assert post( w.port, "/act", cookie, { "op": "kill", "key": proc, "sure": True },
                         origin = "http://evil.example" )[ 0 ] == 403, "killed from another page"
            code, _, out = post( w.port, "/act", cookie, { "op": "kill", "key": proc } )
            asked = json.loads( out )
            assert code == 200 and asked[ "confirm" ][ "verb" ] == "kill" and p.poll() is None, "asked first"
            code, _, out = post( w.port, "/act", cookie, { "op": "kill", "key": proc, "sure": True },
                                 origin = f"http://127.0.0.1:{w.port}" )
            assert code == 200 and "killing" in json.loads( out )[ "said" ], out
            assert gone( p.pid, 10 ) or p.wait( 10 ) is not None, "the process was not stopped"
            machine = st( "tab=machines" )[ "rows" ][ 0 ][ "key" ]
            asked = json.loads( post( w.port, "/act", cookie, { "op": "rename", "key": machine } )[ 2 ] )
            assert asked[ "prompt" ][ "text" ] == "box", asked

            get( w.port, "/", cookie )
            assert w.used( 5 ), "a request is not use"
            deadline = time.monotonic() + 15
            while w._list is not None and time.monotonic() < deadline:
                time.sleep( 0.2 )
            assert w._list is None and ms[ 0 ].stopped, "the machines were kept after the page went"
            w.stop()
            assert W.said() is None, "a server gone is still said"
            assert Web.start( base / "cache", port = 0, machines_of = lambda: ms ) is not None, "the lock was kept"
        finally:
            if p.poll() is None:
                os.killpg( p.pid, signal.SIGKILL )


if test( "the agent: only a host agent serves, and `errand web` starts it then gives its page" ):
    from errand import web as W
    with scratch() as base:
        other = base / "cache" / "agents" / "env-x"
        assert not W.serves( other ) and W.serves( W.host_agent_dir() )
        echo = [ ]
        try:
            assert W.main( echo = echo.append, browse = False ) == 0, echo
            url = echo[ -1 ].split()[ 0 ]
            rec = W.said()
            assert url.startswith( rec[ "url" ] + "?o=" ) and rec[ "token" ] not in url, ( url, rec )
            code, headers, _ = get( rec[ "port" ], url.split( str( rec[ "port" ] ), 1 )[ 1 ] )
            assert code == 303, code
            cookie = headers[ "Set-Cookie" ].split( ";" )[ 0 ]
            rows = json.loads( get( rec[ "port" ], "/state?tab=machines", cookie )[ 2 ] )[ "rows" ]
            assert rows and rows[ 0 ][ "kind" ] in ( "machine", "broken" ), rows
            echo.clear()
            assert W.main( echo = echo.append, browse = False ) == 0 and echo[ 0 ].split()[ 0 ] != url, "a code, once"
            echo.clear()
            assert W.main( [ "token" ], echo = echo.append, browse = False ) == 0 and echo == [ rec[ "token" ] ], echo
        finally:
            rec = W.said()
            if rec:
                os.kill( rec[ "pid" ], signal.SIGTERM )
                assert gone( rec[ "pid" ], 20 ), "the agent did not go"


if test( "e: an output of the row chosen opens in an editor of this machine, nothing else does; dev reads the page again" ):
    from errand.web.server import Web
    from urllib.parse import quote
    with scratch() as base:
        ms = machines( base, os.getpid() )
        record = base / "edited.txt"
        editor = base / "editor.sh"
        editor.write_text( f"#!/bin/sh\necho \"$@\" >> {record}\n" )
        editor.chmod( 0o755 )
        kept = os.environ.get( "ERRAND_WEB_EDITOR" )
        os.environ[ "ERRAND_WEB_EDITOR" ] = f"{editor} --wait"
        w = Web.start( base / "cache", port = 0, machines_of = lambda: ms, linger = 30, reload_page = True )
        try:
            from errand import web as W
            cookie = get( w.port, f"/?o={W.once()}" )[ 1 ][ "Set-Cookie" ].split( ";" )[ 0 ]
            rows = json.loads( get( w.port, "/state?tab=runs", cookie )[ 2 ] )[ "rows" ]
            proc = next( r[ "key" ] for r in rows if r[ "kind" ] == "proc" and "test_x" in r[ "label" ] )
            code, _, out = post( w.port, "/act", cookie, { "op": "edit", "key": proc } )
            assert code == 200 and "output.txt opened" in json.loads( out )[ "said" ], out
            deadline = time.monotonic() + 10
            while not record.exists() and time.monotonic() < deadline:
                time.sleep( 0.05 )
            assert record.read_text().split() == [ "--wait", str( base / "leaf" / "output.txt" ) ], record.read_text()
            code, _, out = post( w.port, "/act", cookie, { "op": "edit", "key": proc, "path": "/etc/passwd" } )
            assert code == 400 and "not a path" in json.loads( out )[ "error" ], "any file, opened"

            from errand.web import page
            kept_page = page.PAGE
            src = Path( page.__file__ )
            text = src.read_text()
            try:
                assert text.count( "const EVERY = 2000;" ) == 1
                src.write_text( text.replace( "const EVERY = 2000;", "const EVERY = 2001;" ) )
                assert b"const EVERY = 2001;" in get( w.port, "/", cookie )[ 2 ], "the page not read again"
            finally:
                src.write_text( text )
                import importlib
                importlib.reload( page )
                assert page.PAGE == kept_page
        finally:
            w.stop()
            if kept is None:
                os.environ.pop( "ERRAND_WEB_EDITOR", None )
            else:
                os.environ[ "ERRAND_WEB_EDITOR" ] = kept


if test( "a run's entry file: from its record, else from its directory, else the path its command runs" ):
    from errand.web.server import _entry_file
    leaf = "/data/p/errand-outputs/runs/otrec/experiments/exp_2d_real.py/foam/2026-11-19_04h27m04-lmo"
    assert _entry_file( { "project": "/home/p", "leaf": leaf, "file": "otrec/experiments/exp_2d_real.py" } ) \
        == "/home/p/otrec/experiments/exp_2d_real.py"
    assert _entry_file( { "project": "/home/p", "leaf": leaf } ) == "/home/p/otrec/experiments/exp_2d_real.py"
    assert _entry_file( { "project": "/x", "what": "run /tmp/q/bc7.sh", "leaf": "/x/errand-outputs/runs/bc7.sh/2026" } ) == "/tmp/q/bc7.sh"
    assert _entry_file( { "project": "/x", "what": "a.py::b" } ) is None
