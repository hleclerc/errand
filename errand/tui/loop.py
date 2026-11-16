"""The loop: lay the two panes out, draw them, read a key, hand it to the screen. And `main`.
"""
from __future__ import annotations

import curses
import os
import subprocess
from pathlib import Path

from .drawing import draw_pane, put
from .screen import Screen
from .terminal import C_ACTIVE, C_BAD, C_DIM, C_OK, C_TITLE, C_WARN, dim, get_mouse, OWN_MOUSE, PRESSED, read_key, \
    REPAINT, TRACE, WHEEL, WHEEL_DOWN, WHEEL_UP, without_rep

HINT = "↑↓ choose · ←→ fold · enter detail · s stop · o output · x shell · / filter · p project · r again · ? keys · q quit"

KEYS = [
    ( "↑ ↓  pgup pgdn", "move in the active pane" ),
    ( "← →", "fold, unfold a machine or a history" ),
    ( "tab", "the other pane: the list, or the detail ( its files and output )" ),
    ( "enter", "list: go to the detail · detail: open the file under the cursor" ),
    ( "s", "stop the process ( INT, TERM, KILL ) or the vm under the cursor, once confirmed" ),
    ( "o", "the whole output, or the file under the cursor, in $PAGER" ),
    ( "x", "a shell on its machine, where it works" ),
    ( "/", "filter: machine, project, command, state ( esc clears it )" ),
    ( "p", "the current project only, or every project" ),
    ( "r", "ask every machine again now" ),
    ( "click, wheel", "choose a row · scroll what is under the pointer" ),
    ( "q", "leave ( nothing stops: what runs is owned by its agents )" ),
]


