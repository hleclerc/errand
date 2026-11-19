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

HINT = "1 runs · 2 machines · 3 caches · ↑↓ choose · →← unfold, fold · tab detail · enter open · e edit · k kill · f forget · r rename · a watch · / filter · ? keys · q quit"

KEYS = [
    ( "↑ ↓  pgup pgdn", "move in the active pane" ),
    ( "1  2  3", "the runs tab ( running, waiting, done ), the machines tab, the caches tab" ),
    ( "→  ←", "unfold, fold: a machine, a day · ← on a row inside: up to what holds it" ),
    ( "tab", "the other pane: the list, or the detail ( its outputs: the one under the cursor is shown )" ),
    ( "enter", "fold, unfold · a row: its detail · an output: opened as this machine opens it ( open, xdg-open )" ),
    ( "e", "the output under the cursor in $VISUAL / $EDITOR ( a copy, when it is on another machine )" ),
    ( "k", "kill what is under the cursor, once confirmed: a process, a vm, or all errand runs on a machine" ),
    ( "f", "forget the machine under the cursor: not asked any more, until work is sent there ( errand machines )" ),
    ( "a", "watch the machine under the cursor, or not: saved, errand status follows it; a greyed one is not contacted" ),
    ( "r", "name the machine under the cursor: every name it is reached by shows as one" ),
    ( "o", "the whole console, or the output under the cursor, in $PAGER" ),
    ( "x", "a shell on its machine, where it works" ),
    ( "/", "filter: machine, project, command, state ( esc clears it )" ),
    ( "p", "the current project only, or every project" ),
    ( "i  u", "caches: remove the dead entries, those unused for n days -- of a place, or of every place on a cache's row" ),
    ( "d  D", "caches: the entry under the cursor removed where it is dead or unused, or everywhere it is" ),
    ( "h", "caches: the machine of the place under the cursor holds its directory ( its agent purges it daily )" ),
    ( "n  v", "caches: the days after which an entry is unused ( 30 ) · every entry, or the dead and unused only" ),
    ( "R", "ask every machine again now ( they say what changes by themselves )" ),
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
    _title( win, screen, width )
    if screen.typing:
        line, attr = f"/{screen.query}▏  enter keeps it · esc clears it", curses.A_BOLD
    elif screen.confirm:
        line, attr = f"enter: {screen.confirm.verb} · esc: nothing", curses.color_pair( C_WARN ) | curses.A_BOLD
    elif screen.prompt:
        line, attr = "enter: keep it · esc: nothing", curses.color_pair( C_WARN ) | curses.A_BOLD
    elif screen.message:
        line, attr = screen.message, curses.color_pair( C_WARN )
    else:
        line, attr = HINT, dim()
    put( win, height - 1, 0, line.ljust( width - 1 )[ : width - 1 ], width - 1, attr )
    curses.curs_set( 0 )
    if screen.help:
        _help( win, height, width )
    if screen.confirm:
        _confirm( win, screen.confirm, height, width )
    if screen.prompt:
        _prompt( win, screen.prompt, height, width )
    win.noutrefresh()
    curses.doupdate()


def _title( win, screen, width ):
    """`errand  ● 3 running  ◌ 1 waiting  · 5 machines`: the whole picture, before any row."""
    running = waiting = 0
    for m in screen.machines:
        for p in ( m.table or { } ).get( "procs", [ ] ):
            if p.get( "vm" ) or p.get( "kind" ) == "agent":
                continue
            if p.get( "waiting" ):
                waiting += 1
            else:
                running += 1
    asleep = sum( 1 for m in screen.machines if getattr( m, "dormant", False ) )
    x = 1
    left = [ ( "errand", curses.color_pair( C_TITLE ) | curses.A_BOLD ), ( "  ", 0 ) ]
    for i, t in enumerate( ( "runs", "machines", "caches" ) ):
        left.append( ( f" {i + 1} {t} ", curses.color_pair( C_ACTIVE ) | curses.A_BOLD | curses.A_REVERSE if t == screen.tab else dim() ) )
        left.append( ( " ", 0 ) )
    for text, attr in left:
        put( win, 0, x, text, width - x - 1, attr )
        x += len( text )
    # the counts on the right: apart from the tabs
    right = [ ( f"● {running} running", curses.color_pair( C_OK ) | curses.A_BOLD if running else dim() ),
              ( "   ", 0 ),
              ( f"◌ {waiting} waiting", curses.color_pair( C_WARN ) | curses.A_BOLD if waiting else dim() ),
              ( "   ", 0 ),
              ( f"{len( screen.machines )} machines" + ( f", {asleep} not watched" if asleep else "" ), dim() ) ]
    size = sum( len( t ) for t, _ in right )
    x = max( x + 2, width - 2 - size )
    for text, attr in right:
        put( win, 0, x, text, width - x - 1, attr )
        x += len( text )


def _confirm( win, asked, height, width ):
    """What waits for a yes, as a window in the middle: what it is, what it touches, and the two keys."""
    from .drawing import draw_box
    inner = max( [ len( asked.title ), *( len( l ) + 2 for l in asked.lines ), 34 ] )
    w = min( width - 4, inner + 6 )
    h = min( height - 2, len( asked.lines ) + 6 )
    y0, x0 = max( 0, ( height - h ) // 2 ), max( 0, ( width - w ) // 2 )
    tone = curses.color_pair( C_BAD if asked.danger else C_WARN )
    for i in range( h ):
        put( win, y0 + i, x0, " " * w, w, 0 )
    draw_box( win, ( y0, x0, h, w ), asked.verb, False )
    for i in range( h ):                                        # the frame in the action's tone
        put( win, y0 + i, x0, "│" if 0 < i < h - 1 else ( "╭" if i == 0 else "╰" ), 1, tone | curses.A_BOLD )
        put( win, y0 + i, x0 + w - 1, "│" if 0 < i < h - 1 else ( "╮" if i == 0 else "╯" ), 1, tone | curses.A_BOLD )
    put( win, y0, x0 + 1, "─" * ( w - 2 ), w - 2, tone | curses.A_BOLD )
    put( win, y0 + h - 1, x0 + 1, "─" * ( w - 2 ), w - 2, tone | curses.A_BOLD )
    put( win, y0, x0 + 2, f" {asked.verb} ", w - 4, tone | curses.A_BOLD )
    put( win, y0 + 1, x0 + 3, asked.title, w - 6, curses.A_BOLD )
    for i, line in enumerate( asked.lines[ : h - 5 ] ):
        put( win, y0 + 3 + i, x0 + 3, f"· {line}", w - 6, 0 )
    keys = f"enter: {asked.verb}   ·   esc: nothing"
    put( win, y0 + h - 2, x0 + w - 3 - len( keys ), keys, len( keys ), tone | curses.A_BOLD )


def _prompt( win, asked, height, width ):
    """A line to type, as a window in the middle."""
    from .drawing import draw_box
    w = min( width - 4, max( 50, len( asked.title ) + 8, len( asked.text ) + 10 ) )
    h = 6
    y0, x0 = max( 0, ( height - h ) // 2 ), max( 0, ( width - w ) // 2 )
    for i in range( h ):
        put( win, y0 + i, x0, " " * w, w, 0 )
    draw_box( win, ( y0, x0, h, w ), "name", True )
    put( win, y0 + 1, x0 + 3, asked.title, w - 6, curses.A_BOLD )
    put( win, y0 + 3, x0 + 3, "› ", 2, curses.color_pair( C_ACTIVE ) | curses.A_BOLD )
    # the current name, selected: what is typed replaces it
    put( win, y0 + 3, x0 + 5, asked.text, w - 8, ( curses.A_REVERSE if asked.fresh else curses.A_BOLD ) | curses.color_pair( C_ACTIVE ) )
    put( win, y0 + 3, x0 + 5 + len( asked.text ), "▏", 1, curses.color_pair( C_ACTIVE ) )
    keys = "enter: keep it   ·   esc: nothing"
    put( win, y0 + h - 1 - 0, x0 + w - 3 - len( keys ), keys, len( keys ), dim() )


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
    if screen.prompt:
        asked = screen.prompt
        if key == 27:
            screen.prompt, screen.message = None, "nothing done"
        elif key in ( 10, 13, curses.KEY_ENTER ):
            screen.prompt = None
            asked.go( asked.text )
        elif key in ( curses.KEY_BACKSPACE, 127, 8 ):
            screen.prompt = asked._replace( text = "" if asked.fresh else asked.text[ : -1 ], fresh = False )
        elif 32 <= key < 127:
            screen.prompt = asked._replace( text = ( "" if asked.fresh else asked.text ) + chr( key ), fresh = False )
        return None
    if screen.confirm:
        asked, screen.confirm = screen.confirm, None
        if key in ( ord( "y" ), ord( "Y" ), 10, 13, curses.KEY_ENTER ):
            asked.go()
        else:
            screen.message = "nothing done"
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
    elif key == curses.KEY_DOWN:
        pane.move( 1 )
    elif key == curses.KEY_UP:                      # `k` kills: no vi keys to move
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
    elif key == curses.KEY_RIGHT:
        screen.fold( unfold = True )
    elif key == curses.KEY_LEFT:
        screen.fold( unfold = False )
    elif key == ord( "e" ):
        screen.edit()
    elif key in ( ord( "1" ), ord( "2" ), ord( "3" ) ):
        screen.select( ( "runs", "machines", "caches" )[ key - ord( "1" ) ] )
    elif screen.tab == "caches" and key in ( ord( "i" ), ord( "u" ), ord( "d" ), ord( "D" ) ):
        screen.remove_cached( { "i": "dead", "u": "unused", "d": "flagged", "D": "everywhere" }[ chr( key ) ] )
    elif screen.tab == "caches" and key == ord( "h" ):
        screen.hold_cached()
    elif screen.tab == "caches" and key == ord( "n" ):
        screen.ask_cache_days()
    elif screen.tab == "caches" and key == ord( "v" ):
        screen.cache_every = not screen.cache_every
        screen.message = "every entry" if screen.cache_every else "the dead and unused entries only"
    elif key in ( 10, 13, curses.KEY_ENTER ):
        screen.enter()
    elif key == ord( "k" ):
        screen.kill()
    elif key == ord( "f" ):
        screen.forget()
    elif key == ord( "a" ):
        screen.activate()
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
        screen.rename()
    elif key == ord( "R" ):
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
    from .terminal import tint_ready
    tint_ready()                                # the row chosen: tinted, its colours kept


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
