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


@contextlib.contextmanager
def patched( owner, **values ):
    """`owner.name = value` for each, for the block only."""
    kept = { k: getattr( owner, k ) for k in values }
    for k, v in values.items():
        setattr( owner, k, v )
    try:
        yield
    finally:
        for k, v in kept.items():
            setattr( owner, k, v )


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
    assert not describe( { "argv": [ "py", "-m", "errand.vm", "use", "{}" ] } )[ "vm" ], "a command's hold is under its project"


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
    tables = lambda: [ ( "mac", here, None ), ( "lmo", lmo, None ), ( "n22", None, "ssh: connect timed out" ) ]
    out = io.StringIO()
    with patched( S, tables = tables ), contextlib.redirect_stdout( out ):
        assert S.show_running( Path( "/x/sdot" ) ) == 5
    said = out.getvalue()
    for want in ( "aaaaaaaa", "bbbbbbbb", "orphaned", "lmo > windows 80103674", "dddddddd", "guitar:",
                  "1 running on lmo", "1 unowned on lmo", "lmo: windows vm 80103674 ready", "n22: cannot say", "connect timed out" ):
        assert want in said, f"{want!r} not in:\n{said}"
    assert "cccccccc" not in said, "another project was shown in full without --all"
    out = io.StringIO()
    with patched( S, tables = tables ), contextlib.redirect_stdout( out ):
        S.show_running( Path( "/x/sdot" ), everything = True )
    assert "cccccccc" in out.getvalue() and "kill -- -4242" in out.getvalue(), out.getvalue()


if test( "a wait is said in the waiter's record, keeps its start across states, and goes once arrived ( ADR 0009 )" ):
    from errand.agents import arrival
    with scratch() as d:
        os.environ[ arrival.ENV ] = str( d )
        try:
            arrival.waiting( "windows vm abc queued", key = "vm" )
            first = arrival.read( d )
            time.sleep( 0.05 )
            arrival.waiting( "windows vm abc booting", key = "vm" )
            got = arrival.read( d )
            assert got[ "what" ] == "windows vm abc booting" and got[ "since" ] == first[ "since" ], ( first, got )
            arrival.arrived( key = "vm" )
            assert arrival.read( d ) is None
        finally:
            del os.environ[ arrival.ENV ]
        arrival.waiting( "nobody to tell" )               # no agent: nothing written, nothing raised
        # the shell's version, for the scripts an agent runs
        line = arrival.SHELL_WAITING + 'waiting "slurm job 7 pending" 7; cat "$ERRAND_PROC_DIR/waiting"; arrived; ls "$ERRAND_PROC_DIR"'
        out = subprocess.run( [ "sh", "-c", line ], capture_output = True, text = True,
                              env = { **os.environ, arrival.ENV: str( d ) } ).stdout
        said = json.loads( out.splitlines()[ 0 ] )
        assert said[ "what" ] == "slurm job 7 pending" and said[ "job" ] == "7" and said[ "since" ] > 0, out
        assert "waiting" not in out.splitlines()[ 1 : ], "arrived left the wait behind"


if test( "what a process of an agent waits for is read by table, and shown by status" ):
    from errand import agents
    from errand.agents import arrival, table as T
    from errand.cli import standing as S
    os.environ[ "ERRAND_AGENT" ] = "direct"
    agents._open.clear()
    with scratch() as base:
        d = base / "agents" / "w"
        conn = agents.open( { "kind": "local", "dir": str( d ), "keep_alive": 5 } )
        pid = agents.start( conn, [ "sh", "-c", arrival.SHELL_WAITING + 'waiting "slurm job 81234 pending" 81234; exec sleep 60' ] )
        try:
            deadline = time.monotonic() + 10
            rows = [ ]
            while time.monotonic() < deadline and not any( r.get( "waiting" ) for r in rows ):
                time.sleep( 0.1 )
                rows = T.procs_of( d, T.served( d ) )
            assert rows and rows[ 0 ][ "waiting" ][ "job" ] == "81234", rows
            now = time.time() + 130
            out = io.StringIO()
            with contextlib.redirect_stdout( out ):
                S.show_running( Path( "/x/proj" ), got = [ ( "here", { "time": now, "procs": [ { **rows[ 0 ], "project": "/x/proj" } ],
                                                                        "vms": [ ], "guests": [ ] }, None ) ] )
            assert "waiting: slurm job 81234 pending" in out.getvalue() and "2 min" in out.getvalue(), out.getvalue()
        finally:
            agents.client.stop( agents.attach( conn, pid ) )
            conn.close()
            agents._open.clear()


