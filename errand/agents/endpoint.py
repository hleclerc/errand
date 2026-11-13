"""Where an agent ( or the hub ) listens, and how a client reaches it, on this platform.

A unix socket, `<dir>/sock`, where there are unix sockets. On Windows, a TCP
port on 127.0.0.1, written with a random token in `<dir>/sock`: a client reads
both and says the token first, so another user's process on the same machine
cannot speak to the agent by guessing its port.

And the lock that makes an agent the only one of its directory, both ways.
"""
from __future__ import annotations

import os
import secrets
import socket
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"
UNIX = hasattr( socket, "AF_UNIX" ) and not WINDOWS


def listen( root: Path ):
    """-> ( server socket, accept( ) -> connection or None ), the socket's file written."""
    path = root / "sock"
    if path.exists():
        path.unlink()
    if UNIX:
        server = socket.socket( socket.AF_UNIX, socket.SOCK_STREAM )
        server.bind( str( path ) )
        os.chmod( path, 0o600 )
        server.listen( 16 )
        return server, lambda: server.accept()[ 0 ]
    token = secrets.token_hex( 16 )
    server = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
    server.bind( ( "127.0.0.1", 0 ) )
    server.listen( 16 )
    path.write_text( f"tcp {server.getsockname()[ 1 ]} {token}\n" )

    def accept():
        conn = server.accept()[ 0 ]
        conn.settimeout( 10 )
        try:
            said = b""
            while not said.endswith( b"\n" ) and len( said ) < 100:
                got = conn.recv( 1 )
                if not got:
                    break
                said += got
        except OSError:
            said = b""
        if said.strip().decode( errors = "replace" ) != token:
            conn.close()
            return None
        conn.settimeout( None )
        return conn

    return server, accept


def reach( root: Path ) -> socket.socket | None:
    path = root / "sock"
    try:
        if UNIX:
            s = socket.socket( socket.AF_UNIX, socket.SOCK_STREAM )
            try:
                s.connect( str( path ) )
            except OSError:
                s.close()
                raise
            return s
        kind, port, token = path.read_text().split()
        s = socket.create_connection( ( "127.0.0.1", int( port ) ), timeout = 10 )
        s.sendall( token.encode() + b"\n" )
        s.settimeout( None )
        return s
    except ( OSError, ValueError ):
        return None


def hold( path: Path ):
    """The lock of `path`, held for as long as the returned file is open; None if somebody holds it."""
    handle = open( path, "a+" )
    try:
        if WINDOWS:
            import msvcrt
            handle.seek( 0 )
            msvcrt.locking( handle.fileno(), msvcrt.LK_NBLCK, 1 )
        else:
            import fcntl
            fcntl.flock( handle, fcntl.LOCK_EX | fcntl.LOCK_NB )
        return handle
    except OSError:
        handle.close()
        return None


def serve( root: Path, idle, client, closing = None ) -> int:
    """Listen in `root` until `idle()` says to stop, each connection handed to `client( conn )`
    on a thread of its own. One server per directory: another one there means it answers."""
    import threading

    root.mkdir( parents = True, exist_ok = True )
    held = hold( root / "lock" )
    if held is None:
        return 0
    sweep( root )
    server, accept = listen( root )
    server.settimeout( 1.0 )
    try:
        while not idle():
            try:
                conn = accept()
            except socket.timeout:
                continue
            if conn is None:
                continue
            conn.settimeout( None )
            client( conn, threading )
    finally:
        server.close()
        path = root / "sock"
        if path.exists():
            path.unlink()
        if closing is not None:
            closing()
        held.close()
    return 0


def sweep( root: Path, older = 3600.0 ):
    """The directories beside this one that nobody serves any more -- an agent or a hub of sources
    since replaced -- untouched for an hour, and whose lock is free: they go. Not one that holds a
    session somebody may still attach to."""
    import shutil
    import time
    now = time.time()
    for d in root.parent.iterdir() if root.parent.is_dir() else [ ]:
        if d == root or not d.is_dir() or not ( d / "lock" ).exists():
            continue
        try:
            if now - max( p.stat().st_mtime for p in [ d, *d.iterdir() ] ) < older:
                continue
        except ( OSError, ValueError ):
            continue
        if _attachable( d, now ):
            continue                           # a session `errand attach` may still come back for
        free = hold( d / "lock" )
        if free is None:
            continue                       # somebody serves it
        free.close()
        shutil.rmtree( d, ignore_errors = True )


def _attachable( d: Path, now: float ) -> bool:
    """A session kept for its client ( `keep` ), unfinished or finished less than a week ago: its
    output is what `errand attach` replays, and it goes when the agent's own sweep says so."""
    import json
    from .procs import KEEP_DAYS
    for p in ( d / "proc" ).iterdir() if ( d / "proc" ).is_dir() else [ ]:
        try:
            if not json.loads( ( p / "meta.json" ).read_text() ).get( "keep" ):
                continue
            done = p / "exit"
            if not done.exists() or now - done.stat().st_mtime < KEEP_DAYS * 86400:
                return True
        except ( OSError, ValueError ):
            continue
    return False
