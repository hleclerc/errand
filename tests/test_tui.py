"""`errand tui`: what runs where, for whom, since when, and what waits.

The list is built without a terminal ( `tui.rows` ); the agent's ops ( `agents.look` ) are called as
the watcher calls them for this machine; and the screen itself is driven through a real terminal,
over a real agent and a real process, in a cache directory of its own.
"""
import contextlib
import os
import re
import shutil
import signal
import tempfile
import time
from pathlib import Path

from errand import test

from _record import from_histories
from_histories()

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


if test( "the runs tab: what runs, what waits, every run as a tree ( ADR 0023 ), of every machine; the machines tab: machines and vms" ):
    from errand.tui import rows as R
    got = [ ( r.kind, r.mark, r.label.split()[ 0 ] ) for r in R.build( [ a_machine() ] ) ]
    assert got == [ ( "day", None, "running" ), ( "proc", "run", "lmo" ), ( "proc", "run", "lmo" ),
                    ( "day", None, "waiting" ), ( "proc", "wait", "lmo" ), ( "tnode", "", "a.py" ) ], got
    rows = R.build( [ a_machine() ] )
    assert rows[ 1 ].label.split()[ 1 ] == "run" and "test_x.py::solve" in rows[ 1 ].label, "the machine, then what"
    waits = rows[ 4 ].detail
    assert waits.endswith( "waiting: slurm job 81234 pending, 2 min" ), "how long it waits, once, not an hour ( " + waits + " )"
    runs = rows[ 2 ].detail
    assert not re.search( r"\d\d:\d\d", runs ) and re.search( r"\d+ (s|min|h)", runs ), "a run running says for how long: " + runs
    assert rows[ 5 ].open is False and rows[ 5 ].detail.startswith( "1 run" ), "its file, folded: how many runs, when"
    run = next( r for r in R.build( [ a_machine() ], unfold = True ) if r.kind == "run" )
    assert run.mark == "FAIL" and re.match( r"\d\d:\d\d", run.label ), run.label
    got = [ ( r.depth, r.kind, r.label.split()[ 0 ] ) for r in R.build( [ a_machine() ], tab = "machines" ) ]
    assert got == [ ( 0, "machine", "lmo" ), ( 1, "vm", "windows" ), ( 2, "proc", "sdot-ffi" ) ], got
    head = R.build( [ a_machine() ], tab = "machines" )[ 0 ]
    assert head.detail == "1/1", head.detail                    # running / waiting: short, so that the gauges line up
    m = a_machine()
    assert dict( R.facts( head, m ) )[ "work" ] == "1 running, 1 waiting, 1 vm", R.facts( head, m )
    assert [ r.kind for r in R.build( [ a_machine() ], folded = { "lmo" }, tab = "machines" ) ] == [ "machine" ]


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
        run = next( r for r in R.build( [ here ], unfold = True ) if r.kind == "run" )
        screen.describe( run )
        deadline = time.monotonic() + 10
        while R.key( run ) not in screen.seen and time.monotonic() < deadline:
            time.sleep( 0.05 )
        shown = [ ( r.kind, r.label, r.detail ) for r in screen.describe( run ) ]
        assert any( label.startswith( "step" ) and "iteration 9" in label for _, label, _ in shown ), shown
        assert any( label.startswith( "energy" ) for _, label, _ in shown ), shown
        view = next( ( r for r in shown if r[ 0 ] == "output" and r[ 1 ] == "convergence" ), None )
        assert view is not None and view[ 2 ] == "plot.html", shown


if test( "the list: the filter, the current project only, and the current project highlighted" ):
    from errand.tui import rows as R
    found = R.build( [ a_machine() ], query = "slurm" )
    assert [ r.kind for r in found ] == [ "day", "proc" ] and "grid" in found[ 1 ].label, [ r.label for r in found ]
    mine = R.build( [ a_machine() ], only = { "sdot-ffi" }, mine = { "sdot-ffi" }, unfold = True )
    assert all( "sdot-ffi" in str( r.data[ 1 ].get( "project" ) ) for r in mine if r.kind in ( "proc", "run" ) ), [ r.label for r in mine ]
    assert any( r.kind == "proc" for r in mine ) and any( r.kind == "run" for r in mine ), [ r.label for r in mine ]
    broken = a_machine()
    broken.error = "ssh: connect to host lmo port 22: Operation timed out"
    head = R.build( [ broken ], tab = "machines" )[ 0 ]
    assert head.kind == "broken" and head.detail == "✗", head.detail                  # why: in the detail
    assert "ssh" in dict( R.facts( head, broken ) )[ "error" ], R.facts( head, broken )


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