if test( "a login node's hold on an allocation, started through rsh with no directory, says its project and env" ):
    import shlex
    from types import SimpleNamespace
    import errand
    from errand.agents.table import describe
    from errand.cli.alive import Allocation
    env = errand.Env( [ errand.Ssh( host = "cluster" ), errand.Slurm( keep_alive = "30m" ) ] )
    env.name = "jz"
    where = SimpleNamespace( root = Path( "/proj" ), ssh = errand.Ssh( host = "cluster", root = "/scratch/sdot" ),
                             there = Path( "/scratch/sdot" ), cache = "/home/me/.cache/errand", boot = "/home/me/_boot.py" )
    a = Allocation( env, { }, where )
    # what `rsh` hands the login node's agent: sh -c "sh -c '<script>'"
    got = describe( { "argv": [ "sh", "-c", f"sh -c {shlex.quote( a.script() )}" ] } )
    assert ( got[ "project" ], got[ "env" ], got[ "kind" ] ) == ( "/scratch/sdot", "jz", "allocation" ), got
    assert got[ "what" ] == f"slurm allocation {a.name[ : 8 ]}", got
    bridge = describe( { "argv": [ "sh", "-c", "exec \"${SHELL:-/bin/sh}\" -ic 'cd /scratch/sdot && micromamba run -n x "
                                               "python /c/_boot.py -m errand.agents connect /c/agents/env-0123456789 900'" ] } )
    assert ( bridge[ "project" ], bridge[ "kind" ], bridge[ "what" ] ) == ( "/scratch/sdot", "agent", "environment agent env-0123456789" ), bridge


if test( "an allocation's agents are read on its node, not from the login node; environment agents are folded" ):
    from errand.agents import table as T
    from errand.cli import standing as S
    with scratch() as base:
        job = base / "alloc" / "abc" / "81234"
        for d in ( base / "agents" / "lmo", job, job / "env-0123456789" ):
            ( d / "proc" ).mkdir( parents = True )
            ( d / "lock" ).touch()
        only = T.scan( guests = False, only = job )
        assert only[ "vms" ] == [ ] and only[ "nodes" ] == [ ]
        asked = [ ]
        # Put back whatever happens: the suite runs in one process, and every test after this one would
        # find errand's cache in this scratch directory ( the screen's, the web's, the vms' tests did ).
        with patched( T, allocations = lambda cache: [ ( job, "81234", "r1i0n3" ) ],
                      node_table = lambda d, j, n: asked.append( ( d, j, n ) ) or { "procs": [ ] },
                      roots = lambda: [ base ] ), patched( T.bootstrap, local_cache = lambda: base ):
            got = T.scan( guests = False )
        assert asked == [ ( job, "81234", "r1i0n3" ) ] and got[ "nodes" ][ 0 ][ "node" ] == "r1i0n3", got
    now = time.time()
    row = lambda i, **kw: { "agent": "a", "id": i, "pid": 1, "started": now - 60, "keep": False, "state": "running",
                            "project": "/scratch/sdot", "what": f"run {i}", **kw }
    table = { "time": now, "procs": [ row( "eeeeeeee5", kind = "agent", what = "environment agent env-0123456789" ) ],
              "vms": [ ], "guests": [ ],
              "nodes": [ { "node": "r1i0n3", "job": "81234", "procs": [ row( "ffffffff6" ) ] },
                         { "node": "r1i0n4", "job": "81235", "error": "srun: error: job 81235 has ended" } ] }
    out = io.StringIO()
    with contextlib.redirect_stdout( out ):
        assert S.show_running( Path( "/x/sdot" ), got = [ ( "here", { "time": now, "procs": [ ], "vms": [ ], "guests": [ ] }, None ),
                                                           ( "jz", table, None ) ] ) == 1
    said = out.getvalue()
    for want in ( "jz > r1i0n3", "ffffffff", "1 environment agent kept warm", "jz > r1i0n4 ( slurm job 81235 ): cannot say" ):
        assert want in said, f"{want!r} not in:\n{said}"
    assert "eeeeeeee" not in said and "?" not in said.replace( "( --all", "" ), said


