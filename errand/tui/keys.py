"""What a key does, by where it was pressed: anywhere, in a list, in the dialog.
"""
from __future__ import annotations

import curses

from .terminal import get_mouse, PRESSED, TRACE, WHEEL_DOWN, WHEEL_UP
from .screen import Screen
from .panes import _f


def _handle( screen: Screen, key ):
    """One key, whatever the screen is showing. -> "quit" when it is time to leave."""
    if TRACE:
        open( TRACE, "a" ).write( f"key {key}\n" )
    if screen.dialog is not None:
        _dialog_key( screen, key )
        return None
    if screen.help:
        screen.help = False
        return None

    screen.message = ""
    screen.dirty   = True
    answer = _common( screen, key )
    if answer is None:
        answer = _list_key( screen, key )
    if answer == "quit":
        # A run started here belongs here: leaving would break the pipe
        # under it. Detaching is how work outlives a window.
        if screen.session.running:
            screen.message = ( "something is running: x interrupts it, "
                               "or tick `detach` next time" )
            return None
        return "quit"
    return None


def _common( screen: Screen, key ):
    """What every page does the same way. -> "quit", "" when it acted, or None."""
    pane = screen.pane()
    if key == curses.KEY_MOUSE:
        try:
            _, x, y, _, state = get_mouse()
        except curses.error:
            return ""
        screen.mouse( y, x, state )
    elif key in ( curses.KEY_DOWN, 14 ):                 # ctrl-n, for while typing
        pane.move( 1 )
    elif key in ( curses.KEY_UP, 16 ):                   # ctrl-p
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
    elif key in ( 9, ord( "\t" ) ):
        screen.step( 1 )         # the next rectangle OF THIS PAGE
    elif key == curses.KEY_BTAB:
        screen.step( -1 )
    elif key in ( 10, 13, curses.KEY_ENTER ):
        screen.enter()
    elif key == curses.KEY_RIGHT:
        row = pane.current()
        if row is not None and row.open is False:
            screen.fold( row )
    elif key == curses.KEY_LEFT:
        row = pane.current()
        if row is not None and row.open:
            screen.fold( row )
    elif key == _f( 1 ):
        screen.help = True
    elif key == _f( 2 ):
        screen.turn( -1 )
    elif key == _f( 3 ):
        screen.turn( 1 )
    elif key == _f( 5 ):
        screen.run_last()
    elif key == _f( 6 ):
        screen.run_again()
    elif key == _f( 7 ):
        screen.message = screen.session.stop() or "interrupted"
    elif key == _f( 8 ):
        screen.open_file()
    elif key in ( _f( 9 ), 18 ):                         # ctrl-r
        screen.reread()
    elif key == _f( 12 ):
        return "quit"
    else:
        return None
    return ""


def _list_key( screen: Screen, key ):
    """**What you type is the search**, on either page. It is the fastest thing
    you can do with a keyboard, and finding one line among three hundred is
    what both these lists need.

    So `esc` clears what was typed -- the filter is the thing you most want
    gone -- and only then leaves. Space is a word separator while a search is
    on ( adding a word narrows, it does not rewrite ), and ctrl-space is the
    tick, as is a click straight on the box.
    """
    if key == 27:                                        # esc
        if screen.query:
            screen.typed( "" )
        else:
            return "quit"
    elif key in ( curses.KEY_BACKSPACE, 127, 8 ):
        screen.typed( screen.query[ : -1 ] )
    elif key == 0:                                       # ctrl-space
        screen.toggle_row()
    elif key == ord( " " ) and not screen.query:
        screen.toggle_row()
    elif 32 <= key < 127:
        screen.typed( screen.query + chr( key ) )
    return ""


def _dialog_key( screen: Screen, key ):
    dialog = screen.dialog
    if key == 27:
        screen.dialog = None
    elif key in ( 10, 13, curses.KEY_ENTER ):
        screen.dialog = None
        screen.launch( dialog.argv() )
    elif key == curses.KEY_MOUSE:
        try:
            _, x, y, _, state = get_mouse()
        except curses.error:
            return
        if state & PRESSED:
            dialog.click( y, x )
        elif state & WHEEL_UP:
            dialog.move( -1 )
        elif state & WHEEL_DOWN:
            dialog.move( 1 )
    elif key in ( curses.KEY_DOWN, 9 ):
        dialog.move( 1 )
    elif key in ( curses.KEY_UP, curses.KEY_BTAB ):
        dialog.move( -1 )
    elif key == curses.KEY_RIGHT:
        dialog.sideways( 1 )
    elif key == curses.KEY_LEFT:
        dialog.sideways( -1 )
    elif key == ord( " " ) and dialog.toggle():
        pass
    else:
        dialog.type( key )
