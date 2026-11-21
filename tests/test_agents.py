"""Agents ( ADR 0005 ): a process that stays, starts what it is asked to, and outlives its clients.

On this machine, with a `local` target: the same agent, bridge and protocol as over ssh, without the ssh.
The real thing is exercised on a host named in errand-envs.py, by hand ( `ERRAND_AGENT=hub errand -v run --env <ssh env>` ).
"""
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from errand import test

ROOT = Path( __file__ ).resolve().parent.parent


@contextlib.contextmanager
def scratch( ):
    """A directory under /tmp ( a unix socket's path must be short ), removed even while an agent still writes in it."""
    d = tempfile.mkdtemp( dir = "/tmp" )
    try:
        yield d
    finally:
        shutil.rmtree( d, ignore_errors = True )


def local( d, keep = 5 ):
    return { "kind": "local", "dir": str( d ), "keep_alive": keep }


def fresh( mode = "direct" ):
    from errand import agents
    os.environ[ "ERRAND_AGENT" ] = mode
    agents._open.clear()
    return agents


if test( "frames go through any byte stream, and a broken one says so" ):
    import io
    from errand.agents import frames as F
    buf = io.BytesIO( F.pack( 3, F.OPEN, { "op": "ping" } ) + F.pack( 3, F.OUT, b"\x00\xffraw" ) )
    assert F.read_frame( buf.read ) == ( 3, F.OPEN, b'{"op": "ping"}' )
    assert F.read_frame( buf.read ) == ( 3, F.OUT, b"\x00\xffraw" )
    try:
        F.read_frame( buf.read )
        raise AssertionError( "an empty stream gave a frame" )
    except F.Broken:
        pass


if test( "shell: output, errors, exit code, input, directory, timeout" ):
    agents = fresh()
    with scratch() as d:
        conn = agents.open( local( d ) )
        got = agents.shell( conn, "echo out; echo err >&2; exit 3", capture = True )
        assert ( got.stdout, got.stderr, got.returncode ) == ( "out\n", "err\n", 3 ), got
        assert agents.shell( conn, "cat", input = "piped", capture = True ).stdout == "piped"
        assert agents.shell( conn, "pwd", cwd = "/", capture = True ).stdout.strip() == "/"
        assert agents.shell( conn, "exit 0", quiet = True ).returncode == 0
        t = time.monotonic()
        try:
            agents.shell( conn, "sleep 30", timeout = 0.5 )
            raise AssertionError( "no timeout" )
        except subprocess.TimeoutExpired:
            assert time.monotonic() - t < 10
        conn.close()


if test( "one agent per directory, reached again by a new connection" ):
    agents = fresh()
    with scratch() as d:
        first = agents.open( local( d ) ).ping()[ "pid" ]
        agents._open.clear()
        assert agents.open( local( d ) ).ping()[ "pid" ] == first, "a second agent was started"


if test( "losing the connection loses nothing: the process goes on, and is caught up with" ):
    agents = fresh()
    from errand.agents import frames as F
    with scratch() as d:
        conn = agents.open( local( d ) )
        pid = agents.start( conn, [ "sh", "-c", "echo one; sleep 1; echo two; exit 7" ] )
        call = agents.attach( conn, pid )
        kind, payload = call.next( 10 )
        assert ( kind, payload ) == ( F.OUT, b"one\n" ), ( kind, payload )
        conn.close()                                   # the laptop closes
        agents._open.clear()
        call = agents.attach( agents.open( local( d ) ), pid, out = len( payload ) )
        rest, code = b"", None
        while code is None:
            kind, payload = call.next( 30 )
            rest += payload if kind == F.OUT else b""
            code = F.load( payload )[ "code" ] if kind == F.EXIT else None
        assert ( rest, code ) == ( b"two\n", 7 ), ( rest, code )
        time.sleep( 0.2 )
        assert not ( Path( d ) / "proc" / pid ).exists(), "delivered: nobody needs it any more"


