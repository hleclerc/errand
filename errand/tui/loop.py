"""The loop: lay the panes out, draw them, read a key, hand it to the screen. And `main`.
"""
from __future__ import annotations

import curses
import os
import time
from pathlib import Path

from ..session import Session
from .terminal import C_ACTIVE, C_BAD, C_DIM, C_OK, C_TITLE, C_WARN, dim, LOOK, OWN_MOUSE, read_key, REPAINT, WHEEL_DOWN, WHEEL_UP, without_rep
from .panes import PAGES
from .drawing import draw_pane, put
from .screen import Screen
from .keys import _handle


# ── the loop ─────────────────────────────────────────────────────────────────

HINTS = {
    "cases": "type to search · enter runs it · space ticks · tab next box · "
             "F3 runs · F1 keys · F12 quit",
    "runs" : "type to search · enter its files · F5 last again · F8 open · tab next box · "
             "F2 cases · F1 keys · F12 quit",
}

KEYS = [
    ( "F1",     "these keys" ),
    ( "F2 F3",  "the page before · the page after" ),
    ( "F5 F6",  "run the last command again · the one under the cursor" ),
    ( "F7 F8",  "interrupt what is running · open the file under the cursor" ),
    ( "F9",     "read the project again" ),
    ( "F12",    "leave" ),
    ( "typing", "the search, on either page" ),
    ( "esc",    "clear what you typed, then leave" ),
    ( "tab",    "the next rectangle of this page; shift-tab the one before" ),
    ( "arrows", "move in the active rectangle" ),
    ( "click",  "choose a row, and that rectangle becomes the active one" ),
    ( "wheel",  "scroll whatever is under the pointer" ),
    ( "space",  "tick a case, or fold — ctrl-space while a search is on" ),
    ( "enter",  "cases: ask where to run · runs: its files · files: open it" ),
]


