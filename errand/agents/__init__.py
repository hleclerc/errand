"""Agents: processes that stay where the work is, and a hub here that keeps the way to them open ( ADR 0005 ).

    frames     the protocol: frames multiplexed over any byte stream
    procs      the processes an agent starts: output on disk, streamed to whoever listens
    agent      the agent: a unix socket, clients that come and go, processes that stay
    daemon     starting an agent ( or the hub ) detached, and the `connect` bridge to it
    client     a connection, its channels, and `shell`
    upstream   which command reaches an agent, for a target ( ssh, this machine )
    hub        the process here that keeps streams open between commands

`open( target )` is the way in. How it gets there is `ERRAND_AGENT`:

    hub      through the hub, started if need be ( the default on a terminal )
    direct   a stream owned by this process, closed with it ( the default without a terminal )
    off      no agent: `Over.shell` opens an ssh per command, as before
"""
from __future__ import annotations

import os
import sys
import threading
import time

from . import frames as F, upstream as U
from .client import attach, Call, Connection, interact, Lost, shell, start


_open : dict = { }
_lock = threading.Lock()


def mode( ) -> str:
    chosen = os.environ.get( "ERRAND_AGENT", "" ).strip().lower()
    if chosen in ( "0", "off", "no" ):
        return "off"
    if chosen in ( "hub", "direct" ):
        return chosen
    try:
        tty = sys.stdin.isatty() and sys.stdout.isatty()
    except ( AttributeError, ValueError ):
        tty = False
    return "hub" if tty else "direct"


def enabled( ) -> bool:
    return mode() != "off"


def open( target: dict ) -> Connection:
    """A connection to the agent `target` names: reused while it lives."""
    key = U.identity( target )
    with _lock:
        conn = _open.get( key )
        if conn is None or not conn.alive:
            conn = _open[ key ] = _through_hub( target ) if mode() == "hub" else U.direct( target )
        return conn


def _through_hub( target: dict ) -> Connection:
    import socket
    from . import daemon
    root = U.hub_dir()
    sock = daemon.reach( root )
    if sock is None:
        daemon.start( root, float( os.environ.get( "ERRAND_HUB_KEEP_ALIVE" ) or U.KEEP_ALIVE ), what = "hub" )
        deadline = time.monotonic() + daemon.WAIT
        while sock is None and time.monotonic() < deadline:
            time.sleep( 0.05 )
            sock = daemon.reach( root )
        if sock is None:
            # No hub to be had: this process holds the stream itself.
            return U.direct( target )
    conn = Connection( sock.recv, sock.sendall, lambda: sock.shutdown( socket.SHUT_RDWR ) )
    route = conn.calls[ 0 ] = Call( conn, 0 )
    conn.writer.send( 0, F.OPEN, { "op": "route", "target": target } )
    try:
        route.reply( timeout = 120 )
    finally:
        conn.forget( 0 )
    return conn


__all__ = [ "attach", "Call", "Connection", "enabled", "interact", "Lost", "mode", "open", "shell", "start" ]


def ask_hub( root, request: dict, timeout = 30.0 ):
    """A request to the hub serving in `root` itself ( `streams`, `stop` ): its reply, None if none serves there."""
    import socket
    from . import daemon
    sock = daemon.reach( root )
    if sock is None:
        return None
    conn = Connection( sock.recv, sock.sendall, lambda: sock.shutdown( socket.SHUT_RDWR ) )
    call = conn.calls[ 0 ] = Call( conn, 0 )
    try:
        conn.writer.send( 0, F.OPEN, request )
        return call.reply( timeout = timeout )
    except ( Lost, TimeoutError, RuntimeError, OSError ):
        return None
    finally:
        try:
            conn.close()
        except OSError:
            pass
