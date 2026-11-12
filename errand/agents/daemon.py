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
import socket
import sys
import threading
import time
from pathlib import Path


WAIT = 15.0          # seconds a bridge waits for the agent it started to answer


def reach( root: Path ) -> socket.socket | None:
    s = socket.socket( socket.AF_UNIX, socket.SOCK_STREAM )
    try:
        s.connect( str( root / "sock" ) )
        return s
    except OSError:
        s.close()
        return None


def start( root: Path, keep_alive: float, what = "agent" ):
    """The agent -- or the hub -- detached from whoever asked: double fork, new session, stdio to a log."""
    root.mkdir( parents = True, exist_ok = True )
    if os.fork():
        return
    os.setsid()
    if os.fork():
        os._exit( 0 )
    log = os.open( str( root / "log" ), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600 )
    null = os.open( os.devnull, os.O_RDONLY )
    os.dup2( null, 0 )
    os.dup2( log, 1 )
    os.dup2( log, 2 )
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


def connect( root: Path, keep_alive: float ) -> int:
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


def bridge( sock: socket.socket ) -> int:
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