def layout( screen: Screen, height, width ):
    """A line for the pages, a line for the search, a line for the keys, and
    the rectangles between.

    The search has a line of its own on BOTH pages: it is what you type into,
    so it is never somewhere you have to go and find, and it is in the same
    place whichever list you are looking at.
    """
    body = height - 3
    if screen.page == "cases":
        left = max( 30, min( 80, width * 55 // 100 ) )
        screen.cases.box = ( 2, 0, body, left )
        screen.about.box = ( 2, left, body, width - left )
        return
    left = max( 30, min( 76, width * 50 // 100 ) )
    files = max( 4, body * 35 // 100 )
    screen.runs.box  = ( 2, 0, body, left )
    screen.files.box = ( 2, left, files, width - left )
    screen.look.box  = ( 2 + files, left, body - files, width - left )


def draw( win, screen: Screen ):
    win.erase()
    if REPAINT:
        win.clearok( True )
    height, width = win.getmaxyx()
    layout( screen, height, width )
    for index, pane in enumerate( screen.panes ):
        draw_pane( win, pane, index == screen.active and screen.dialog is None )

    state = ( "running" if screen.session.running else
              "following" if screen.session.record else "idle" )
    screen.tabs, at = [ ], 1
    for name in PAGES:
        shown = f"[{name}]" if name == screen.page else f" {name} "
        put( win, 0, at, shown, max( 0, width - at ),
             curses.color_pair( C_ACTIVE if name == screen.page else C_DIM )
             | ( curses.A_BOLD if name == screen.page else 0 ) )
        screen.tabs.append( ( at, at + len( shown ), name ) )
        at += len( shown ) + 2
    right = f"errand · {screen.session.root.name} · {state}"
    put( win, 0, max( 0, width - len( right ) - 1 ), right, width - 1,
         dim() )

    put( win, 1, 1, "find: ", 6, curses.color_pair( C_TITLE ) | curses.A_BOLD )
    if screen.query:
        put( win, 1, 7, screen.query.ljust( width - 9 )[ : width - 9 ], width - 9,
             curses.A_BOLD )
    else:
        put( win, 1, 7, ( "a case: name, file or tag" if screen.page == "cases"
                          else "a command" ).ljust( width - 9 )[ : width - 9 ],
             width - 9, dim() )

    hint = screen.message or (
        "space ticks · ←→ picks · type into a field · enter runs · esc gives up"
        if screen.dialog is not None else
        "enter runs the first one · esc clears what you typed · ctrl-space ticks"
        if screen.query else HINTS[ screen.page ] )
    put( win, height - 1, 0, hint.ljust( width - 1 )[ : width - 1 ], width - 1,
         curses.color_pair( C_WARN ) if screen.message else dim() )
    if screen.dialog is not None:
        screen.dialog.draw( win )
    else:
        curses.curs_set( 0 )
        if screen.help:
            _help( win, height, width )
    win.noutrefresh()
    curses.doupdate()


def _help( win, height, width ):
    w, h = min( width - 4, 78 ), len( KEYS ) + 4
    y0, x0 = max( 0, ( height - h ) // 2 ), max( 0, ( width - w ) // 2 )
    for i in range( h ):
        put( win, y0 + i, x0, " " * w, w, curses.A_REVERSE )
    put( win, y0 + 1, x0 + 2, "keys", w - 4, curses.A_REVERSE | curses.A_BOLD )
    for i, ( key, what ) in enumerate( KEYS ):
        put( win, y0 + 2 + i, x0 + 2, f"{key:<10} {what}", w - 4, curses.A_REVERSE )
    put( win, y0 + h - 1, x0 + 2, "any key closes this", w - 4, curses.A_REVERSE )


def loop( win, screen: Screen ):
    curses.curs_set( 0 )
    if curses.has_colors():
        curses.use_default_colors()
        for pair, colour in ( ( C_TITLE, curses.COLOR_CYAN ), ( C_ACTIVE, curses.COLOR_CYAN ),
                              ( C_DIM, -1 ), ( C_OK, curses.COLOR_GREEN ),
                              ( C_BAD, curses.COLOR_RED ), ( C_WARN, curses.COLOR_YELLOW ) ):
            try:
                curses.init_pair( pair, colour, -1 )
            except curses.error:
                pass
    if OWN_MOUSE:
        os.write( 1, b"\x1b[?1000h\x1b[?1006h" )
    else:
        curses.mousemask( curses.ALL_MOUSE_EVENTS | WHEEL_UP | WHEEL_DOWN )
    curses.mouseinterval( 0 )            # a click is a click, not half a drag
    win.timeout( 200 )

    while True:
        now = time.time()
        # Twice a second by itself, and at once after a key: a fold or a tick
        # that waited for the next tick to show would feel like a lost press.
        if now - screen.looked > LOOK or screen.dirty:
            screen.dirty = False
            if now - screen.looked > LOOK:
                screen.looked = now
                if screen.session.plan:
                    screen.session.look()
            screen.build_cases()
            screen.build_runs()
        screen.build_about()
        screen.build_files()
        screen.build_preview()
        draw( win, screen )

        key = read_key( win )
        if key == -1:
            continue
        # The mouse events already waiting are dealt with BEFORE the next picture: a turn of the
        # wheel is dozens of events a second, and a picture per event is a screen that flickers
        # through every intermediate scroll position, which is also what makes it lag behind the
        # hand. Only the mouse: after any other key the lists are rebuilt before the next one.
        for _ in range( 200 ):
            if _handle( screen, key ) == "quit":
                return 0
            if key != curses.KEY_MOUSE:
                break
            key = read_key( win, 0 )
            if key not in ( -1, curses.KEY_MOUSE ):
                curses.ungetch( key )
                break
            if key == -1:
                break
        win.timeout( 200 )


def main( root: Path, out_root: Path, also = ( ) ):
    import sys

    if not sys.stdout.isatty():
        print( "errand tui needs a terminal", file = sys.stderr )
        return 2
    without_rep()
    try:
        return curses.wrapper( loop, Screen( Session( root, out_root, also ).discover() ) ) or 0
    finally:
        if OWN_MOUSE:                      # what `loop` switched on, whatever ended it
            os.write( 1, b"\x1b[?1006l\x1b[?1000l" )