def layout( screen: Screen, height, width ):
    left = max( 40, min( width - 30, width * 58 // 100 ) )
    screen.list.box   = ( 1, 0, height - 2, left )
    screen.detail.box = ( 1, left, height - 2, width - left )


def draw( win, screen: Screen ):
    win.erase()
    if REPAINT:
        win.clearok( True )
    height, width = win.getmaxyx()
    layout( screen, height, width )
    for index, pane in enumerate( screen.panes ):
        draw_pane( win, pane, index == screen.active )
    title = "errand · what runs where"
    put( win, 0, 1, title, width - 2, curses.color_pair( C_TITLE ) | curses.A_BOLD )
    if screen.typing:
        line, attr = f"/{screen.query}▏  enter keeps it · esc clears it", curses.A_BOLD
    elif screen.confirm:
        line, attr = screen.confirm[ 0 ], curses.color_pair( C_WARN ) | curses.A_BOLD
    elif screen.message:
        line, attr = screen.message, curses.color_pair( C_WARN )
    else:
        line, attr = HINT, dim()
    put( win, height - 1, 0, line.ljust( width - 1 )[ : width - 1 ], width - 1, attr )
    curses.curs_set( 0 )
    if screen.help:
        _help( win, height, width )
    win.noutrefresh()
    curses.doupdate()


def _help( win, height, width ):
    w, h = min( width - 4, 90 ), len( KEYS ) + 4
    y0, x0 = max( 0, ( height - h ) // 2 ), max( 0, ( width - w ) // 2 )
    for i in range( h ):
        put( win, y0 + i, x0, " " * w, w, curses.A_REVERSE )
    put( win, y0 + 1, x0 + 2, "keys", w - 4, curses.A_REVERSE | curses.A_BOLD )
    for i, ( key, what ) in enumerate( KEYS ):
        put( win, y0 + 2 + i, x0 + 2, f"{key:<16} {what}", w - 4, curses.A_REVERSE )
    put( win, y0 + h - 1, x0 + 2, "any key closes this", w - 4, curses.A_REVERSE )


def handle( screen: Screen, key ):
    """One key -> "quit" when it is time to leave."""
    if TRACE:
        open( TRACE, "a" ).write( f"key {key}\n" )
    if screen.help:
        screen.help = False
        return None
    if screen.confirm:
        _, then = screen.confirm
        screen.confirm = None
        if key in ( ord( "y" ), ord( "Y" ) ):
            then()
        else:
            screen.message = "not stopped"
        return None
    if screen.typing:
        if key == 27:
            screen.typing, screen.query = False, ""
        elif key in ( 10, 13, curses.KEY_ENTER ):
            screen.typing = False
        elif key in ( curses.KEY_BACKSPACE, 127, 8 ):
            screen.query = screen.query[ : -1 ]
        elif 32 <= key < 127:
            screen.query += chr( key )
        return None

    screen.message = ""
    pane = screen.pane()
    if key == curses.KEY_MOUSE:
        try:
            _, x, y, _, state = get_mouse()
        except curses.error:
            return None
        _mouse( screen, y, x, state )
    elif key in ( curses.KEY_DOWN, ord( "j" ) ):
        pane.move( 1 )
    elif key in ( curses.KEY_UP, ord( "k" ) ):
        pane.move( -1 )
    elif key == curses.KEY_NPAGE:
        pane.move( max( 1, pane.inner[ 2 ] - 1 ) )
    elif key == curses.KEY_PPAGE:
        pane.move( -max( 1, pane.inner[ 2 ] - 1 ) )
    elif key == curses.KEY_HOME:
        pane.cursor = 0
        pane.reveal()
    elif key == curses.KEY_END:
        pane.cursor = max( 0, len( pane.rows ) - 1 )
        pane.reveal()
    elif key in ( 9, curses.KEY_BTAB ):
        screen.active = 1 - screen.active
    elif key in ( curses.KEY_RIGHT, curses.KEY_LEFT ):
        row = screen.list.current()
        if row is not None and row.open is not None and row.open == ( key == curses.KEY_LEFT ):
            screen.toggle( row )
        elif key == curses.KEY_LEFT and screen.active == 1:
            screen.active = 0
    elif key in ( 10, 13, curses.KEY_ENTER ):
        screen.enter()
    elif key == ord( "s" ):
        screen.stop()
    elif key == ord( "o" ):
        screen.whole()
    elif key == ord( "x" ):
        screen.shell()
    elif key == ord( "/" ):
        screen.typing = True
    elif key == 27:
        screen.query = ""
    elif key == ord( "p" ):
        if screen.mine:
            screen.only = not screen.only
        else:
            screen.message = "not in a project: every project is shown"
    elif key == ord( "r" ):
        screen.refresh()
    elif key == ord( "?" ):
        screen.help = True
    elif key in ( ord( "q" ), ord( "Q" ) ):
        return "quit"
    return None


def _mouse( screen: Screen, y, x, state ):
    for index, pane in enumerate( screen.panes ):
        if not pane.holds( y, x ):
            continue
        if state & WHEEL_UP:
            pane.scroll( -WHEEL )
        elif state & WHEEL_DOWN:
            pane.scroll( WHEEL )
        elif state & PRESSED:
            screen.active = index
            where = pane.row_at( y )
            if where is not None:
                pane.cursor = where
                row = pane.rows[ where ]
                if row.open is not None and x - pane.inner[ 1 ] - 2 * row.depth < 2:
                    screen.toggle( row )
        return


def _colours():
    if not curses.has_colors():
        return
    curses.use_default_colors()
    for pair, colour in ( ( C_TITLE, curses.COLOR_CYAN ), ( C_ACTIVE, curses.COLOR_CYAN ), ( C_DIM, -1 ),
                          ( C_OK, curses.COLOR_GREEN ), ( C_BAD, curses.COLOR_RED ), ( C_WARN, curses.COLOR_YELLOW ) ):
        try:
            curses.init_pair( pair, colour, -1 )
        except curses.error:
            pass


def _mouse_on( on: bool ):
    if OWN_MOUSE:
        os.write( 1, b"\x1b[?1000h\x1b[?1006h" if on else b"\x1b[?1006l\x1b[?1000l" )


def loop( win, screen: Screen ):
    curses.curs_set( 0 )
    if hasattr( curses, "set_escdelay" ):
        curses.set_escdelay( 25 )         # esc is a key here ( the filter ), not a second's wait
    _colours()
    if not OWN_MOUSE:
        curses.mousemask( curses.ALL_MOUSE_EVENTS | WHEEL_UP | WHEEL_DOWN )
    _mouse_on( True )
    curses.mouseinterval( 0 )

    def outside( argv, cwd = None ):
        """A pager, a shell: the terminal is theirs until they end."""
        _mouse_on( False )
        curses.endwin()
        try:
            subprocess.call( argv, cwd = cwd )
        except OSError as err:
            screen.message = f"{argv[ 0 ]}: {err}"
        finally:
            win.refresh()
            _mouse_on( True )

    screen.run_outside = outside
    while True:
        screen.build()
        draw( win, screen )
        key = read_key( win, 500 )
        if key == -1:
            continue
        # The mouse events already waiting are dealt with before the next picture: a turn of the
        # wheel is dozens of events, and a picture each is a screen that lags behind the hand.
        for _ in range( 200 ):
            if handle( screen, key ) == "quit":
                return 0
            if key != curses.KEY_MOUSE:
                break
            key = read_key( win, 0 )
            if key not in ( -1, curses.KEY_MOUSE ):
                curses.ungetch( key )
                break
            if key == -1:
                break


def main( root: Path | None = None ):
    import sys
    from .machines import watched

    if not sys.stdout.isatty():
        print( "errand tui needs a terminal", file = sys.stderr )
        return 2
    from .. import config
    mine = set()
    if root is not None and config.config_in( root ) is not None:       # in a project: it is highlighted
        from ..cli.standing import _project_names
        mine = _project_names( root )
    machines = watched()
    for m in machines:
        m.watch()
    without_rep()
    try:
        return curses.wrapper( loop, Screen( machines, mine ) ) or 0
    finally:
        _mouse_on( False )
        for m in machines:
            m.stopped = True