if test( "the screen: what runs, its output; a run done, as the console drew it; the machines; and `k` kills" ):
    from errand import agents
    from errand.agents import seen
    os.environ[ "ERRAND_AGENT" ] = "direct"
    agents._open.clear()
    with scratch() as base:
        cache = base / "cache"
        os.environ[ "ERRAND_CACHE_DIR" ] = str( cache )
        leaf = base / "proj" / "errand-outputs" / "runs" / "t" / "case" / "2026-11-15_10h00m00-plain"   # ( a run's stamp )
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
            term.read( 1.5 )
            shown = plain( term.buf )               # ( drawn when something happens: everything written so far )
            assert "1 runs" in shown and "running ( 1 )" in shown, shown         # the runs tab first
            term.send( DOWN )                      # under `running`, the process: its output, beside it
            assert term.wait_for( "hello-from-the-process", 30 ), plain( term.buf )[ -3000 : ]

            RIGHT = "\x1bOC"                       # ( → )
            term.send( DOWN )                      # the run done is in the tree ( ADR 0023, 0025 ): its file, folded
            term.send( RIGHT )                     # unfolded: its entry
            term.send( DOWN )
            term.send( RIGHT )                     # unfolded: its run
            term.send( DOWN )                      # the run done: its output, as the console drew it
            assert term.wait_for( "the run said this", 10 ), plain( term.buf )[ -3000 : ]
            assert term.wait_for( "╰ PASS", 10 ), plain( term.buf )[ -3000 : ]

            term.send( "/hello" )                  # a filter that only the process passes
            term.send( "\r" )
            assert "test_t.py::case" not in term.frame(), "the filter kept a run it does not match"
            term.send( "\x1b" )

            term.send( "2" )                       # the machines tab
            assert term.wait_for( "this machine", 10 ), plain( term.buf )[ -2000 : ]
            term.send( "1" )                       # back to the runs
            term.send( "\x1bOH" )                  # home: `running`
            term.send( DOWN )                      # the process
            term.send( "k" )
            assert term.wait_for( "enter: kill", 10 ), plain( term.buf )[ -2000 : ]
            term.send( "\r" )
            term.buf = ""
            # Its group is gone ( the pid the agent gave may be a zygote's child, under `errand run` ).
            assert term.wait_for( "● 0 running", 15 ), "k enter did not kill the process: " + plain( term.buf )[ -600 : ]
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


if test( "f forgets the machine under the cursor, once confirmed; this machine cannot be" ):
    from errand.agents import ledger
    from errand.tui import rows as R
    from errand.tui.machines import Machine
    from errand.tui.screen import Screen
    base = Path( tempfile.mkdtemp( dir = "/tmp" ) )
    kept = os.environ.get( "ERRAND_CACHE_DIR" )
    os.environ[ "ERRAND_CACHE_DIR" ] = str( base )
    try:
        ledger.note( { "kind": "ssh", "host": "h", "options": [ ], "python": "python3", "keep_alive": 900 } )
        here, far = Machine( "here" ), a_machine( "h" )
        here.read_at = time.time()
        screen = Screen( [ here, far ] )
        screen.list.rows = R.build( screen.machines, tab = "machines" )
        screen.list.cursor = next( i for i, r in enumerate( screen.list.rows ) if r.kind == "machine" and r.data[ 0 ] == "h" )
        screen.forget()
        assert screen.confirm and screen.confirm.title == "forget h?" and screen.confirm.verb == "forget", screen.confirm
        assert [ m[ "name" ] for m in ledger.machines() ] == [ "h" ], "nothing before y"
        screen.confirm.go()
        assert ledger.machines() == [ ] and far not in screen.machines and far.stopped, screen.message
        screen.confirm = None
        screen.list.rows = R.build( screen.machines, tab = "machines" )
        screen.list.cursor = next( i for i, r in enumerate( screen.list.rows ) if r.kind == "machine" )
        screen.forget()
        assert screen.confirm is None and "always shown" in screen.message, screen.message
    finally:
        if kept is None:
            os.environ.pop( "ERRAND_CACHE_DIR", None )
        else:
            os.environ[ "ERRAND_CACHE_DIR" ] = kept
        shutil.rmtree( base, ignore_errors = True )