if test( "the agent's directory holds only what runs; the output is the project's, until delivered" ):
    agents = fresh()
    from errand.agents import frames as F
    with scratch() as d, scratch() as project:
        store = f"{project}/errand-outputs/state/procs"
        conn = agents.open( local( d ) )
        pid = agents.start( conn, [ "sh", "-c", "echo one; sleep 1; echo two" ], store = store )
        mark = Path( d ) / "proc" / pid
        assert ( mark / "where" ).read_text() == f"{store}/{pid}" and not ( mark / "out" ).exists()
        conn.close()                                   # gone before the end: nothing delivered
        agents._open.clear()
        time.sleep( 2 )
        assert not mark.exists(), "finished: nothing of it left in the agent's directory"
        assert ( Path( store ) / pid / "out" ).read_bytes() == b"one\ntwo\n", "kept in the project"
        conn = agents.open( local( d ) )
        call = conn.open( { "op": "list", "store": store, "ids": [ pid ] } )
        assert [ p[ "code" ] for p in call.reply( 10 )[ "procs" ] ] == [ 0 ]
        call = agents.attach( conn, pid, store = store )
        got = [ call.next( 10 ) ]
        while got[ -1 ][ 0 ] != F.EXIT:
            got.append( call.next( 10 ) )
        assert got[ 0 ] == ( F.OUT, b"one\ntwo\n" ), got
        time.sleep( 0.2 )
        assert not ( Path( store ) / pid ).exists(), "brought back: it goes"
        agents._open.clear()


if test( "a probe does not outlive its client" ):
    agents = fresh()
    with scratch() as d:
        conn = agents.open( local( d ) )
        marker = Path( d ) / "still-here"
        call = conn.open( { "op": "spawn", "argv": [ "sh", "-c", f"sleep 2; touch {marker}" ], "keep": False } )
        call.reply()
        conn.close()
        time.sleep( 4 )
        assert not marker.exists(), "a process that may not outlive its client did"


if test( "nor its channel: through a hub the stream stays, and a closed channel is a client gone" ):
    agents = fresh()
    with scratch() as d:
        conn = agents.open( local( d ) )
        marker = Path( d ) / "still-here"
        call = conn.open( { "op": "spawn", "argv": [ "sh", "-c", f"sleep 2; touch {marker}" ], "keep": False } )
        call.reply()
        call.close()                    # the connection stays: as a remote shell's, through the hub
        time.sleep( 4 )
        assert not marker.exists(), "a command whose client went would wait forever"
        assert conn.ping()[ "ok" ]
        conn.close()


if test( "an agent with nothing to do goes, and takes its socket with it" ):
    agents = fresh()
    with scratch() as d:
        conn = agents.open( local( d, keep = 1 ) )
        conn.ping()
        conn.close()
        deadline = time.monotonic() + 15
        while ( Path( d ) / "sock" ).exists() and time.monotonic() < deadline:
            time.sleep( 0.2 )
        assert not ( Path( d ) / "sock" ).exists(), "the agent stayed"


def attached( d ):
    """An environment agent behind a layer it may not outlive ( apptainer ): a child of its bridge."""
    argv = [ sys.executable, "-m", "errand.agents", "connect", str( d ), "5", "attached" ]
    return { "kind": "cmd", "id": f"here:attached:{d}", "argv": argv, "keep_alive": 5 }


def gone( pid, within = 10 ):
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill( pid, 0 )
        except OSError:
            return True
        time.sleep( 0.1 )
    return False


if test( "an attached agent is its bridge's own, and goes with it, what it started too" ):
    agents = fresh()
    with scratch() as d:
        os.environ[ "PYTHONPATH" ] = os.pathsep.join( p for p in ( str( ROOT ), os.environ.get( "PYTHONPATH" ) ) if p )
        conn = agents.open( attached( d ) )
        pid = conn.ping()[ "pid" ]
        assert agents.shell( conn, "echo inside", capture = True ).stdout.strip() == "inside"
        agents.start( conn, [ "sh", "-c", f"echo $$ > {d}/kept; exec sleep 60" ] )
        deadline = time.monotonic() + 10
        while not ( Path( d ) / "kept" ).exists() and time.monotonic() < deadline:
            time.sleep( 0.05 )
        time.sleep( 0.1 )
        kept = int( ( Path( d ) / "kept" ).read_text() )
        agents._open.clear()
        other = agents.open( attached( d ) )
        assert other.ping()[ "pid" ] != pid, "another bridge reached the first one's agent: it would lose it"
        other.close()
        conn.close()
        assert gone( pid ), "the agent outlived its bridge"
        assert not list( Path( d ).glob( "attached-*" ) ), "an attached agent left its directory"
        assert gone( kept ), "what it started outlived it"