if test( "a run says its steps in its journal: merged at 10 Hz, never the last lost, nothing without a run ( ADR 0010 )" ):
    from errand import steps
    with scratch() as d:
        journal = d / steps.FILE
        kept = os.environ.get( steps.ENV )                 # this test's own run has one
        os.environ[ steps.ENV ] = str( journal )
        try:
            for i in range( 1, 101 ):                       # a tight loop: a few lines, not a hundred
                steps.step( f"iteration {i}", done = i / 100, residual = 10.0 ** -i )
            steps.flush()
            events = steps.read( journal )
            assert 1 <= len( events ) < 10, events
            assert events[ -1 ][ "text" ] == "iteration 100" and events[ -1 ][ "residual" ] == 1e-100, events[ -1 ]
            time.sleep( steps.RATE )
            steps.step( energy = 2 )                        # a point, the text stays
            steps.view( "plot.html", title = "convergence", content = "<p>1</p>" )
            assert ( d / "plot.html" ).read_text() == "<p>1</p>" and not list( d.glob( ".*.tmp" ) )
            s = steps.summary( journal )
            assert s[ "text" ] == "iteration 100" and s[ "done" ] == 1.0 and s[ "curves" ][ "energy" ] == [ 2.0 ], s
            assert s[ "views" ] == [ { "view": "plot.html", "title": "convergence" } ], s
            line = steps.line( s )
            assert "iteration 100" in line and "100 %" in line and "energy 2" in line, line
        finally:
            del os.environ[ steps.ENV ]
        steps.step( "nobody to tell", done = 0.5 )          # no run: nothing written, nothing raised
        if kept:
            os.environ[ steps.ENV ] = kept
        try:
            steps.step( residual = "small" )
            assert False, "a curve took a word"
        except ValueError:
            pass
        # the end of a fraction is estimated from how fast it went
        s = steps.summarize( [ { "t": 0, "done": 0.1 }, { "t": 10, "done": 0.2, "text": "x" } ] )
        assert abs( s[ "eta" ] - 80 ) < 1e-9 and s[ "first" ] == 0, s
        # a long journal is read by its two ends: the views said early, the state said late
        long = d / "long.jsonl"
        with open( long, "w" ) as f:
            f.write( json.dumps( { "t": 0, "view": "early.html" } ) + "\n" )
            for i in range( 20000 ):
                f.write( json.dumps( { "t": i, "text": f"it {i}", "r": i } ) + "\n" )
        s = steps.summary( long )
        assert s[ "views" ][ 0 ][ "view" ] == "early.html" and s[ "text" ] == "it 19999" and len( s[ "curves" ][ "r" ] ) == steps.POINTS, s
        # the shell's version, for scripts
        out = subprocess.run( [ "sh", "-c", 'eval "$ERRAND_STEPS_SH"; step "iteration 4, \\"ok\\"" done=0.5 residual=3e-7; '
                                            'step residual=1e-8; view plot.html' ],
                              capture_output = True, text = True,
                              env = { **os.environ, steps.ENV: str( d / "sh.jsonl" ), steps.SH_ENV: steps.SHELL_STEPS } )
        assert out.returncode == 0, out.stderr
        s = steps.summary( d / "sh.jsonl" )
        assert s[ "text" ] == 'iteration 4, "ok"' and s[ "done" ] == 0.5 and s[ "curves" ][ "residual" ] == [ 3e-7, 1e-8 ], s
        assert s[ "views" ] == [ { "view": "plot.html", "title": None } ], s


if test( "the bar, the sparkline, the line at the bottom of a terminal" ):
    from errand import steps
    from errand.cli.footer import Followed, Footer
    assert steps.bar( 0.5, 4 ) == "▕██  ▏" and steps.bar( 1, 4 ) == "▕████▏" and steps.bar( 0, 4 ) == "▕    ▏"
    assert steps.spark( [ 1, 2, 3 ] )[ 0 ] == "▁" and steps.spark( [ 1, 2, 3 ] )[ -1 ] == "█"
    assert steps.spark( [ 1, 1e-3, 1e-6 ] ) == "█▅▁", steps.spark( [ 1, 1e-3, 1e-6 ] )      # log scale
    out = io.StringIO()
    footer = Footer( out )
    footer.show( "iteration 3" )
    footer.clear()
    said = out.getvalue()
    assert "iteration 3" in said and "r" in said and said.endswith( "\033[r\0338" ), repr( said )
    with scratch() as d:
        journal = d / steps.FILE
        said = [ ]
        with Followed( journal, said.append ) as f:
            journal.write_text( json.dumps( { "t": 1, "text": "iteration 1" } ) + "\n" )
            f.look()
        assert said == [ "iteration 1", None ], said