if test( "k on a machine kills everything errand runs there, once confirmed in its window; on a process, that one" ):
    from errand.tui import rows as R
    from errand.tui.loop import handle
    from errand.tui.screen import Screen
    far = a_machine( "lmo" )
    asked = [ ]
    far.ask = lambda req, timeout = 60: asked.append( req ) or { "ok": True }
    screen = Screen( [ far ] )
    screen.list.rows = R.build( screen.machines, tab = "machines" )
    screen.list.cursor = next( i for i, r in enumerate( screen.list.rows ) if r.kind == "machine" )
    screen.active = 0
    handle( screen, ord( "k" ) )
    c = screen.confirm
    assert c and c.verb == "kill" and c.danger and "lmo" in c.title and any( "test_x.py::solve" in l for l in c.lines ), c
    handle( screen, 27 )                                      # esc: nothing
    assert screen.confirm is None and asked == [ ] and screen.message == "nothing done"
    handle( screen, ord( "k" ) )
    handle( screen, 10 )                                      # enter: kill
    deadline = time.monotonic() + 5
    while not asked and time.monotonic() < deadline:
        time.sleep( 0.02 )
    assert [ r[ "pgid" ] for r in asked ] == [ 12 ], asked     # the one row with a process group
    asked.clear()
    screen.list.rows = R.build( screen.machines )               # the runs tab: the work
    screen.list.cursor = next( i for i, r in enumerate( screen.list.rows ) if r.kind == "proc" and "solve" in str( r.data ) )
    handle( screen, ord( "k" ) )
    assert screen.confirm.title.startswith( "kill " ) and "solve" in screen.confirm.title, screen.confirm


if test( "a machine's resources: measured by its agent, as gauges on its row, in words in its detail" ):
    from errand.agents import resources
    from errand.tui import rows as R
    got = resources.measure()
    assert got[ "cpus" ] >= 1 and ( got[ "busy" ] is None or 0 <= got[ "busy" ] <= 1 ), got
    assert got[ "ram" ] is None or 0 < got[ "ram" ][ "used" ] <= got[ "ram" ][ "total" ], got
    started = time.time()
    resources.measure()
    assert time.time() - started < 0.5, "cheap enough for every table"
    res = { "cpus": 128, "busy": 0.68, "load": 87.1, "ram": { "total": 524288, "used": 215040 },
            "gpus": [ { "index": 0, "name": "A100", "util": 87.0, "used": 30720.0, "total": 81920.0 } ],
            "held": { "cpus": 16.0, "ram": 65536.0, "gpus": 1, "exclusive": False, "claims": 2 }, "scheduler": None }
    assert [ ( n, round( f, 2 ) ) for n, f in R.meters( res ) ] == [ ( "cpu", 0.68 ), ( "ram", 0.41 ), ( "gpu0", 0.87 ) ]
    four = dict( res, gpus = [ dict( res[ "gpus" ][ 0 ], index = i, util = 50.0 ) for i in range( 4 ) ] )
    assert R.meters( four )[ -1 ] == ( "gpu×4", 0.5 ), "beyond two cards, their mean"
    facts = dict( R.resource_facts( res ) )
    assert facts[ "cpu" ] == "68 % of 128 cores · load 87.1" and facts[ "ram" ] == "210 G of 512 G used", facts
    assert facts[ "gpu 0" ] == "A100 · 87 % · 30 G of 80 G" and facts[ "held" ] == "by errand: 16 cpus · 64 G · 1 gpu ( 2 claims )", facts
    m = a_machine( "lmo" )
    m.table[ "resources" ] = res
    row = next( r for r in R.build( [ m ], tab = "machines" ) if r.kind == "machine" )
    assert [ n for n, _ in row.meters ] == [ "cpu", "ram", "gpu0" ], row.meters
    assert R.meters( None ) == [ ] and R.resource_facts( None ) == [ ], "an older agent says nothing of them"


