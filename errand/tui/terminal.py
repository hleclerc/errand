"""The terminal itself: reading keys and the mouse, attributes, the debug switches, and a terminfo
without `rep` for terminals that get it wrong.
"""
from __future__ import annotations

import curses
import os
import re
from pathlib import Path


LOOK  = 0.5          # seconds between askings of the output tree
WHEEL = 3            # rows per notch

# ncurses reports the wheel as buttons 4 and 5 -- when it is a build that HAS a button 5.
# The one macOS ships ( ncurses 6.0, the 32-bit mouse mask ) has none: `BUTTON5_PRESSED` is
# missing from the module, the bit that would stand for it is another button's double click,
# and the wheel turned DOWN is simply never delivered. Clicks went astray along with it, because
# the terminfo of that vintage names the old X10 form, which cannot say a column past 223.
#
# So there, errand asks the terminal for the SGR form itself ( 1006 ) and reads it off the keys
# ncurses does not recognise -- an escape followed by `[<b;x;y` and `M` or `m` -- then hands the
# rest of the screen the same ( y, x, state ) it would have got from `getmouse`, with flags of
# its own. Everywhere else ncurses does it all, as it always did.
OWN_MOUSE = not hasattr( curses, "BUTTON5_PRESSED" )

if OWN_MOUSE:
    WHEEL_UP, WHEEL_DOWN, PRESSED = 1 << 28, 1 << 29, 1 << 30
else:
    WHEEL_UP   = curses.BUTTON4_PRESSED
    WHEEL_DOWN = curses.BUTTON5_PRESSED
    # A press is an intention; a RELEASE is the end of one, and acting on both
    # would do everything twice -- and, worse, would make the release of a wheel
    # notch land as a click wherever the pointer happened to be.
    PRESSED = ( curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED
                | curses.BUTTON1_DOUBLE_CLICKED | curses.BUTTON1_TRIPLE_CLICKED )

_SGR_MOUSE = re.compile( r"\[<(\d+);(\d+);(\d+)([Mm])$" )
_own_event: tuple = ( 0, 0, 0, 0, 0 )


def read_key( win, wait = 200 ):
    """`win.getch()`, with the mouse of a terminal ncurses cannot read turned into `KEY_MOUSE`.

    `wait` is how long to wait for a key, in milliseconds; 0 is "only what is already there".
    """
    win.timeout( wait )
    key = win.getch()
    if not OWN_MOUSE or key not in ( 27, curses.KEY_MOUSE ):
        return key
    global _own_event
    # A terminfo that names `\E[<` as its mouse ( Ghostty's, xterm's ) makes ncurses swallow that
    # much and hand back KEY_MOUSE -- with the rest of the report still to be read, as keys. We
    # never ask ncurses for the mouse, so a KEY_MOUSE here can only be that.
    seen = [ ord( "[" ), ord( "<" ) ] if key == curses.KEY_MOUSE else [ ]
    win.timeout( 15 )                      # what follows an escape is already in the buffer
    try:
        while len( seen ) < 24:
            c = win.getch()
            if c == -1:
                break
            seen.append( c )
            if c in ( ord( "M" ), ord( "m" ) ):
                break
    finally:
        win.timeout( wait )
    m = _SGR_MOUSE.match( "".join( chr( c ) for c in seen if 0 <= c < 256 ) )
    if m is None:
        if key == curses.KEY_MOUSE:
            return -1                      # a report cut short: nothing to act on
        for c in reversed( seen ):         # a lone escape, and keys typed after it
            curses.ungetch( c )
        return key
    button, x, y = int( m.group( 1 ) ), int( m.group( 2 ) ) - 1, int( m.group( 3 ) ) - 1
    if button & 64:                        # the wheel: 64 up, 65 down
        state = WHEEL_DOWN if button & 1 else WHEEL_UP
    elif button & 32 or m.group( 4 ) == "m" or button & 3:
        return -1                          # drags, releases, the other buttons
    else:
        state = PRESSED
    _own_event = ( 0, x, y, 0, state )
    return curses.KEY_MOUSE


def get_mouse( ):
    return _own_event if OWN_MOUSE else curses.getmouse()


C_TITLE, C_ACTIVE, C_DIM, C_OK, C_BAD, C_WARN = 1, 2, 3, 4, 5, 6


def dim( ):
    """Faded, and faded ON PURPOSE: the default colour is what ordinary text
    already is, so saying `C_DIM` alone said nothing. What is there to be read
    only if you look for it -- helps, sizes, details -- goes through here."""
    return curses.color_pair( C_DIM ) | curses.A_DIM | curses.A_DIM


# Set when something is READING the screen rather than looking at it: every
# frame is then painted in full, instead of ncurses sending only the cells that
# changed. A test that had to reconstruct which those were would be testing its
# own reconstruction.
REPAINT = bool( os.environ.get( "ERRAND_TUI_REPAINT" ) )
# Every key and every mouse report, appended to a file. Not a feature: a way
# of answering "did that even arrive" without guessing, which is the only
# question worth asking when a screen does not react.
TRACE = os.environ.get( "ERRAND_TUI_TRACE" )


def without_rep( ):
    """Hand ncurses a terminfo that does not know `rep`, when it is one that gets it wrong.

    `rep` is "repeat the last character N times". The ncurses that macOS ships ( 6.0, from 2015 )
    uses it for a run of a MULTIBYTE character as well, and then sends neither the characters nor
    anything that repeats them: a border drawn as `╭ cases ──────╮` arrives as `╭ cases ╮`. Every
    box in the screen collapses to its title. Which terminals are hit is down to their terminfo
    -- Ghostty's has `rep`, Apple's own xterm-256color has not -- and a newer ncurses sends the
    characters, so nothing is done there. Here the entry is dumped, `rep` dropped, and compiled
    into a directory of our own; anything that goes wrong along the way leaves things as they were.
    """
    import subprocess
    import tempfile

    if tuple( curses.ncurses_version ) >= ( 6, 2, 0 ) or not os.environ.get( "TERM" ):
        return
    try:
        curses.setupterm( os.environ[ "TERM" ], 1 )
        if not curses.tigetstr( "rep" ):
            return
    except curses.error:
        return
    term = os.environ[ "TERM" ]
    mine = f"{term}-norep"
    where = Path( tempfile.gettempdir() ) / f"errand-terminfo-{os.getuid()}"
    try:
        if not any( where.glob( f"*/{mine}" ) ):
            dump = subprocess.run( [ "infocmp", "-x", "-1", term ], capture_output = True,
                                   text = True, check = True ).stdout
            lines = [ l for l in dump.splitlines() if not l.strip().startswith( "rep=" ) ]
            first = next( i for i, l in enumerate( lines ) if not l.startswith( "#" ) )
            lines[ first ] = f"{mine}|{term} without rep,"      # a dump opens with comments, then its names
            where.mkdir( exist_ok = True )
            subprocess.run( [ "tic", "-x", "-o", str( where ), "-" ], input = "\n".join( lines ) + "\n",
                            text = True, check = True, capture_output = True )
        if any( where.glob( f"*/{mine}" ) ):
            os.environ[ "TERMINFO" ] = str( where )
            os.environ[ "TERM" ]     = mine
    except ( OSError, subprocess.SubprocessError ):
        pass
