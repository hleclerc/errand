"""`errand status` everywhere ( ADR 0008, step 3 ): what runs is read from the agents' records on each
machine, the ledger says which machines to ask, and nothing is started to find out."""
import contextlib
import io
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
    try:
        yield Path( d )
    finally:
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


SESSION = [ "python", "_boot.py", "-m", "errand.agents.ops", "session",
            json.dumps( { "root": "/srv/work/sdot", "env": "lin", "verb": "run",
                          "known": { "pattern": "tests/test_x.py::*", "label": "nightly" } } ) ]


if test( "a session says its project and what it runs; anything else, its records' project or its directory" ):
    from errand.agents.table import describe
    got = describe( { "argv": SESSION } )
    assert ( got[ "project" ], got[ "env" ], got[ "what" ] ) == ( "/srv/work/sdot", "lin", "run tests/test_x.py::* [nightly]" ), got
    assert describe( { "argv": [ "sleep", "9" ], "store": "/p/proj/errand-outputs/state/procs" } )[ "project" ] == "/p/proj"
    assert describe( { "argv": [ "sleep", "9" ], "cwd": "/p/other" } )[ "project" ] == "/p/other"
    assert describe( { "argv": [ "py", "-m", "errand.vm", "keep", "/x" ] } )[ "vm" ]


if test( "what an agent runs is read from its directory: running while it lives, orphaned once it is killed" ):
    from errand import agents
    from errand.agents import table as T
    os.environ[ "ERRAND_AGENT" ] = "direct"
    agents._open.clear()
    with scratch() as base:
        d = base / "agents" / "a"
        conn = agents.open( { "kind": "local", "dir": str( d ), "keep_alive": 5 } )
        agent = conn.ping()[ "pid" ]
        call = conn.open( { "op": "spawn", "argv": [ "sh", "-c", "exec sleep 60" ], "cwd": str( base ), "keep": True,
                            "store": str( base / "proj" / "errand-outputs" / "state" / "procs" ) } )
        call.reply( 10 )
        call.close()
        try:
            assert T.agent_dirs( [ base ] ) == [ d ]
            rows = T.procs_of( d, T.served( d ) )
            assert [ r[ "state" ] for r in rows ] == [ "running" ], rows
            assert rows[ 0 ][ "project" ] == str( base / "proj" ), rows
            pid = rows[ 0 ][ "pid" ]
            os.kill( agent, signal.SIGKILL )
            assert gone( agent )
            rows = T.procs_of( d, T.served( d ) )
            assert [ r[ "state" ] for r in rows ] == [ "orphaned" ], "an agent's death hid what it left running"
            os.killpg( pid, signal.SIGKILL )
            assert gone( pid )
            assert T.procs_of( d, T.served( d ) ) == [ ], "a process that ended is still said to run"
        finally:
            conn.close()
            agents._open.clear()


if test( "the ledger keeps the ssh machines reached, and forgets them after two weeks" ):
    from errand.agents import ledger
    with scratch() as base:
        os.environ[ "ERRAND_CACHE_DIR" ] = str( base )
        try:
            ledger.note( { "kind": "ssh", "host": "lmo", "options": [ ], "python": "python3", "keep_alive": 900 } )
            ledger.note( { "kind": "local", "dir": "/tmp/x" } )
            got = ledger.machines()
            assert [ m[ "name" ] for m in got ] == [ "lmo" ], got
            p = next( ( base / "ledger" ).glob( "*.json" ) )
            p.write_text( json.dumps( { **got[ 0 ], "last": time.time() - ledger.FORGET - 1 } ) )
            assert ledger.machines() == [ ] and not p.exists()
        finally:
            del os.environ[ "ERRAND_CACHE_DIR" ]