if test( "a machine without work for a day is greyed and not contacted until a; r names a machine" ):
    from errand.agents import ledger
    from errand.tui import rows as R
    from errand.tui.loop import handle
    from errand.tui.machines import Machine
    from errand.tui.screen import Screen
    base = Path( tempfile.mkdtemp( dir = "/tmp" ) )
    kept = os.environ.get( "ERRAND_CACHE_DIR" )
    os.environ[ "ERRAND_CACHE_DIR" ] = str( base )
    try:
        ledger.note( { "kind": "ssh", "host": "jz", "options": [ ], "python": "python3", "keep_alive": 900 } )
        old = Machine( "jz", { "kind": "ssh", "host": "jz" }, time.time() - 3 * 86400, [ "jz" ] )
        assert old.dormant
        started = [ ]
        old._loop = lambda: started.append( 1 )
        old.watch()
        time.sleep( 0.1 )
        assert started == [ ], "contacted though dormant"
        screen = Screen( [ old ] )
        screen.list.rows = R.build( screen.machines, tab = "machines" )
        row = screen.list.rows[ 0 ]
        assert row.kind == "dormant" and row.detail.startswith( "3 d" ) and not row.meters, ( row.kind, row.detail )
        assert "not contacted" in dict( R.facts( row, old ) )[ "dormant" ]
        handle( screen, ord( "a" ) )
        time.sleep( 0.1 )
        assert not old.dormant and started == [ 1 ] and "watching jz" in screen.message, screen.message
        assert ledger.groups()[ 0 ][ "watch" ] is True, "saved: the next screen, and errand status, watch it too"
        screen.list.rows = R.build( screen.machines, tab = "machines" )
        handle( screen, ord( "r" ) )
        assert screen.prompt and screen.prompt.text == "jz", screen.prompt
        for k in "jean-zay":                                  # the first letter replaces the name, as selected
            handle( screen, ord( k ) )
        handle( screen, 10 )
        assert old.name == "jean-zay" and [ g[ "name" ] for g in ledger.groups() ] == [ "jean-zay" ], ledger.groups()
    finally:
        if kept is None:
            os.environ.pop( "ERRAND_CACHE_DIR", None )
        else:
            os.environ[ "ERRAND_CACHE_DIR" ] = kept
        shutil.rmtree( base, ignore_errors = True )


if test( "a on a watched machine switches its gauges off, saved, what runs followed still; agents kept warm are no work" ):
    from errand.agents import ledger
    from errand.tui import rows as R
    from errand.tui.loop import handle
    from errand.tui.screen import Screen
    base = Path( tempfile.mkdtemp( dir = "/tmp" ) )
    kept = os.environ.get( "ERRAND_CACHE_DIR" )
    os.environ[ "ERRAND_CACHE_DIR" ] = str( base )
    try:
        ledger.note( { "kind": "ssh", "host": "lmo", "options": [ ], "python": "python3", "keep_alive": 900 } )
        m = a_machine( "lmo" )
        m.names = [ "lmo" ]
        m.table[ "procs" ].append( { "id": "ag", "kind": "agent", "project": "/home/h/p", "what": "environment agent env-1",
                                     "started": time.time() - 60, "state": "running", "pgid": 99 } )
        rows = R.build( [ m ], tab = "machines" )
        assert rows[ 0 ].detail == "1/1" and not any( "environment agent" in r.label for r in rows ), [ r.label for r in rows ]
        assert dict( R.facts( rows[ 0 ], m ) )[ "agents" ].startswith( "1 kept warm" )
        screen = Screen( [ m ] )
        screen.list.rows = rows
        sent = [ ]
        m._call = type( "C", ( ), { "send": lambda self, kind, data: sent.append( data ) } )()
        m.want_resources( True )
        handle( screen, ord( "a" ) )
        assert not m.dormant and m.table is not None and not m.gauges and "gauges not measured" in screen.message, screen.message
        assert sent == [ b'{"resources": true}', b'{"resources": false}' ], sent
        g = ledger.groups()[ 0 ]
        assert g[ "gauges" ] is False and ledger.watched( g ), "saved, and still contacted"
        m.want_resources( True )
        assert len( sent ) == 2, "the machines tab shown again: still no gauges"
        handle( screen, ord( "a" ) )
        assert m.gauges and ledger.groups()[ 0 ][ "gauges" ] is True and sent[ -1 ] == b'{"resources": true}', sent
        old = { "name": "x", "watch": False }                                      # an older ledger's `watch: false`
        assert not ledger.gauges( old ) and ledger.watched( { **old, "last": time.time() } ), "read as its gauges off"
    finally:
        if kept is None:
            os.environ.pop( "ERRAND_CACHE_DIR", None )
        else:
            os.environ[ "ERRAND_CACHE_DIR" ] = kept
        shutil.rmtree( base, ignore_errors = True )


