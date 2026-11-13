"""The client's side of a connection: channels opened on it, and `shell`, the one call most of errand needs.

A `Connection` reads frames on a thread of its own and hands each to the
channel it belongs to; a `Call` is one channel: its reply, then the frames that
follow until EXIT. `shell( line )` is what `Over.shell` used to do with a fresh
ssh each time -- the same contract, `subprocess.CompletedProcess` and all.
"""
from __future__ import annotations

import queue
import signal
import subprocess
import sys
import threading
import time

from . import frames as F


MARKER = b"\x00errand-agent-1\n"      # what a bridge says before the first frame


class Lost( ConnectionError ):
    """The connection went away while a call was waiting on it."""


class Call:
    def __init__( self, conn: "Connection", channel: int ):
        self.conn, self.channel = conn, channel
        self.events = queue.Queue()     # ( type, payload ); ( None, None ) when the connection is gone

    def reply( self, timeout = 60.0 ) -> dict:
        kind, payload = self.next( timeout )
        if kind != F.REPLY:
            raise Lost( "no reply from the agent" )
        got = F.load( payload )
        if "error" in got:
            raise RuntimeError( f"agent: {got[ 'error' ]}" )
        return got

    def next( self, timeout = None ):
        try:
            kind, payload = self.events.get( timeout = timeout )
        except queue.Empty:
            raise TimeoutError from None
        if kind is None:
            raise Lost( "the connection to the agent was lost" )
        return kind, payload

    def send( self, kind, payload = b"" ):
        self.conn.writer.send( self.channel, kind, payload )

    def close( self ):
        try:
            self.send( F.CLOSE )
        except OSError:
            pass
        self.conn.forget( self.channel )


class Connection:
    def __init__( self, read, write, close = None, marker = False ):
        self.read, self.writer, self._close = read, F.Writer( write ), close
        self.calls : dict = { }
        self.lock  = threading.Lock()
        self.next_channel = 1
        self.alive = True
        if marker:
            self._skip_to_marker()
        threading.Thread( target = self._pump, daemon = True ).start()

    def _skip_to_marker( self ):
        # A login shell may say things before the bridge starts: they are not frames.
        seen = b""
        while not seen.endswith( MARKER ):
            got = self.read( 1 )
            if not got:
                raise Lost( "the bridge to the agent did not start: " + seen.decode( errors = "replace" )[ -500 : ] )
            seen = ( seen + got )[ -4096 : ]

    def _pump( self ):
        try:
            while True:
                channel, kind, payload = F.read_frame( self.read )
                call = self.calls.get( channel )
                if call is not None:
                    call.events.put( ( kind, payload ) )
        except ( F.Broken, OSError, ValueError ):
            pass
        self.alive = False
        for call in list( self.calls.values() ):
            call.events.put( ( None, None ) )

    def open( self, request: dict ) -> Call:
        if not self.alive:
            raise Lost( "the connection to the agent is closed" )
        with self.lock:
            channel = self.next_channel
            self.next_channel += 1
            call = self.calls[ channel ] = Call( self, channel )
        self.writer.send( channel, F.OPEN, request )
        return call

    def forget( self, channel ):
        self.calls.pop( channel, None )

    def ping( self, timeout = 30.0 ) -> dict:
        call = self.open( { "op": "ping" } )
        try:
            return call.reply( timeout )
        finally:
            call.close()

    def close( self ):
        if self._close:
            self._close()


GRACE = ( 2.0, 5.0 )        # seconds after Ctrl-C at which SIGTERM, then SIGKILL, follow SIGINT


def stop( call: Call ):
    """Ctrl-C, over there: SIGINT to the process and all it started ( its process group ), then
    SIGTERM, then SIGKILL, for whatever is still alive -- a Python that catches KeyboardInterrupt
    and goes on, a program that ignores SIGINT. What errand started is stopped, not asked."""
    import threading

    def send( sig ):
        try:
            call.send( F.SIGNAL, { "sig": int( sig ) } )
        except OSError:
            pass

    send( signal.SIGINT )
    for after, sig in zip( GRACE, ( signal.SIGTERM, signal.SIGKILL ) ):
        t = threading.Timer( after, send, args = ( sig, ) )
        t.daemon = True
        t.start()