def wait_for( path, within = 10 ):
    deadline = time.monotonic() + within
    while not Path( path ).exists() and time.monotonic() < deadline:
        time.sleep( 0.05 )
    time.sleep( 0.1 )
    return int( Path( path ).read_text() )


def alive( pid ):
    try:
        os.kill( pid, 0 )
        return True
    except OSError:
        return False


if test( "an agent killed outright: the next one in its directory kills what it left running ( ADR 0008 )" ):
    import signal
    agents = fresh()
    with scratch() as d:
        conn = agents.open( local( d ) )
        agent = conn.ping()[ "pid" ]
        agents.start( conn, [ "sh", "-c", f"sleep 60 & echo $! > {d}/child; echo $$ > {d}/kept; wait" ] )
        kept, child = wait_for( f"{d}/kept" ), wait_for( f"{d}/child" )
        os.kill( agent, signal.SIGKILL )
        assert gone( agent )
        conn.close()
        assert alive( kept ) and alive( child ), "nothing kills it before the next agent"
        agents._open.clear()
        assert agents.open( local( d ) ).ping()[ "pid" ] != agent
        assert gone( kept, 15 ) and gone( child, 15 ), "an agent's processes outlived it and the next one"
        agents._open.clear()


if test( "a SIGTERM to an agent takes what it runs with it" ):
    import signal
    agents = fresh()
    with scratch() as d:
        conn = agents.open( local( d ) )
        agent = conn.ping()[ "pid" ]
        agents.start( conn, [ "sh", "-c", f"echo $$ > {d}/kept; exec sleep 60" ] )
        kept = wait_for( f"{d}/kept" )
        os.kill( agent, signal.SIGTERM )
        assert gone( kept, 15 ) and gone( agent, 15 ), "a logout or a kill left the work running, unowned"
        conn.close()
        agents._open.clear()


if test( "Ctrl-C stops what ignores it, and what it left in its group, with its client already gone" ):
    agents = fresh()
    with scratch() as d:
        conn = agents.open( local( d ) )
        stubborn = ( f"trap '' INT TERM; ( trap '' INT TERM; sleep 60 ) & echo $! > {d}/child; "
                     f"echo $$ > {d}/kept; while :; do sleep 0.1; done" )
        pid = agents.start( conn, [ "sh", "-c", stubborn ] )
        kept, child = wait_for( f"{d}/kept" ), wait_for( f"{d}/child" )
        agents.client.stop( agents.attach( conn, pid ) )
        time.sleep( 0.2 )
        conn.close()                    # errand exits right after Ctrl-C: the agent finishes the job
        agents._open.clear()
        assert gone( kept, 15 ), "a process that ignores SIGINT and SIGTERM was not stopped"
        assert gone( child, 15 ), "what it left in its group outlived the stop"


if test( "a process that ends by itself leaves what it meant to ( nohup … & )" ):
    agents = fresh()
    with scratch() as d:
        conn = agents.open( local( d ) )
        got = agents.shell( conn, f"nohup sleep 30 >/dev/null 2>&1 & echo $! > {d}/bg", capture = True )
        assert got.returncode == 0
        bg = wait_for( f"{d}/bg" )
        time.sleep( 0.5 )
        try:
            assert alive( bg ), "a batch submitted with nohup was killed with its submitter"
        finally:
            os.kill( bg, 9 )
        conn.close()
        agents._open.clear()


