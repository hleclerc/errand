"""`errand tui`: what runs where, for whom, since when, and what waits.

The list is built without a terminal ( `tui.rows` ); the agent's ops ( `agents.look` ) are called as
the watcher calls them for this machine; and the screen itself is driven through a real terminal,
over a real agent and a real process, in a cache directory of its own.
"""
import contextlib
import os
import shutil
import signal
import tempfile
import time
from pathlib import Path

from errand import test

from _tty import DOWN, plain, Term, tui_env
import sys


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


def a_machine( name = "lmo", here = False ):
    from errand.tui.machines import Machine
    now = time.time()
    m = Machine( name, None if here else { "kind": "ssh", "host": name } )
    m.table = { "time": now, "procs": [
        { "id": "a1", "project": "/home/h/sdot-ffi", "what": "run test_x.py::solve", "env": "lmo-jax",
          "started": now - 700, "state": "running", "pgid": 12 },
        { "id": "b2", "project": "/home/h/otrec", "what": "run grid", "started": now - 9000, "state": "running",
          "waiting": { "what": "slurm job 81234 pending", "since": now - 120 } },
        { "id": "c3", "project": "/home/h/otrec", "what": "windows vm keeper", "vm": True, "started": now, "state": "running" } ],
        "vms": [ { "name": "3fa2c1aa77", "state": "ready", "cpus": 8, "ram": "16G", "keeper": 5 } ],
        "guests": [ { "vm": "3fa2c1aa77", "procs": [ { "id": "g", "project": "C:/w/sdot-ffi", "what": "run ping",
                                                        "started": now - 30, "state": "running" } ] } ] }
    m.read_at = now
    m.history = { "runs": [ { "leaf": "/x/leaf", "project": "/home/h/sdot-ffi", "what": "a.py::b", "started": now - 3600,
                              "status": "FAIL", "duration": 12.3 } ], "more": 0 }
    return m


if test( "the list: a machine, what runs there oldest first, its vms with their guests' work, its history folded" ):
    from errand.tui import rows as R
    got = [ ( r.depth, r.kind, r.mark, r.label.split()[ 0 ] ) for r in R.build( [ a_machine() ] ) ]
    assert got == [ ( 0, "machine", None, "lmo" ), ( 1, "proc", "wait", "otrec" ), ( 1, "proc", "run", "sdot-ffi" ),
                    ( 1, "vm", "", "windows" ), ( 2, "proc", "run", "sdot-ffi" ), ( 1, "group", None, "history" ) ], got
    head = R.build( [ a_machine() ] )[ 0 ].detail
    assert "1 running" in head and "1 waiting" in head and "1 vm" in head, head
    waits = R.build( [ a_machine() ] )[ 1 ].detail
    assert "waiting: slurm job 81234 pending, 2 min" in waits and waits.startswith( "2 h 30" ), waits
    opened = R.build( [ a_machine() ], opened = { "lmo" } )
    assert [ ( r.kind, r.mark ) for r in opened[ -1 : ] ] == [ ( "run", "FAIL" ) ], "an opened history shows its runs"
    assert [ r.kind for r in R.build( [ a_machine() ], folded = { "lmo" } ) ] == [ "machine" ], "a folded machine hides all"


if test( "a step: the row says its text and bar, the detail its curves and views, a finished run its journal ( ADR 0010 )" ):
    import json
    from errand import steps
    from errand.tui import rows as R
    from errand.tui.machines import Machine
    from errand.tui.screen import Screen
    m = a_machine()
    p = m.table[ "procs" ][ 0 ]
    p[ "step" ] = steps.summarize( [ { "t": time.time() - 3, "text": "iteration 41", "done": 0.41, "residual": 1e-3 },
                                     { "t": time.time() - 1, "residual": 1e-7 } ] )
    row = next( r for r in R.build( [ m ] ) if r.data[ 1 ] is p )
    assert "iteration 41" in row.detail and "41 %" in row.detail and "▕" in row.detail, row.detail
    facts = dict( R.facts( row, m ) )
    assert facts[ "step" ] == "iteration 41" and "41 %" in facts[ "progress" ] and facts[ "said" ] == "1 s ago", facts
    assert facts[ "residual" ].endswith( "1e-07" ) and facts[ "residual" ][ 0 ] == "█", facts
    with scratch() as leaf:
        ( leaf / "output.txt" ).write_text( "converging\n" )
        ( leaf / "plot.html" ).write_text( "<p>1</p>" )
        ( leaf / steps.FILE ).write_text( "".join( json.dumps( e ) + "\n" for e in [
            { "t": 1, "view": "plot.html", "title": "convergence" }, { "t": 2, "text": "iteration 9", "energy": 3 } ] ) )
        here = Machine( "here" )
        here.read_at = time.time()
        here.history = { "runs": [ { "leaf": str( leaf ), "project": "/x/p", "what": "a.py::b", "started": 1 } ] }
        screen = Screen( [ here ] )
        run = next( r for r in R.build( [ here ], opened = { "here" } ) if r.kind == "run" )
        screen.describe( run )
        deadline = time.monotonic() + 10
        while R.key( run ) not in screen.seen and time.monotonic() < deadline:
            time.sleep( 0.05 )
        shown = [ ( r.kind, r.label, r.detail ) for r in screen.describe( run ) ]
        assert any( label.startswith( "step" ) and "iteration 9" in label for _, label, _ in shown ), shown
        assert any( label.startswith( "energy" ) for _, label, _ in shown ), shown
        view = next( ( r for r in shown if r[ 0 ] == "file" and r[ 1 ] == "convergence" ), None )
        assert view is not None and view[ 2 ] == "plot.html", shown