def shell( conn: Connection, line: str, *, cwd = None, quiet = False, capture = False, input = None,
           timeout = None, env = None, login = False ) -> subprocess.CompletedProcess:
    """`sh -c line` where the agent is: Over.shell's contract, over a connection already open.

    `login`: through the user's own interactive shell, `$SHELL -ic line`, which is
    what defines `module` or a `micromamba` shell function where they are functions."""
    argv = ( [ "sh", "-c", 'exec "${SHELL:-/bin/sh}" -ic "$1"', "sh", line ] if login else [ "sh", "-c", line ] )
    call = conn.open( { "op": "spawn", "argv": argv, "cwd": cwd, "env": env, "keep": False } )
    call.reply()
    if input is not None:
        call.send( F.IN, input.encode() if isinstance( input, str ) else input )
    call.send( F.EOF )
    out, err = bytearray(), bytearray()
    deadline = time.monotonic() + timeout if timeout else None
    interrupted = 0
    try:
        while True:
            try:
                left = None if deadline is None else max( 0.0, deadline - time.monotonic() )
                kind, payload = call.next( left )
            except TimeoutError:
                call.send( F.SIGNAL, { "sig": signal.SIGKILL } )
                raise subprocess.TimeoutExpired( line, timeout ) from None
            except KeyboardInterrupt:
                # Ctrl-C stops what runs over there ( `stop` ), and this waits for it to be gone.
                if not interrupted:
                    stop( call )
                interrupted += 1
                continue
            if kind == F.EXIT:
                code = int( F.load( payload ).get( "code", -1 ) )
                break
            if kind in ( F.OUT, F.ERR ):
                if capture:
                    ( out if kind == F.OUT else err ).extend( payload )
                elif not quiet:
                    stream = sys.stdout if kind == F.OUT else sys.stderr
                    stream.flush()
                    stream.buffer.write( payload )
                    stream.buffer.flush()
    finally:
        conn.forget( call.channel )
    if interrupted:
        raise KeyboardInterrupt
    text = capture or input is not None and not isinstance( input, bytes )
    decode = ( lambda b: b.decode( errors = "replace" ) ) if text else bytes
    return subprocess.CompletedProcess( [ "sh", "-c", line ], code,
                                        decode( out ) if capture else None, decode( err ) if capture else None )


def start( conn: Connection, argv, *, cwd = None, env = None, store = None ) -> str:
    """A process that outlives this connection: -> its id, to `attach` to later, from anywhere.
    Its output is kept in `store` over there ( the project's ), not in the agent's directory."""
    call = conn.open( { "op": "spawn", "argv": list( argv ), "cwd": cwd, "env": env, "keep": True, "store": store } )
    pid = call.reply()[ "id" ]
    call.send( F.EOF )
    call.close()
    return pid


def attach( conn: Connection, pid: str, out = 0, err = 0, store = None ) -> Call:
    """Follow a process from these offsets: its OUT / ERR frames, then EXIT."""
    call = conn.open( { "op": "attach", "id": pid, "out": out, "err": err, "store": store } )
    call.reply()
    return call


def interact( conn: Connection, argv, *, cwd = None, env = None ) -> int:
    """`argv` over there with a terminal, this one: keys go as they are typed, the screen comes
    back as it is drawn, a resize follows. Ctrl-C is a key like the others: the terminal over
    there turns it into SIGINT for what has the foreground. -> its exit code."""
    import os
    import shutil
    import sys

    size = shutil.get_terminal_size()
    tty = { "cols": size.columns, "rows": size.lines, "term": os.environ.get( "TERM" ) }
    call = conn.open( { "op": "spawn", "argv": list( argv ), "cwd": cwd, "env": env, "keep": False, "tty": tty } )
    call.reply()
    fd = sys.stdin.fileno()
    raw = sys.stdin.isatty()
    if raw:
        import termios
        import tty as ttys
        kept = termios.tcgetattr( fd )
        ttys.setraw( fd )

        def resized( *_ ):
            s = shutil.get_terminal_size()
            try:
                call.send( F.RESIZE, { "cols": s.columns, "rows": s.lines } )
            except OSError:
                pass

        was = signal.signal( signal.SIGWINCH, resized )

    def keys():
        try:
            for chunk in iter( lambda: os.read( fd, 1024 ), b"" ):
                call.send( F.IN, chunk )
        except OSError:
            pass
        if not raw:
            call.send( F.EOF )

    threading.Thread( target = keys, daemon = True ).start()
    code = -1
    try:
        while True:
            kind, payload = call.next()
            if kind in ( F.OUT, F.ERR ):
                view = memoryview( payload )
                while view:
                    view = view[ os.write( 1, view ) : ]
            elif kind == F.EXIT:
                code = int( F.load( payload ).get( "code", -1 ) )
                break
    finally:
        conn.forget( call.channel )
        if raw:
            termios.tcsetattr( fd, termios.TCSADRAIN, kept )
            signal.signal( signal.SIGWINCH, was )
    return code