if test( "errand agents stop --force stops what runs before the agent goes" ):
    agents = fresh()
    with scratch() as d:
        conn = agents.open( local( d ) )
        agent = conn.ping()[ "pid" ]
        agents.start( conn, [ "sh", "-c", f"trap '' TERM; echo $$ > {d}/kept; while :; do sleep 0.1; done" ] )
        kept = wait_for( f"{d}/kept" )
        assert conn.open( { "op": "stop" } ).reply( 10 )[ "ok" ] is False, "stopped with work running, unforced"
        assert conn.open( { "op": "stop", "force": True } ).reply( 10 )[ "ok" ]
        assert gone( kept, 15 ) and gone( agent, 20 ), "forced: the agent went and left its work"
        conn.close()
        agents._open.clear()


if test( "a directory nobody serves, whatever its age: what still runs there is killed by a neighbour" ):
    import json, signal
    from errand.agents import endpoint, procs
    with scratch() as d:
        base = Path( d )
        for name in ( "me", "dead" ):
            ( base / name ).mkdir()
            ( base / name / "lock" ).touch()
        orphan = subprocess.Popen( [ "sleep", "60" ], start_new_session = True )
        mark = base / "dead" / "proc" / "x"
        mark.mkdir( parents = True )
        mark.joinpath( "meta.json" ).write_text( json.dumps( { "keep": True, "pgid": orphan.pid,
                                                               "since": procs.started( orphan.pid ) } ) )
        # a pid recorded with another start time is somebody else's now: left alone
        other = subprocess.Popen( [ "sleep", "60" ], start_new_session = True )
        ( base / "dead" / "proc" / "y" ).mkdir()
        ( base / "dead" / "proc" / "y" / "meta.json" ).write_text( json.dumps( { "keep": True, "pgid": other.pid,
                                                                                 "since": "another life" } ) )
        try:
            endpoint.sweep( base / "me" )
            assert orphan.wait( 10 ) == -signal.SIGTERM, "an orphan was left running"
            assert ( mark / "exit" ).read_text() == str( -signal.SIGKILL )
            assert other.poll() is None, "a pid reused by another process was killed"
            assert ( base / "dead" ).exists(), "recent: the directory itself stays"
        finally:
            for p in ( orphan, other ):
                if p.poll() is None:
                    p.kill()


HUB = """
import os, sys
sys.path.insert( 0, {root!r} )
os.environ[ "ERRAND_AGENT" ] = "hub"
from errand import agents
conn = agents.open( {{ "kind": "local", "dir": {d!r}, "keep_alive": 5 }} )
print( conn.ping()[ "pid" ], agents.shell( conn, "echo through-the-hub", capture = True ).stdout.strip() )
"""


if test( "through the hub: two commands, one agent, one stream" ):
    with scratch() as home, scratch() as d:
        env = { **os.environ, "HOME": home, "ERRAND_HUB_KEEP_ALIVE": "3" }
        seen = [ ]
        for _ in range( 2 ):
            got = subprocess.run( [ sys.executable, "-c", HUB.format( root = str( ROOT ), d = d ) ],
                                  capture_output = True, text = True, env = env, timeout = 60 )
            assert got.returncode == 0, got.stderr
            seen.append( got.stdout.split() )
        assert seen[ 0 ][ 1 ] == "through-the-hub" and seen[ 0 ] == seen[ 1 ], seen
        hubs = list( Path( home ).glob( ".cache/errand/hub-*" ) )
        assert len( hubs ) == 1 and ( hubs[ 0 ] / "sock" ).exists(), "the hub did not stay"


if test( "a bridge that never answers goes when the command that waited for it goes ( ADR 0009 )" ):
    with scratch() as home, scratch() as d:
        env = { **os.environ, "HOME": home, "ERRAND_HUB_KEEP_ALIVE": "30" }
        pid = Path( d ) / "pid"
        # an allocation still in Slurm's queue: the bridge says nothing, for long
        waiter = ( f"import os, sys\nsys.path.insert( 0, {str( ROOT )!r} )\nos.environ[ 'ERRAND_AGENT' ] = 'hub'\n"
                   f"from errand import agents\n"
                   f"agents.open( {{ 'kind': 'cmd', 'id': 'here:never', 'keep_alive': 5,"
                   f" 'argv': [ 'sh', '-c', 'echo $$ > {pid}; exec sleep 60' ] }} )\n" )
        client = subprocess.Popen( [ sys.executable, "-c", waiter ], env = env, stdout = subprocess.DEVNULL,
                                   stderr = subprocess.DEVNULL )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not ( pid.exists() and pid.read_text().strip() ):
            time.sleep( 0.1 )
        bridge = int( pid.read_text() )
        assert alive( bridge ), "the bridge did not start"
        client.kill()
        client.wait()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and alive( bridge ):
            time.sleep( 0.2 )
        assert not alive( bridge ), "the hub kept waiting for an agent nobody wants any more"