if test( "r names this machine too; ← → fold a node of the runs' tree, ← goes up to it; the cursor stays on a run as it ends and others arrive" ):
    from errand.agents import ledger
    from errand.tui import rows as R
    from errand.tui.loop import handle
    from errand.tui.machines import Machine
    from errand.tui.screen import Screen
    import curses
    base = Path( tempfile.mkdtemp( dir = "/tmp" ) )
    kept = os.environ.get( "ERRAND_CACHE_DIR" )
    os.environ[ "ERRAND_CACHE_DIR" ] = str( base )
    try:
        here = Machine( ledger.here_name() )
        here.read_at, now = time.time(), time.time()
        runs = [ { "leaf": f"/x/leaf{i}", "project": "/x/p", "what": f"a.py::c{i}", "started": now - 100 - i, "status": "PASS" }
                 for i in range( 3 ) ]
        here.history = { "runs": list( runs ) }
        here.table = { "procs": [ ] }
        screen = Screen( [ here ] )
        screen.list.box = screen.detail.box = ( 1, 0, 20, 80 )
        screen.build()
        assert [ r.kind for r in screen.list.rows ] == [ "tnode" ], [ r.label for r in screen.list.rows ]   # a.py, folded
        handle( screen, curses.KEY_RIGHT )                    # → unfolds it: its entries, newest first
        screen.build()
        assert [ r.label for r in screen.list.rows ] == [ "a.py", "c0", "c1", "c2" ], [ r.label for r in screen.list.rows ]
        for _ in range( 3 ):                                  # each entry unfolded: its run
            handle( screen, curses.KEY_DOWN )
            handle( screen, curses.KEY_RIGHT )
            screen.build()
            handle( screen, curses.KEY_DOWN )
        assert [ r.kind for r in screen.list.rows ] == [ "tnode", "tnode", "run", "tnode", "run", "tnode", "run" ], \
            [ r.label for r in screen.list.rows ]
        while screen.list.current().data[ 1 ].get( "what" ) != "a.py::c1":
            handle( screen, curses.KEY_UP )
        # a new run, running: rows come before -- the cursor stays on c1
        here.table = { "procs": [ { "state": "running", "what": "a.py::new", "project": "/x/p", "leaf": "/x/new", "id": "n",
                                    "started": now } ] }
        screen.build()
        assert screen.list.current().data[ 1 ].get( "what" ) == "a.py::c1", screen.list.current().label
        # c1's own: running, then done -- the same run, by its leaf
        here.table = { "procs": [ ] }
        screen.build()
        assert screen.list.current().data[ 1 ].get( "what" ) == "a.py::c1"
        handle( screen, curses.KEY_LEFT )                     # ← on a run: up to its entry
        assert screen.list.current().kind == "tnode" and screen.list.current().label == "c1", screen.list.current().label
        handle( screen, curses.KEY_LEFT )                     # ← on the entry: folded
        screen.build()
        assert [ r.kind for r in screen.list.rows ].count( "run" ) == 2, [ r.label for r in screen.list.rows ]
        handle( screen, curses.KEY_RIGHT )                    # → unfolds it
        screen.build()
        assert [ r.kind for r in screen.list.rows ].count( "run" ) == 3
        handle( screen, ord( "r" ) )                          # on an entry: nothing to name, said in a window
        assert screen.confirm and "nothing to name" in screen.confirm.title, screen.confirm
        handle( screen, 10 )
        handle( screen, curses.KEY_DOWN )
        handle( screen, ord( "r" ) )                          # on a run of this machine: it can be named
        assert screen.prompt and screen.prompt.text == ledger.here_name(), screen.prompt
        for k in "mac":
            handle( screen, ord( k ) )
        handle( screen, 10 )
        assert here.name == "mac" and ledger.here_name() == "mac", ( here.name, screen.message )
        assert [ g[ "name" ] for g in ledger.groups() ] == [ ], "this machine is no machine to ask"
        handle( screen, ord( "1" ) )
        screen.build()
        handle( screen, 9 )                                   # tab: the detail, its outputs
        assert screen.active == 1
    finally:
        if kept is None:
            os.environ.pop( "ERRAND_CACHE_DIR", None )
        else:
            os.environ[ "ERRAND_CACHE_DIR" ] = kept
        shutil.rmtree( base, ignore_errors = True )