if test( "the list: the filter, the current project only, and the current project highlighted" ):
    from errand.tui import rows as R
    found = R.build( [ a_machine() ], query = "slurm" )
    assert [ r.label.split()[ 0 ] for r in found ] == [ "lmo", "otrec" ], [ r.label for r in found ]
    mine = R.build( [ a_machine() ], only = { "sdot-ffi" }, mine = { "sdot-ffi" }, opened = { "lmo" } )
    assert { r.label.split()[ 0 ] for r in mine if r.kind in ( "proc", "run" ) } == { "sdot-ffi" }, [ r.label for r in mine ]
    assert all( list( r.hits ) == list( range( 8 ) ) for r in mine if r.kind in ( "proc", "run" ) ), "not highlighted"
    broken = a_machine()
    broken.error = "ssh: connect to host lmo port 22: Operation timed out"
    head = R.build( [ broken ] )[ 0 ]
    assert head.kind == "broken" and "cannot say: ssh" in head.detail and "last table shown" in head.detail, head.detail


if test( "the agent's ops: the files of a leaf newest first, a file's end, a group stopped then its cancel line run" ):
    from errand.agents import look
    import subprocess
    with scratch() as base:
        ( base / "leaf" ).mkdir()
        ( base / "leaf" / "result.yaml" ).write_text( "status: PASS\n" )
        time.sleep( 0.02 )
        ( base / "leaf" / "output.txt" ).write_text( "".join( f"line {i}\n" for i in range( 1000 ) ) )
        files = look.answer( { "op": "ls", "path": str( base / "leaf" ) } )[ "files" ]
        assert [ f[ "name" ] for f in files ] == [ "output.txt", "result.yaml" ], files
        got = look.answer( { "op": "tail", "path": str( base / "leaf" / "output.txt" ), "size": 9 } )
        assert got[ "data" ] == "line 999\n" and got[ "end" ] == got[ "size" ], got
        got = look.answer( { "op": "tail", "path": str( base / "leaf" / "output.txt" ), "offset": 0, "size": 7 } )
        assert got[ "data" ] == "line 0\n" and got[ "end" ] == 7, got
        assert look.answer( { "op": "tail", "path": str( base / "nope" ) } ).get( "missing" )

        mark = base / "mark"
        mark.mkdir()
        ( mark / "cancel" ).write_text( f"touch {base / 'cancelled'}" )
        # INT is ignored: TERM ends it, and its cancel line runs after.
        p = subprocess.Popen( [ "sh", "-c", "trap '' INT; sleep 60 & wait" ], start_new_session = True )
        from errand.agents.procs import started
        assert look.answer( { "op": "kill", "pgid": p.pid, "since": started( p.pid ), "mark": str( mark ) } )[ "ok" ]
        assert gone( p.pid, 10 ) or p.wait( 10 ) is not None
        deadline = time.monotonic() + 10
        while not ( base / "cancelled" ).exists() and time.monotonic() < deadline:
            time.sleep( 0.1 )
        assert ( base / "cancelled" ).exists(), "the cancel line of a stopped process did not run"
        assert "not running" in look.answer( { "op": "kill", "pgid": p.pid } ).get( "error", "" )