if test( "without a hub, a bridge goes with the command that owns it, stopped by a TERM ( ADR 0009 )" ):
    import signal
    with scratch() as d:
        pid = Path( d ) / "pid"
        waiter = ( f"import os, sys\nsys.path.insert( 0, {str( ROOT )!r} )\nos.environ[ 'ERRAND_AGENT' ] = 'direct'\n"
                   f"from errand import agents\n"
                   f"agents.open( {{ 'kind': 'cmd', 'id': 'here:never', 'keep_alive': 5,"
                   f" 'argv': [ 'sh', '-c', 'echo $$ > {pid}; exec sleep 60' ] }} )\n" )
        client = subprocess.Popen( [ sys.executable, "-c", waiter ], stdout = subprocess.DEVNULL,
                                   stderr = subprocess.DEVNULL )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not ( pid.exists() and pid.read_text().strip() ):
            time.sleep( 0.1 )
        bridge = int( pid.read_text() )
        client.send_signal( signal.SIGTERM )
        assert client.wait( timeout = 10 ) == -signal.SIGTERM, "it should still die of the TERM"
        assert gone( bridge ), "the bridge outlived the command that owned it"


if test( "a hub that goes takes its directory with it once its sources were replaced, not before" ):
    from errand.agents import hub as H, upstream as U
    with scratch() as d:
        old, current = Path( d ) / "hub-old", Path( d ) / "hub-current"
        kept = U.hub_dir
        U.hub_dir = lambda fresh = False: current
        try:
            for root in ( old, current ):
                assert H.Hub( root, 0.0 ).run() == 0, "nobody connected: it goes at once"
        finally:
            U.hub_dir = kept
        assert not old.exists(), "a hub nobody will reach again"
        assert ( current / "log" ).exists() or ( current / "lock" ).exists(), "the current one keeps its directory"


if test( "errand agents lists what the hub keeps, and stop takes it all down, the hub included" ):
    with scratch() as home, scratch() as d, scratch() as proj:
        ( Path( proj ) / "errand-project.py" ).write_text( "" )
        env = { **os.environ, "HOME": home, "ERRAND_HUB_KEEP_ALIVE": "60", "PYTHONPATH": str( ROOT ) }
        got = subprocess.run( [ sys.executable, "-c", HUB.format( root = str( ROOT ), d = d ).replace(
                                  '"keep_alive": 5', '"keep_alive": 60, "id": "here:test-agent"' ) ],
                              capture_output = True, text = True, env = env, timeout = 60 )
        assert got.returncode == 0, got.stderr

        def errand( *words ):
            return subprocess.run( [ sys.executable, "-m", "errand", *words ], cwd = proj, capture_output = True,
                                   text = True, env = env, timeout = 120 )

        listed = errand( "agents" )
        assert listed.returncode == 0 and "here:test-agent" in listed.stdout, listed.stdout + listed.stderr
        stopped = errand( "agents", "stop" )
        assert "here:test-agent: stopped" in stopped.stdout and "stopped" in stopped.stdout.split( "hub" )[ -1 ], \
            stopped.stdout + stopped.stderr
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and ( ( Path( d ) / "sock" ).exists() or
                                                 list( Path( home ).glob( ".cache/errand/hub-*/sock" ) ) ):
            time.sleep( 0.2 )
        assert not ( Path( d ) / "sock" ).exists(), "the agent stayed"
        assert not list( Path( home ).glob( ".cache/errand/hub-*/sock" ) ), "the hub stayed"
        assert "no hub running" in errand( "agents" ).stdout