if test( "what a process of an agent is at is read by table, and shown by status ( ADR 0010 )" ):
    from errand import agents, steps
    from errand.agents import table as T
    from errand.cli import standing as S
    os.environ[ "ERRAND_AGENT" ] = "direct"
    agents._open.clear()
    with scratch() as base:
        d = base / "agents" / "w"
        leaf = base / "leaf"
        leaf.mkdir()
        ( leaf / steps.FILE ).write_text( json.dumps( { "t": time.time(), "text": "iteration 41", "done": 0.41 } ) + "\n" )
        conn = agents.open( { "kind": "local", "dir": str( d ), "keep_alive": 5 } )
        pid = agents.start( conn, [ "sh", "-c", f'echo "{leaf}" > "$ERRAND_PROC_DIR/leaf"; exec sleep 60' ] )
        try:
            deadline = time.monotonic() + 10
            rows = [ ]
            while time.monotonic() < deadline and not any( r.get( "step" ) for r in rows ):
                time.sleep( 0.1 )
                rows = T.procs_of( d, T.served( d ) )
            assert rows and rows[ 0 ][ "step" ][ "text" ] == "iteration 41", rows
            out = io.StringIO()
            with contextlib.redirect_stdout( out ):
                S.show_running( Path( "/x/proj" ), got = [ ( "here", { "time": time.time(), "procs": [ { **rows[ 0 ], "project": "/x/proj" } ],
                                                                        "vms": [ ], "guests": [ ] }, None ) ] )
            assert "running" in out.getvalue() and "iteration 41" in out.getvalue() and "41 %" in out.getvalue(), out.getvalue()
        finally:
            agents.client.stop( agents.attach( conn, pid ) )
            conn.close()
            agents._open.clear()


if test( "a machine forgotten is not asked any more, until work is sent there again: errand machines forget" ):
    from errand.agents import ledger
    from _infra import run_errand, write_project
    with scratch() as base:
        kept = os.environ.get( "ERRAND_CACHE_DIR" )
        os.environ[ "ERRAND_CACHE_DIR" ] = str( base )
        try:
            for host in ( "lmo", "h" ):
                ledger.note( { "kind": "ssh", "host": host, "options": [ ], "python": "python3", "keep_alive": 900 } )
            assert sorted( m[ "name" ] for m in ledger.machines() ) == [ "h", "lmo" ]
            assert ledger.forget( "nowhere" ) == [ ]
            project = write_project( base / "proj", "", { } )
            code, out = run_errand( project, "machines" )
            assert code == 0 and "h " in out and "lmo" in out, out
            code, out = run_errand( project, "machines", "forget", "h", "nowhere" )
            assert code == 1 and "h: forgotten" in out and "nowhere: no such machine" in out, out
            assert [ m[ "name" ] for m in ledger.machines() ] == [ "lmo" ]
            ledger.note( { "kind": "ssh", "host": "h", "options": [ ], "python": "python3", "keep_alive": 900 } )
            assert "h" in [ m[ "name" ] for m in ledger.machines() ], "work sent there again: asked again"
        finally:
            if kept is None:
                os.environ.pop( "ERRAND_CACHE_DIR", None )
            else:
                os.environ[ "ERRAND_CACHE_DIR" ] = kept