if test( "history: a link per run, newest first, with its result; a link whose leaf is gone goes" ):
    from errand.agents import seen
    with scratch() as base:
        os.environ[ "ERRAND_CACHE_DIR" ] = str( base / "cache" )
        os.environ[ "ERRAND_PROC_DIR" ] = str( base / "mark" )
        ( base / "mark" ).mkdir()
        try:
            for name in ( "old", "new" ):
                ( base / name ).mkdir()
                seen.note( base / name, base / "proj", f"t.py::{name}", "lin" )
                time.sleep( 0.02 )
            ( base / "new" / "result.yaml" ).write_text( "status: PASS\nduration_s: 1.5\n" )
            assert ( base / "mark" / "leaf" ).read_text() == str( ( base / "new" ).resolve() ), "the owner was not told the leaf"
            got = seen.runs()
            assert [ ( r[ "what" ], r[ "status" ] ) for r in got[ "runs" ] ] == [ ( "t.py::new", "PASS" ), ( "t.py::old", None ) ], got
            shutil.rmtree( base / "old" )
            assert [ r[ "what" ] for r in seen.runs()[ "runs" ] ] == [ "t.py::new" ]
            assert len( list( ( base / "cache" / "seen" ).glob( "*.json" ) ) ) == 1, "a dead link was kept"
        finally:
            del os.environ[ "ERRAND_CACHE_DIR" ], os.environ[ "ERRAND_PROC_DIR" ]


if test( "the screen: a process an agent runs here, its output beside it, a run in the history, and `s` stops it" ):
    from errand import agents
    from errand.agents import seen
    os.environ[ "ERRAND_AGENT" ] = "direct"
    agents._open.clear()
    with scratch() as base:
        cache = base / "cache"
        os.environ[ "ERRAND_CACHE_DIR" ] = str( cache )
        leaf = base / "proj" / "errand-outputs" / "runs" / "t" / "case" / "2026-11-15_x"
        leaf.mkdir( parents = True )
        ( leaf / "output.txt" ).write_text( "the run said this\n" )
        ( leaf / "result.yaml" ).write_text( "status: PASS\nduration_s: 2.0\n" )
        seen.note( leaf, base / "proj", "test_t.py::case", "plain" )
        conn = agents.open( { "kind": "local", "dir": str( cache / "agents" / "a" ), "keep_alive": 30 } )
        call = conn.open( { "op": "spawn", "argv": [ "sh", "-c", "echo hello-from-the-process; exec sleep 60" ],
                            "cwd": str( base ), "keep": True, "store": str( base / "proj" / "errand-outputs" / "state" / "procs" ) } )
        pid = call.reply( 10 )[ "pid" ]
        call.close()
        env = { **tui_env( base ), "ERRAND_CACHE_DIR": str( cache ), "PAGER": "cat" }
        term = Term( [ sys.executable, "-m", "errand", "tui" ], base, env = env )
        try:
            assert term.wait_for( "sh -c echo", 30 ), plain( term.buf )[ -2000 : ]
            shown = term.text()
            assert "this machine" in shown and "proj" in shown and "running" in shown, shown
            term.send( DOWN )                      # the process: its output, beside it
            assert term.wait_for( "hello-from-the-process", 30 ), plain( term.buf )[ -3000 : ]

            term.send( DOWN )                      # the history row
            term.send( "\x1bOC" )                   # → opens it
            assert term.wait_for( "test_t.py::case", 10 ), plain( term.buf )[ -3000 : ]
            term.send( DOWN )
            assert term.wait_for( "the run said this", 10 ), plain( term.buf )[ -3000 : ]

            term.send( "/hello" )                  # a filter that only the process passes
            term.send( "\r" )
            assert "test_t.py::case" not in term.frame(), "the filter kept a run it does not match"
            term.send( "\x1b" )

            term.send( "\x1bOH" )                  # home: the machine
            term.send( DOWN )                      # the process
            term.send( "s" )
            assert term.wait_for( "y stops it", 10 ), plain( term.buf )[ -2000 : ]
            term.send( "y" )
            # Its group is gone ( the pid the agent gave may be a zygote's child, under `errand run` ).
            assert term.wait_for( "idle · read", 15 ), "s y did not stop the process: " + plain( term.buf )[ -600 : ]
            from errand.agents.table import procs_of, served
            assert procs_of( cache / "agents" / "a", served( cache / "agents" / "a" ) ) == [ ]
            term.send( "q", settle = 0.1 )
            deadline = time.monotonic() + 10      # read on: leaving curses waits for its output to drain
            while term.child.poll() is None and time.monotonic() < deadline:
                term.read( 0.2 )
            assert term.child.poll() == 0, "q did not leave"
        finally:
            term.close()
            try:
                os.killpg( pid, signal.SIGKILL )
            except OSError:
                pass
            conn.close()
            agents._open.clear()
            del os.environ[ "ERRAND_CACHE_DIR" ]