if test( "agents stop finds every agent here by its directory, no hub needed: an older one terminated, a busy one left" ):
    agents = fresh()
    from errand.agents import stopping
    with scratch() as d:
        base = Path( d ) / "agents"
        names = ( "host-new-x", "env-old-y", "env-busy-z" )
        conns = { n: agents.open( local( base / n, keep = 60 ), noted = False ) for n in names }
        pids = { n: c.ping()[ "pid" ] for n, c in conns.items() }
        agents.start( conns[ "env-busy-z" ], [ "sh", "-c", f"echo $$ > {d}/busy; while :; do sleep 0.1; done" ] )
        work = wait_for( f"{d}/busy" )
        asked = agents.ask_hub

        def older( root, req, timeout = 30.0 ):        # an agent of sources older than `stop`: it does not answer it
            return None if req.get( "op" ) == "stop" and Path( root ).name == "env-old-y" else asked( root, req, timeout )
        agents.ask_hub = older
        try:
            said = { s[ "id" ]: s[ "how" ] for s in stopping.sweep( roots = [ Path( d ) ] ) }
        finally:
            agents.ask_hub = asked
        assert said == { "env-old-y": "stopped ( older sources: terminated )", "env-busy-z": "left: 1 running",
                         "host-new-x": "stopped" }, said
        assert gone( pids[ "host-new-x" ] ) and gone( pids[ "env-old-y" ] ) and not gone( pids[ "env-busy-z" ], 0.5 )
        assert list( stopping.sweep( roots = [ Path( d ) ], spare = base / "env-busy-z" ) ) == [ ], "the one doing it spared"
        said = { s[ "id" ]: s[ "how" ] for s in stopping.sweep( "busy", force = True, roots = [ Path( d ) ] ) }
        assert said == { "env-busy-z": "stopped" } and gone( pids[ "env-busy-z" ] ) and gone( work, 15 ), said
        for c in conns.values():
            c.close()
        agents._open.clear()


if test( "agents stop: one held by another node of a shared file system is not asked here, but there" ):
    agents = fresh()
    from errand.agents import stopping
    with scratch() as d:
        base = Path( d ) / "agents"
        conn = agents.open( local( base / "env-far-x", keep = 60 ), noted = False )
        pid = conn.ping()[ "pid" ]
        assert ( base / "env-far-x" / "host" ).read_text() == __import__( "socket" ).gethostname(), "it says where it runs"
        ( base / "env-far-x" / "host" ).write_text( "node-elsewhere" )
        hopped = [ ]
        kept = stopping._hop
        stopping._hop = lambda host, names, match, force: hopped.append( ( host, names ) ) or [ { "id": f"{host}: {n}", "how": "stopped" } for n in names ]
        try:
            said = stopping.sweep( roots = [ Path( d ) ] )
        finally:
            stopping._hop = kept
        assert hopped == [ ( "node-elsewhere", [ "env-far-x" ] ) ] and said == [ { "id": "node-elsewhere: env-far-x", "how": "stopped" } ], said
        assert not gone( pid, 0.5 ), "not asked here"
        assert stopping.sweep( roots = [ Path( d ) ], hop = False ) == [ { "id": "env-far-x", "how": "unreachable: held on node-elsewhere" } ]
        ( base / "env-far-x" / "host" ).unlink()
        assert stopping.sweep( roots = [ Path( d ) ] ) == [ { "id": "env-far-x", "how": "stopped" } ] and gone( pid )
        conn.close()
        agents._open.clear()


if test( "a remote shell's command is told apart from its options" ):
    from errand.agents.rsh import command_of
    assert command_of( [ "lmo", "sh", "-c", "true" ] ) == "sh -c true"
    assert command_of( [ "-l", "me", "-p", "22", "lmo", "python3", "-V" ] ) == "python3 -V"


if test( "a session's marks are read out of its output, however the output was cut" ):
    import io
    from errand.cli.sessions import Marked
    from errand.agents.ops import MARK
    s = Marked()
    shown = io.BytesIO()
    s._show = shown.write
    data = ( "before " + MARK + '{"op": "ran", "n": 1}\nafter\n' ).encode()
    for k in range( len( data ) ):                         # one byte at a time: every cut point there is
        s._out( data[ k : k + 1 ] )
    s._out( b"", end = True )
    assert shown.getvalue() == b"before after\n", shown.getvalue()
    assert s.marks.get_nowait() == { "op": "ran", "n": 1 }


