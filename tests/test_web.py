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


if test( "the server: token then cookie, Host checked, the rows, a run's files and output, a whole file, stop" ):
    from errand.web.server import Web
    from errand import web as W
    with scratch() as base:
        p = subprocess.Popen( [ "sh", "-c", "sleep 60 & wait" ], start_new_session = True )
        try:
            ms = machines( base, p.pid )
            w = Web.start( base / "cache", port = 0, machines_of = lambda: ms, linger = 3 )
            assert w is not None and w.port
            assert Web.start( base / "cache", port = 0 ) is None, "a second server from the same cache"
            said = base / "cache" / "web.json"
            assert said.stat().st_mode & 0o077 == 0, oct( said.stat().st_mode )
            got = W.said()
            assert got[ "port" ] == w.port and got[ "url" ].endswith( f"?t={w.token}" ), got

            assert get( w.port, "/" )[ 0 ] == 403, "no token, yet served"
            assert get( w.port, "/?t=wrong" )[ 0 ] == 403
            code, headers, _ = get( w.port, f"/?t={w.token}" )
            assert code == 303 and headers[ "Location" ] == "/", ( code, headers )
            cookie = headers[ "Set-Cookie" ].split( ";" )[ 0 ]
            assert "HttpOnly" in headers[ "Set-Cookie" ] and "SameSite=Strict" in headers[ "Set-Cookie" ]
            assert get( w.port, "/", cookie, host = f"evil.example:{w.port}" )[ 0 ] == 403, "another Host served"
            code, headers, page = get( w.port, "/", cookie )
            assert code == 200 and b"<title>errand</title>" in page, code

            rows = json.loads( get( w.port, "/state?opened=box", cookie )[ 2 ] )[ "rows" ]
            got = [ ( r[ "depth" ], r[ "kind" ], r[ "mark" ], r[ "label" ].split()[ 0 ] ) for r in rows ]
            assert got == [ ( 0, "machine", "", "box" ), ( 1, "proc", "run", "sdot-ffi" ), ( 1, "proc", "wait", "otrec" ),
                            ( 1, "vm", "", "windows" ), ( 2, "proc", "run", "sdot-ffi" ), ( 1, "group", "", "history" ),
                            ( 2, "run", "ok", "sdot-ffi" ) ], got
            assert "waiting: slurm job 81234 pending" in rows[ 2 ][ "detail" ]
            found = json.loads( get( w.port, "/state?q=slurm", cookie )[ 2 ] )[ "rows" ]
            assert [ r[ "label" ].split()[ 0 ] for r in found ] == [ "box", "otrec" ], found
            assert [ r[ "kind" ] for r in json.loads( get( w.port, "/state?folded=box", cookie )[ 2 ] )[ "rows" ] ] == [ "machine" ]

            from urllib.parse import quote
            proc = rows[ 1 ][ "key" ]
            d = json.loads( get( w.port, "/detail?key=" + quote( proc ), cookie )[ 2 ] )
            assert ( "env", "lin" ) in [ tuple( f ) for f in d[ "facts" ] ], d[ "facts" ]
            assert [ f[ "name" ] for f in d[ "files" ] ] and d[ "source" ] == "output.txt", d
            assert d[ "out" ].rstrip().endswith( "step 99" ) and d[ "stop" ] is True, d
            guest = json.loads( get( w.port, "/detail?key=" + quote( rows[ 4 ][ "key" ] ), cookie )[ 2 ] )
            assert "guest" in guest[ "stop" ], guest
            code, _, whole = get( w.port, "/file?machine=box&path=" + quote( d[ "path" ] ), cookie )
            assert code == 200 and whole.decode().startswith( "step 0\n" ) and whole.decode().endswith( "step 99\n" )
            assert get( w.port, "/detail?key=nope", cookie )[ 0 ] == 404

            assert get( w.port, "/stop", method = "POST", body = { "key": proc } )[ 0 ] == 403, "stopped without a token"
            code, _, said_ = get( w.port, "/stop", cookie, method = "POST", body = { "key": proc } )
            assert code == 200 and "stopping" in json.loads( said_ )[ "said" ], said_
            assert gone( p.pid, 10 ) or p.wait( 10 ) is not None, "the process was not stopped"

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
            url = echo[ -1 ]
            rec = W.said()
            assert url == rec[ "url" ], ( url, rec )
            code, headers, _ = get( rec[ "port" ], f"/?t={rec[ 'token' ]}" )
            cookie = headers[ "Set-Cookie" ].split( ";" )[ 0 ]
            rows = json.loads( get( rec[ "port" ], "/state", cookie )[ 2 ] )[ "rows" ]
            assert rows and rows[ 0 ][ "kind" ] in ( "machine", "broken" ), rows
            echo.clear()
            assert W.main( echo = echo.append, browse = False ) == 0 and echo == [ url ], "a second call, another page"
        finally:
            rec = W.said()
            if rec:
                os.kill( rec[ "pid" ], signal.SIGTERM )
                assert gone( rec[ "pid" ], 20 ), "the agent did not go"
