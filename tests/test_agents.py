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
        call.close()                    # the connection stays: as rsync's remote shell, through the hub
        time.sleep( 4 )
        assert not marker.exists(), "an rsync --server whose client went would wait forever"
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


if test( "rsync's remote shell is told apart from its options" ):
    from errand.agents.rsh import command_of
    assert command_of( [ "lmo", "rsync", "--server", "-a", "." ] ) == "rsync --server -a ."
    assert command_of( [ "-l", "me", "-p", "22", "lmo", "rsync", "--server" ] ) == "rsync --server"


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