if test( "attach with nothing left running says so" ):
    with scratch() as d:
        project = Path( d ) / "proj"
        project.mkdir()
        ( project / "errand-project.py" ).write_text( "" )
        got = subprocess.run( [ sys.executable, "-m", "errand", "attach" ], cwd = project, capture_output = True, text = True,
                              env = { **os.environ, "PYTHONPATH": str( ROOT ) }, timeout = 60 )
        assert got.returncode == 0 and "nothing left running" in got.stdout, got.stdout + got.stderr


if test( "a process can have a terminal: its size, a resize, and Ctrl-C as a key" ):
    agents = fresh()
    from errand.agents import frames as F
    prog = ( "import os, signal, sys, time; print( 'tty', sys.stdin.isatty(), os.get_terminal_size(), flush = True ); "
             "signal.signal( signal.SIGWINCH, lambda *a: print( 'now', os.get_terminal_size(), flush = True ) ); "
             "time.sleep( 30 )" )
    with scratch() as d:
        call = agents.open( local( d ) ).open( { "op": "spawn", "argv": [ sys.executable, "-c", prog ], "keep": False,
                                                 "tty": { "cols": 101, "rows": 33 } } )
        call.reply()
        out = b""

        def until( word ):
            global out
            end = time.monotonic() + 20
            while word not in out and time.monotonic() < end:
                kind, payload = call.next( 20 )
                out += payload if kind == F.OUT else b"[exit]" if kind == F.EXIT else b""

        until( b"columns=101, lines=33" )
        assert b"tty True" in out, out
        call.send( F.RESIZE, { "cols": 140, "rows": 50 } )
        until( b"columns=140, lines=50" )
        call.send( F.IN, b"\x03" )                         # what a terminal makes of it: SIGINT
        until( b"[exit]" )
        assert b"KeyboardInterrupt" in out and out.endswith( b"[exit]" ), out


if test( "a server that starts takes away what nobody serves any more beside it, and nothing else" ):
    from errand.agents import endpoint
    with scratch() as d:
        base = Path( d )
        for name in ( "me", "stale", "recent", "served", "session" ):
            ( base / name ).mkdir()
            ( base / name / "lock" ).touch()
        ( base / "not-ours" ).mkdir()                       # no lock: not an agent's
        # a session somebody may still attach to: finished two hours ago, its output kept
        ( base / "session" / "proc" / "x" ).mkdir( parents = True )
        ( base / "session" / "proc" / "x" / "meta.json" ).write_text( '{"keep": true}' )
        ( base / "session" / "proc" / "x" / "exit" ).write_text( "0" )
        old = time.time() - 7200
        for name in ( "stale", "served", "not-ours", "session" ):
            for p in ( base / name, *( base / name ).rglob( "*" ) ):
                os.utime( p, ( old, old ) )
        held = endpoint.hold( base / "served" / "lock" )    # somebody serves it
        try:
            endpoint.sweep( base / "me" )
        finally:
            held.close()
        assert sorted( p.name for p in base.iterdir() ) == [ "me", "not-ours", "recent", "served", "session" ]


if test( "a socket whose path is too long for the platform is reached through a short link" ):
    import threading
    from errand.agents import endpoint
    if endpoint.UNIX:
        with tempfile.TemporaryDirectory() as tmp:
            deep = Path( tmp ) / ( "a-directory-with-a-long-name-" * 4 ) / "hub"
            deep.mkdir( parents = True )
            assert len( str( deep / "sock" ) ) > 110
            server, accept = endpoint.listen( deep )
            try:
                assert ( deep / "sock" ).exists(), "the socket is in its directory, not in the link's"
                t = threading.Thread( target = lambda: accept().sendall( b"hi" ) )
                t.start()
                s = endpoint.reach( deep )
                assert s is not None
                assert s.recv( 2 ) == b"hi"
                s.close()
                t.join()
            finally:
                server.close()