if test( "the detail: outputs to go through, the one under the cursor shown, enter opens it, e edits it" ):
    from errand.tui import rows as R
    from errand.tui.loop import handle
    from errand.tui.machines import Machine
    from errand.tui.screen import Screen
    import curses
    leaf = Path( tempfile.mkdtemp( dir = "/tmp" ) )
    try:
        ( leaf / "output.txt" ).write_text( "the console\n" )
        ( leaf / "notes.txt" ).write_text( "first line of notes\nsecond\n" )
        ( leaf / "data.bin" ).write_bytes( b"\x00\x01\x02" * 100 )
        here = Machine( "here" )
        here.read_at = time.time()
        here.table = { "procs": [ ] }
        here.history = { "runs": [ { "leaf": str( leaf ), "project": "/x/p", "what": "a.py::b", "started": time.time(), "status": "PASS" } ] }
        screen = Screen( [ here ] )
        screen.list.box, screen.detail.box = ( 1, 0, 30, 60 ), ( 1, 60, 30, 80 )
        opened, edited = [ ], [ ]
        screen.run_outside = lambda argv, cwd = None: edited.append( argv )
        screen.build()
        for _ in range( 2 ):                                  # the run's tree unfolded ( ADR 0023 ): its file, its entry
            handle( screen, curses.KEY_RIGHT )
            screen.build()
            handle( screen, curses.KEY_DOWN )
        assert screen.list.current().kind == "run", [ r.label for r in screen.list.rows ]

        def settle( what ):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                screen.build()
                if any( what in r.label for r in screen.detail.rows ):
                    return True
                time.sleep( 0.05 )
            return False

        assert settle( "the console" ), [ r.label for r in screen.detail.rows ]
        outputs = [ r.label for r in screen.detail.rows if r.kind == "output" ]
        assert outputs[ 0 ] == "console" and "notes.txt" in outputs and "output.txt" not in outputs, outputs
        handle( screen, 9 )                                   # tab: the detail
        screen.build()
        screen.detail.cursor = next( i for i, r in enumerate( screen.detail.rows ) if r.label == "notes.txt" )
        assert settle( "first line of notes" ), [ r.label for r in screen.detail.rows ]
        assert not any( "the console" in r.label for r in screen.detail.rows ), "the file shown, not the console"
        screen.detail.cursor = next( i for i, r in enumerate( screen.detail.rows ) if r.label == "data.bin" )
        assert settle( "binary" ), [ r.label for r in screen.detail.rows ]
        screen.detail.cursor = next( i for i, r in enumerate( screen.detail.rows ) if r.label == "notes.txt" )
        os.environ[ "VISUAL" ] = "myeditor -x"
        try:
            handle( screen, ord( "e" ) )
        finally:
            del os.environ[ "VISUAL" ]
        assert edited == [ [ "myeditor", "-x", str( leaf / "notes.txt" ) ] ], edited
        import subprocess
        real = subprocess.Popen
        subprocess.Popen = lambda argv, **kw: opened.append( argv )
        try:
            handle( screen, 10 )
        finally:
            subprocess.Popen = real
        assert opened and opened[ 0 ][ -1 ] == str( leaf / "notes.txt" ), opened
    finally:
        shutil.rmtree( leaf, ignore_errors = True )


if test( "a run that still runs: under running, and at its place in the tree, marked and open; ↓ goes past it" ):
    from errand.tui import rows as R
    from errand.tui.loop import handle
    from errand.tui.machines import Machine
    from errand.tui.screen import Screen
    import curses
    m = Machine( "here" )
    m.read_at, now = time.time(), time.time()
    m.table = { "procs": [ { "state": "running", "what": "a.py::live", "project": "/x/p", "leaf": "/x/live", "id": "l", "started": now } ] }
    m.history = { "runs": [ { "leaf": "/x/live", "project": "/x/p", "what": "a.py::live", "started": now },
                            { "leaf": "/x/old", "project": "/x/p", "what": "a.py::old", "started": now - 10, "status": "PASS" },
                            { "leaf": "/x/gone", "project": "/x/p", "what": "a.py::gone", "started": now - 20 } ] }
    screen = Screen( [ m ] )
    screen.list.box = screen.detail.box = ( 1, 0, 20, 80 )
    screen.build()
    shown = [ ( r.kind, r.mark, r.label.split()[ -1 ] if r.label else "" ) for r in screen.list.rows ]
    assert [ k for k in shown if k[ 2 ] == "a.py::live" ] == [ ( "proc", "run", "a.py::live" ) ], shown
    assert shown[ 2 : 5 ] == [ ( "tnode", "run", "a.py" ), ( "tnode", "run", "live" ), ( "run", "run", "running" ) ], shown
    assert ( "tnode", "", "gone" ) in shown and screen.list.rows[ -1 ].open is False, "a run that ended unsaid: folded"
    for _ in range( 6 ):
        handle( screen, curses.KEY_DOWN )
        screen.build()
    assert screen.list.current().label == "gone", [ r.label for r in screen.list.rows ]
