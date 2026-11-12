"""Starting a process for an agent, the way this platform allows: pipes, or a terminal.

    start( argv, env, cwd, tty ) -> Child

A `Child` has its output streams ( `streams`: ( read( n ), name ) ), and can be
written to, have its input closed, be resized ( a terminal ), be signalled --
it AND everything it started, its process group -- and waited for.

With `tty = { "cols", "rows" }` it gets a terminal: a pty here ( POSIX ), a
pseudo-console on Windows ( `conpty.py` ). One stream then carries everything,
as a terminal does, and Ctrl-C is a byte the terminal turns into SIGINT.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys

WINDOWS = sys.platform == "win32"


class Child:
    def __init__( self, popen, streams, write, close_input, resize = None, master = None ):
        self.popen, self.streams = popen, streams
        self._write, self._close_input, self._resize = write, close_input, resize
        self.master = master

    @property
    def pid( self ):
        return self.popen.pid

    def write( self, data: bytes ):
        try:
            self._write( data )
        except ( BrokenPipeError, OSError, ValueError ):
            pass

    def close_input( self ):
        try:
            self._close_input()
        except OSError:
            pass

    def resize( self, cols: int, rows: int ):
        if self._resize is not None:
            try:
                self._resize( int( cols ), int( rows ) )
            except OSError:
                pass

    def signal( self, sig: int ):
        """To the whole group: what it started goes with it."""
        if WINDOWS:
            if sig in ( signal.SIGINT, getattr( signal, "CTRL_BREAK_EVENT", -1 ) ):
                try:
                    self.popen.send_signal( signal.CTRL_BREAK_EVENT )
                    return
                except OSError:
                    pass
            # nothing gentler that reaches a tree: the tree, at once
            subprocess.run( [ "taskkill", "/T", "/F", "/PID", str( self.popen.pid ) ],
                            stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL )
            return
        try:
            os.killpg( self.popen.pid, sig )
        except ( ProcessLookupError, PermissionError ):
            pass

    def wait( self ) -> int:
        code = self.popen.wait()
        if self.master is not None:
            self.master.closed_by_wait()
        return code


def _reader( fd ):
    def read( n ):
        try:
            return os.read( fd, n )
        except OSError:          # a pty whose other side is closed: that is its end
            return b""
    return read


def start( argv, env = None, cwd = None, tty = None ) -> Child:
    full_env = { **os.environ, **( env or { } ) }
    if tty:
        if WINDOWS:
            try:
                from .conpty import start as console
                return console( argv, full_env, cwd, tty )
            except OSError:
                pass                     # no pseudo-console here: pipes, without a terminal
        else:
            return _pty( argv, full_env, cwd, tty )
    if WINDOWS:
        popen = subprocess.Popen( list( argv ), cwd = cwd or None, env = full_env,
                                  stdin = subprocess.PIPE, stdout = subprocess.PIPE, stderr = subprocess.PIPE,
                                  creationflags = subprocess.CREATE_NEW_PROCESS_GROUP )
    else:
        popen = subprocess.Popen( list( argv ), cwd = cwd or None, env = full_env,
                                  stdin = subprocess.PIPE, stdout = subprocess.PIPE, stderr = subprocess.PIPE,
                                  start_new_session = True )

    def write( data ):
        popen.stdin.write( data )
        popen.stdin.flush()

    return Child( popen, [ ( _reader( popen.stdout.fileno() ), "out" ), ( _reader( popen.stderr.fileno() ), "err" ) ],
                  write, popen.stdin.close )


class _Master:
    def __init__( self, fd ):
        self.fd = fd

    def closed_by_wait( self ):
        pass


def _pty( argv, env, cwd, tty ) -> Child:
    import fcntl
    import pty
    import struct
    import termios

    master, slave = pty.openpty()

    def size( cols, rows ):
        fcntl.ioctl( master, termios.TIOCSWINSZ, struct.pack( "HHHH", rows, cols, 0, 0 ) )

    size( int( tty.get( "cols" ) or 80 ), int( tty.get( "rows" ) or 24 ) )
    env = { **env, "TERM": tty.get( "term" ) or env.get( "TERM" ) or "xterm-256color" }

    def controlling():
        # a session of its own, whose terminal is this one: Ctrl-C reaches its foreground group
        os.setsid()
        fcntl.ioctl( 0, termios.TIOCSCTTY, 0 )

    popen = subprocess.Popen( list( argv ), cwd = cwd or None, env = env, stdin = slave, stdout = slave,
                              stderr = slave, preexec_fn = controlling, close_fds = True )
    os.close( slave )

    def write( data ):
        view = memoryview( data )
        while view:
            view = view[ os.write( master, view ) : ]

    def close_input():
        write( b"\x04" )            # end of input, as a terminal says it: ^D

    return Child( popen, [ ( _reader( master ), "out" ) ], write, close_input, resize = size, master = _Master( master ) )
