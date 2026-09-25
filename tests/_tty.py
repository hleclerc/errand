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

# What a terminal in keypad mode sends -- which is the mode ncurses puts it in.
DOWN, UP, END, HOME = "\x1bOB", "\x1bOA", "\x1bOF", "\x1bOH"


class Term:
    def __init__( self, argv, cwd: Path, rows = ROWS, cols = COLS, env = None ):
        self.master, slave = pty.openpty()
        fcntl.ioctl( slave, termios.TIOCSWINSZ, struct.pack( "HHHH", rows, cols, 0, 0 ) )
        self.rows, self.cols = rows, cols
        self.child = subprocess.Popen( argv, cwd = str( cwd ), stdin = slave, stdout = slave,
                                       stderr = slave, close_fds = True, env = env )
        os.close( slave )
        self.buf  = ""
        self.seen = ""        # everything ever read, so `text()` can clear `buf`

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
            text = data.decode( "utf-8", "replace" )
            self.buf  += text
            self.seen += text
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

    def frame( self, seconds = 1.0 ):
        """THE LAST picture painted, and not the last second of painting.

        `text` accumulates several frames, so it can only answer "did this
        appear"; a question of the form "is this gone" needs one frame, which
        is what everything since the last clear-screen is.
        """
        self.buf = ""
        self.read( seconds )
        parts = self.buf.split( "\x1b[2J" )
        return plain( parts[ -1 ] if len( parts ) > 1 else self.buf )

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


# ── the mouse ────────────────────────────────────────────────────────────────
#
# ncurses tells the terminal which reporting protocol it wants; a test has to
# answer in the one that was asked for, so it reads that off the stream rather
# than assuming. SGR ( 1006 ) carries coordinates as numbers and works past
# column 95; the older form packs them into single bytes.

LEFT, WHEEL_UP, WHEEL_DOWN = 0, 64, 65


def _sgr_mouse( term_name = "xterm-256color" ):
    """Does ncurses expect the SGR form of a mouse report, or the old packed one?

    Asked of the TERMINFO, which is where the answer is: `kmous` is the prefix
    ncurses will match, and here it is `\x1b[<` -- SGR. Not asked of the
    stream: ncurses does not necessarily send an enabling sequence at all, and
    a test that waited for one would sit there sending a form nothing reads.
    """
    import curses
    try:
        fd = ( sys.__stdout__ or sys.stdout ).fileno()
    except Exception:
        fd = 1
    try:
        curses.setupterm( term_name, fd )
        return ( curses.tigetstr( "kmous" ) or b"" ).startswith( b"\x1b[<" )
    except Exception:
        return True                  # anything current speaks SGR


def mouse( term, button, y, x ):
    """Report a press at ( y, x ), zero-based, in the form the app will read.

    A wheel notch has no release and a terminal does not send one; a button
    does, and leaving it out would leave the terminal thinking one is held.
    """
    if _sgr_mouse():
        term.send( f"\x1b[<{button};{x + 1};{y + 1}M" )
        if button < WHEEL_UP:
            term.send( f"\x1b[<{button};{x + 1};{y + 1}m", settle = 0.4 )
    else:
        term.send( "\x1b[M" + chr( 32 + button ) + chr( 33 + x ) + chr( 33 + y ) )


def click( term, y, x ):
    mouse( term, LEFT, y, x )


def wheel( term, y, x, down = True, times = 1 ):
    for _ in range( times ):
        mouse( term, WHEEL_DOWN if down else WHEEL_UP, y, x )
