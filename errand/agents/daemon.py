"""Starting an agent as a daemon, and the `connect` bridge that reaches it.

What a layer gives is a byte stream -- ssh's stdio, a container's. An agent must
not die with it, so the stream does not reach the agent itself: it reaches

    python <errand> -m errand.agents connect <dir> <keep_alive>

which starts the agent in `<dir>` if none answers there ( detached: a session of
its own, its output in `<dir>/log` ), then copies bytes between its stdio and
the agent's socket until either side closes. The bridge dies with the stream;
the agent does not notice.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path


WAIT = 15.0          # seconds a bridge waits for the agent it started to answer


def reach( root: Path ):
    from .endpoint import reach as at
    return at( root )


def start( root: Path, keep_alive: float, what = "agent" ):
    """The agent -- or the hub -- detached from whoever asked: double fork, new session, stdio to a log.
    On Windows, a process of its own, out of the console and of the job of whoever started it."""
    root.mkdir( parents = True, exist_ok = True )
    if sys.platform == "win32":
        return _start_windows( root, keep_alive, what )
    if os.fork():
        return
    os.setsid()
    if os.fork():
        os._exit( 0 )
    _stdio_to( root / "log" )
    try:
        if what == "hub":
            from .hub import Hub
            code = Hub( root, keep_alive ).run()
        else:
            from .agent import Agent
            code = Agent( root, keep_alive ).run()
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    os._exit( code )


def _stdio_to( log_path: Path, keep = None ):
    """Stdin from nothing, stdout and stderr to `log_path`, and no other descriptor of whoever started
    it: a pipe it kept open would never close for them -- rsync, whose remote shell started the hub,
    waits for its end of the stream forever."""
    log = os.open( str( log_path ), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600 )
    null = os.open( os.devnull, os.O_RDONLY )
    os.dup2( null, 0 )
    os.dup2( log, 1 )
    os.dup2( log, 2 )
    top = min( os.sysconf( "SC_OPEN_MAX" ), 65536 ) if hasattr( os, "sysconf" ) else 1024
    if keep is None:
        os.closerange( 3, top )
    else:
        os.closerange( 3, keep )
        os.closerange( keep + 1, top )


def _start_windows( root: Path, keep_alive: float, what ):
    import subprocess
    # Not CREATE_NEW_PROCESS_GROUP: that disables Ctrl-C for the group AND what it starts, which a
    # terminal the agent opens ( `conpty` ) would then never deliver.
    flags = subprocess.DETACHED_PROCESS | getattr( subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000 )
    argv = [ sys.executable, "-m", "errand.agents", "hub" if what == "hub" else "serve", str( root ), str( keep_alive ) ]
    with open( root / "log", "ab" ) as log:
        try:
            subprocess.Popen( argv, stdin = subprocess.DEVNULL, stdout = log, stderr = log, close_fds = True,
                              creationflags = flags )
        except OSError:
            # a job that does not let its processes leave it: the agent lives as long as the job
            subprocess.Popen( argv, stdin = subprocess.DEVNULL, stdout = log, stderr = log, close_fds = True,
                              creationflags = flags & ~0x01000000 )


def connect( root: Path, keep_alive: float, attached = False ) -> int:
    if attached:
        return _attached( root, keep_alive )
    sock = reach( root )
    if sock is None:
        start( root, keep_alive )
        deadline = time.monotonic() + WAIT
        while sock is None and time.monotonic() < deadline:
            time.sleep( 0.05 )
            sock = reach( root )
        if sock is None:
            tail = ( root / "log" ).read_text( errors = "replace" )[ -2000 : ] if ( root / "log" ).exists() else ""
            print( f"errand: the agent in {root} did not start\n{tail}", file = sys.stderr )
            return 1
    return bridge( sock )


STALE = 60.0         # seconds after which the directory of an attached agent with no socket is a leftover


def _attached( root: Path, keep_alive: float ) -> int:
    """The agent as a child of this bridge, gone with it: for a layer whose surroundings end with the
    command that entered them ( `Layer.agent_may_detach` ) -- an image mounted for as long as
    `apptainer exec` runs. Kept between commands as long as the stream is: a hub's is.

    One per bridge, in a directory of its own: another bridge reaching it would lose it with this one."""
    import shutil
    import signal
    root.mkdir( parents = True, exist_ok = True )
    now = time.time()
    for old in root.glob( "attached-*" ):           # a bridge that was killed leaves its directory
        try:
            if now - old.stat().st_mtime > STALE and reach( old ) is None:
                shutil.rmtree( old, ignore_errors = True )
        except OSError:
            pass
    own = root / f"attached-{os.getpid()}"
    own.mkdir( parents = True, exist_ok = True )
    # The child watches the read end: the bridge gone, however it went ( a SIGTERM, a SIGKILL ),
    # its end of the pipe closes, and the agent goes too.
    watch, held = os.pipe()
    child = os.fork()
    if child == 0:
        _stdio_to( own / "log", keep = watch )
        code = 1
        try:
            from .agent import Agent
            agent = Agent( own, keep_alive )

            def end( *_ ):
                # what it started ( sessions of their own ) would run on in surroundings that are gone
                agent.terminate()
                shutil.rmtree( own, ignore_errors = True )
                os._exit( 0 )

            def orphan():
                try:
                    os.read( watch, 1 )
                finally:
                    end()

            signal.signal( signal.SIGTERM, end )
            threading.Thread( target = orphan, daemon = True ).start()
            code = agent.run()
        except BaseException:
            import traceback
            traceback.print_exc()
        os._exit( code )
    os.close( watch )

    once = threading.Lock()

    def gone():                    # from the bridge's end or its reader's, once
        if not once.acquire( blocking = False ):
            return
        try:
            os.kill( child, signal.SIGTERM )
            os.waitpid( child, 0 )
        except OSError:
            pass
        shutil.rmtree( own, ignore_errors = True )

    deadline = time.monotonic() + WAIT
    sock = reach( own )
    while sock is None and time.monotonic() < deadline and os.waitpid( child, os.WNOHANG ) == ( 0, 0 ):
        time.sleep( 0.05 )
        sock = reach( own )
    if sock is None:
        tail = ( own / "log" ).read_text( errors = "replace" )[ -2000 : ] if ( own / "log" ).exists() else ""
        print( f"errand: the agent in {own} did not start\n{tail}", file = sys.stderr )
        gone()
        return 1
    try:
        return bridge( sock, gone )
    finally:
        gone()


def bridge( sock, gone = None ) -> int:
    from .client import MARKER
    stdin, stdout = sys.stdin.buffer.raw, sys.stdout.buffer.raw
    stdout.write( MARKER )             # what came before this was a login shell talking

    def down():                        # agent -> stdout
        try:
            for chunk in iter( lambda: sock.recv( 65536 ), b"" ):
                view = memoryview( chunk )
                while view:
                    view = view[ stdout.write( view ) : ]
        except OSError:
            pass
        if gone is not None:
            gone()
        os._exit( 0 )

    threading.Thread( target = down, daemon = True ).start()
    try:
        for chunk in iter( lambda: os.read( stdin.fileno(), 65536 ), b"" ):
            sock.sendall( chunk )
    except OSError:
        pass
    # The stream is gone: the agent learns it from the closed socket, and lets go
    # of what may not outlive its client.
    sock.close()
    return 0
