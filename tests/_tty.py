"""A terminal to drive a screen through, and what it was told to show.

A curses program cannot be tested by capturing its output: it writes to a
terminal, and without one it refuses. So the test gives it a real one -- a pty,
with a real size -- types at it, and reads what it painted.

The program is told to repaint every frame ( ERRAND_TUI_REPAINT ), because
ncurses otherwise sends only the cells that CHANGED -- so a phrase that is on
the screen but was drawn two frames ago would be nowhere in what arrives.
"""
from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

ROWS, COLS = 40, 120

DOWN, UP = "\x1bOB", "\x1bOA"          # what a terminal in keypad mode sends


class Term:
    def __init__( self, argv, cwd: Path, rows = ROWS, cols = COLS, env = None ):
        self.master, slave = pty.openpty()
        fcntl.ioctl( slave, termios.TIOCSWINSZ, struct.pack( "HHHH", rows, cols, 0, 0 ) )
        self.rows, self.cols = rows, cols
        self.child = subprocess.Popen( argv, cwd = str( cwd ), stdin = slave, stdout = slave,
                                       stderr = slave, close_fds = True, env = env )
        os.close( slave )
        self.buf = ""

    def read( self, seconds = 0.3 ):
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select( [ self.master ], [ ], [ ], max( 0, end - time.time() ) )
            if not ready:
                break
            try:
                data = os.read( self.master, 65536 )
            except OSError:
                break
            if not data:
                break
            self.buf += data.decode( "utf-8", "replace" )
        return self.buf

    def wait_for( self, text, timeout = 60 ):
        end = time.time() + timeout
        while time.time() < end:
            self.read( 0.3 )
            if text in plain( self.buf ):
                return True
        return False

    def send( self, keys, settle = 0.5 ):
        os.write( self.master, keys.encode() )
        time.sleep( settle )

    def text( self, seconds = 1.0 ):
        """What the program wrote over the next second, escapes removed.

        What, not where: a frame is a stream of jumps and strings, and each
        string was written in one piece, so a phrase the screen shows is a
        phrase that appears here.
        """
        self.buf = ""
        return plain( self.read( seconds ) )

    def close( self ):
        try:
            self.child.send_signal( signal.SIGKILL )
            self.child.wait( timeout = 5 )
        except Exception:
            pass
        os.close( self.master )


ESCAPE = re.compile( r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][B0]|\x1b[=>]|\x1b\][^\x07]*\x07" )


def plain( data ):
    """Every character the program wrote, escapes removed.

    WHAT was written, never where. Rebuilding the grid would mean writing a
    terminal emulator, and then the tests would be about that emulator -- while
    what they have to check is that a phrase is on the screen, and each phrase
    the screen shows was written to it in one piece.
    """
    return ESCAPE.sub( "", data )


def tui_env( project: Path ):
    """The same environment `run_errand` gives a run, plus a terminal."""
    import errand
    env = dict( os.environ )
    env.pop( "ERRAND_CLAIM", None )
    queue = project / ".queue"
    queue.mkdir( parents = True, exist_ok = True )
    env[ "XDG_RUNTIME_DIR" ] = str( queue )
    package = str( Path( errand.__file__ ).resolve().parent.parent )
    env[ "PYTHONPATH" ] = os.pathsep.join( [ package, *filter( None, [ env.get( "PYTHONPATH" ) ] ) ] )
    env[ "TERM" ] = "xterm-256color"
    env[ "PYTHONUNBUFFERED" ] = "1"
    env[ "ERRAND_TUI_REPAINT" ] = "1"
    return env


def start_tui( project: Path, *args ):
    return Term( [ sys.executable, "-m", "errand", "--tui", *args ], project,
                 env = tui_env( project ) )