if test( "what a process leaves its owner to do on a stop is done: by its agent, and by the next one for an orphan" ):
    import signal
    agents = fresh()
    with scratch() as d:
        # a stand-in scancel, which says it was called, on the PATH of what the agent starts
        ( Path( d ) / "bin" ).mkdir()
        ( Path( d ) / "bin" / "scancel" ).write_text( f'#!/bin/sh\necho "$@" >> {d}/cancelled; echo cancel >> {d}/order\n' )
        ( Path( d ) / "bin" / "scancel" ).chmod( 0o755 )
        ( Path( d ) / "bin" / "srun" ).write_text( f"#!/bin/sh\ntrap 'echo int >> {d}/order; exit 130' INT\n"
                                                   f"echo $$ > {d}/srun; while :; do sleep 0.1; done\n" )
        ( Path( d ) / "bin" / "srun" ).chmod( 0o755 )
        env = { "PATH": f"{d}/bin:{os.environ[ 'PATH' ]}" }
        # a process that registers its cancel with its owner ( ADR 0009 ), then waits
        name = "errand-test"
        line = [ "sh", "-c", f'echo "$(command -v scancel) --name={name}" > "$ERRAND_PROC_DIR/cancel"; exec srun' ]
        conn = agents.open( local( Path( d ) / "a" ) )
        pid = agents.start( conn, line, env = env )
        srun = wait_for( f"{d}/srun" )
        agents.client.stop( agents.attach( conn, pid ) )
        assert gone( srun, 15 )
        deadline = time.monotonic() + 10
        while not Path( f"{d}/cancelled" ).exists() and time.monotonic() < deadline:
            time.sleep( 0.05 )
        assert f"--name={name}" in Path( f"{d}/cancelled" ).read_text(), "the job was not cancelled by name"
        assert Path( f"{d}/order" ).read_text().split() == [ "int", "cancel" ], \
            "cancelled before srun had its Ctrl-C: the job's own clean-up was cut short"
        # an orphan: its agent killed outright, the next one cancels its job
        Path( f"{d}/cancelled" ).unlink()
        Path( f"{d}/srun" ).unlink()
        agent = conn.ping()[ "pid" ]
        agents.start( conn, line, env = env )
        srun = wait_for( f"{d}/srun" )
        os.kill( agent, signal.SIGKILL )
        assert gone( agent )
        conn.close()
        agents._open.clear()
        agents.open( local( Path( d ) / "a" ) ).ping()
        assert gone( srun, 15 )
        assert Path( f"{d}/cancelled" ).exists(), "the next agent killed the orphan but left its job"
        agents._open.clear()


if test( "a process that ends before its client is attached still gives its output" ):
    # `spawn` replies, then attaches: a quick process may be over in between, and its output must wait for
    # the attach rather than go with its directory.
    import socket
    import subprocess
    import sys
    import tempfile
    import threading
    import time
    from pathlib import Path
    from errand.agents import client as C, endpoint
    with tempfile.TemporaryDirectory( dir = "/tmp" ) as tmp:
        d = Path( tmp ) / "a"
        here = str( Path( __file__ ).resolve().parent.parent )
        subprocess.run( [ sys.executable, "-c", f"from pathlib import Path; from errand.agents import daemon; daemon.start( Path( {str( d )!r} ), 10 )" ],
                        env = { **os.environ, "PYTHONPATH": here }, check = True )
        deadline = time.monotonic() + 10
        while endpoint.reach( d ) is None:
            assert time.monotonic() < deadline, "no agent"
            time.sleep( 0.05 )
        bad = [ ]

        def one():
            s = endpoint.reach( d )
            conn = C.Connection( s.recv, s.sendall, lambda: s.shutdown( socket.SHUT_RDWR ) )
            for _ in range( 15 ):
                got = C.shell( conn, "echo out; exit 3", capture = True )
                if ( got.stdout, got.returncode ) != ( "out\n", 3 ):
                    bad.append( ( got.stdout, got.returncode ) )

        threads = [ threading.Thread( target = one ) for _ in range( 12 ) ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not bad, f"{len( bad )} of 180 came back without their output: {bad[ : 3 ]}"