if test( "a watcher subscribed is told what changes as it changes: a process that starts, that ends; no asking again" ):
    from errand import agents
    from errand.agents import frames as F
    from errand.tui.machines import Machine
    os.environ[ "ERRAND_AGENT" ] = "direct"
    agents._open.clear()
    with scratch() as base:
        kept = os.environ.get( "ERRAND_CACHE_DIR" )
        os.environ[ "ERRAND_CACHE_DIR" ] = str( base )         # the agent's machine: this scratch directory
        target = { "kind": "local", "dir": str( base / "agents" / "w" ), "keep_alive": 10 }
        try:
            conn = agents.open( target )
            call = conn.open( { "op": "watch", "limit": 10 } )
            assert call.reply( 10 ).get( "ok" )

            def next_table( within ):
                deadline = time.monotonic() + within
                while time.monotonic() < deadline:
                    try:
                        kind, payload = call.next( timeout = max( 0.05, deadline - time.monotonic() ) )
                    except TimeoutError:
                        break
                    e = json.loads( payload ) if kind == F.OUT else { }
                    if "table" in e:
                        return e[ "table" ]
                return None

            first = next_table( 10 )
            assert first is not None and first[ "procs" ] == [ ] and "resources" in first, first
            started = time.monotonic()
            pid = agents.start( conn, [ "sh", "-c", "exec sleep 60" ] )
            got = next_table( 5 )
            took = time.monotonic() - started
            assert got and [ p[ "state" ] for p in got[ "procs" ] ] == [ "running" ], got
            assert took < 1.5, f"told {took:.2f} s after it started: not as it changed"
            pgid = got[ "procs" ][ 0 ][ "pgid" ]
            os.killpg( pgid, signal.SIGKILL )
            got = next_table( 5 )
            assert got is not None and got[ "procs" ] == [ ], got
            call.close()

            m = Machine( "w", target )                          # the screen's way: subscribed
            m.watch()
            deadline = time.monotonic() + 10
            while m.table is None and time.monotonic() < deadline:
                time.sleep( 0.05 )
            assert m.table is not None and m.error is None and m.table[ "procs" ] == [ ], ( m.table, m.error )
            agents.start( conn, [ "sh", "-c", "exec sleep 60" ] )
            deadline = time.monotonic() + 5
            while not m.table[ "procs" ] and time.monotonic() < deadline:
                time.sleep( 0.05 )
            assert m.table[ "procs" ], "the screen was not told"
            for p in m.table[ "procs" ]:
                os.killpg( p[ "pgid" ], signal.SIGKILL )
            m.stopped = True
        finally:
            if kept is None:
                os.environ.pop( "ERRAND_CACHE_DIR", None )
            else:
                os.environ[ "ERRAND_CACHE_DIR" ] = kept
            try:
                conn.close()
            except Exception:
                pass
            agents._open.clear()


if test( "one machine whatever names reach it; named once for all; a machine without work for a day is left alone" ):
    from errand.agents import ledger
    with scratch() as base:
        kept = os.environ.get( "ERRAND_CACHE_DIR" )
        os.environ[ "ERRAND_CACHE_DIR" ] = str( base )
        try:
            note = lambda host: ledger.note( { "kind": "ssh", "host": host, "options": [ ], "python": "python3", "keep_alive": 900 } )
            for host in ( "hugo.leclerc@cinaps", "cinaps", "urg11uj@jz", "lmo", "n22", "node22" ):
                note( host )
                time.sleep( 0.01 )
            ledger.learn( "n22", "node22.lab" )
            ledger.learn( "node22", "node22.lab" )                     # two names that answered alike
            got = { tuple( g[ "names" ] ): g[ "name" ] for g in ledger.groups() }
            assert got == { ( "cinaps", "hugo.leclerc@cinaps" ): "hugo.leclerc@cinaps", ( "urg11uj@jz", ): "urg11uj@jz",
                             ( "lmo", ): "lmo", ( "n22", "node22" ): "n22" }, got        # the oldest name shows
            assert ledger.rename( "cinaps", "the lab" ) == [ "cinaps", "hugo.leclerc@cinaps" ]
            assert [ g[ "name" ] for g in ledger.groups() if "cinaps" in g[ "names" ] ] == [ "the lab" ]
            assert sorted( ledger.forget( "the lab" ) ) == [ "cinaps", "hugo.leclerc@cinaps" ], "forgotten whole"
            assert not ledger.dormant( ledger.groups()[ 0 ] )
            assert ledger.dormant( { "last": time.time() - ledger.DORMANT - 1 } )
        finally:
            if kept is None:
                os.environ.pop( "ERRAND_CACHE_DIR", None )
            else:
                os.environ[ "ERRAND_CACHE_DIR" ] = kept