if test( "a neighbour's sweep keeps a directory whose records cannot say they ended ( an older errand's )" ):
    from errand.agents import endpoint
    with scratch() as base:
        for name in ( "me", "old" ):
            ( base / name / "proc" ).mkdir( parents = True )
            ( base / name / "lock" ).touch()
        rec = base / "old" / "proc" / "x"
        rec.mkdir()
        rec.joinpath( "meta.json" ).write_text( json.dumps( { "keep": False, "started": time.time() - 7200 } ) )
        past = time.time() - 7200
        for p in ( base / "old", base / "old" / "lock", base / "old" / "proc", rec, rec / "meta.json" ):
            os.utime( p, ( past, past ) )
        endpoint.sweep( base / "me" )
        assert ( base / "old" ).exists(), "work nobody can see the end of lost its only record"
        dead = subprocess.Popen( [ "true" ] )
        dead.wait()
        rec.joinpath( "meta.json" ).write_text( json.dumps( { "keep": False, "pid": dead.pid, "started": past } ) )
        for p in ( base / "old", rec / "meta.json" ):
            os.utime( p, ( past, past ) )
        endpoint.sweep( base / "me" )
        assert not ( base / "old" ).exists(), "a record whose process is known gone keeps its directory for ever"


if sys.platform.startswith( "linux" ) and test( "linux: a process errand started whose agent is gone, with no record, is found" ):
    from errand.agents import table as T
    with scratch() as base:
        p = subprocess.Popen( [ "sleep", "60" ], start_new_session = True,
                              env = { **os.environ, "ERRAND_AGENT_DIR": str( base / "gone-agent" ) } )
        try:
            time.sleep( 0.2 )
            rows = [ r for r in T.strays( set() ) if r[ "pgid" ] == p.pid ]
            assert [ r[ "state" ] for r in rows ] == [ "unowned" ], rows
            assert not [ r for r in T.strays( { p.pid } ) if r[ "pgid" ] == p.pid ], "a recorded group was said unowned"
        finally:
            p.kill()


if test( "status: this project in full, one line per other one, --all expands; the machines that could not say" ):
    from errand.cli import standing as S
    now = time.time()
    row = lambda project, state, i, **kw: { "agent": "a", "id": i, "pid": 1, "pgid": 4242, "started": now - 120, "keep": False,
                                            "state": state, "project": project, "what": f"run {i}", **kw }
    here = { "time": now, "procs": [ row( "/x/sdot", "running", "aaaaaaaa1" ) ], "vms": [ ], "guests": [ ] }
    lmo = { "time": now, "procs": [ row( "/h/sdot", "orphaned", "bbbbbbbb2" ), row( "/h/guitar", "unowned", "pgid-4242" ),
                                   row( "/h/guitar", "running", "cccccccc3" ) ],
            "vms": [ { "name": "80103674ede5f052-9a5c1a75", "state": "ready", "cpus": 2, "ram": "4G" } ],
            "guests": [ { "vm": "80103674ede5f052-9a5c1a75", "procs": [ row( "C:/errand/sdot", "running", "dddddddd4" ) ] } ] }
    S.tables = lambda: [ ( "mac", here, None ), ( "lmo", lmo, None ), ( "n22", None, "ssh: connect timed out" ) ]
    out = io.StringIO()
    with contextlib.redirect_stdout( out ):
        assert S.show_running( Path( "/x/sdot" ) ) == 5
    said = out.getvalue()
    for want in ( "aaaaaaaa", "bbbbbbbb", "orphaned", "lmo > windows 80103674", "dddddddd", "guitar:",
                  "1 running on lmo", "1 unowned on lmo", "lmo: windows vm 80103674 ready", "n22: cannot say", "connect timed out" ):
        assert want in said, f"{want!r} not in:\n{said}"
    assert "cccccccc" not in said, "another project was shown in full without --all"
    out = io.StringIO()
    with contextlib.redirect_stdout( out ):
        S.show_running( Path( "/x/sdot" ), everything = True )
    assert "cccccccc" in out.getvalue() and "kill -- -4242" in out.getvalue(), out.getvalue()
