"""Drawing boxes and rows with curses.
"""
from __future__ import annotations

import curses

from .terminal import C_ACTIVE, C_BAD, C_OK, C_TITLE, C_WARN, dim


BOX = "╭╮╰╯─│"


# ── drawing ──────────────────────────────────────────────────────────────────

def put( win, y, x, text, width, attr = 0 ):
    if y < 0 or x < 0 or width <= 0:
        return
    try:
        win.addnstr( y, x, str( text ), width, attr )
    except curses.error:
        pass                # the bottom right cell of a terminal is a lie


def draw_box( win, box, title, active ):
    y, x, h, w = box
    if h < 2 or w < 4:
        return
    tl, tr, bl, br, hor, ver = BOX
    attr = ( curses.color_pair( C_ACTIVE ) | curses.A_BOLD ) if active \
           else dim()
    head = f" {title} "[ : max( 0, w - 4 ) ]
    put( win, y, x, tl + head + hor * ( w - 2 - len( head ) ) + tr, w, attr )
    for i in range( 1, h - 1 ):
        put( win, y + i, x, ver, 1, attr )
        put( win, y + i, x + w - 1, ver, 1, attr )
    put( win, y + h - 1, x, bl + hor * ( w - 2 ) + br, w, attr )


def draw_rows( win, rows, cursor, box_inner, active, plain = False ):
    top_y, left, height, width = box_inner
    for i in range( height ):
        index = cursor[ 0 ] + i          # cursor is ( top, selected )
        if index >= len( rows ):
            break
        row = rows[ index ]
        y = top_y + i
        chosen = active and index == cursor[ 1 ]
        base = curses.A_REVERSE if chosen else 0
        if plain:
            put( win, y, left, row.label, width, base | _colour( row ) )
            continue
        lead = "  " * row.depth
        if row.open is not None:
            lead += "▾ " if row.open else "▸ "
        elif row.checked is not None:
            lead += "[x] " if row.checked else "[ ] "
        elif row.mark is not None:
            lead += f"{row.mark:<5}"
        else:
            lead += "  "
        text = lead + row.label
        put( win, y, left, text.ljust( width )[ : width ], width, base | _colour( row ) )
        for i in row.hits:
            at = len( lead ) + i
            if at < width:
                put( win, y, left + at, row.label[ i ], 1,
                     base | curses.color_pair( C_ACTIVE ) | curses.A_BOLD )
        if row.detail:
            room = width - len( text ) - 2
            if room > 4:
                shown = row.detail[ : room ]
                put( win, y, left + width - len( shown ), shown, len( shown ),
                     base | dim() )


def _colour( row ):
    if row.kind == "group":
        return curses.color_pair( C_TITLE ) | curses.A_BOLD
    if row.kind == "broken" or row.mark in ( "FAIL", "lost" ):
        return curses.color_pair( C_BAD )
    if row.mark == "ok":
        return curses.color_pair( C_OK )
    if row.mark == "skip":
        return curses.color_pair( C_WARN )
    if row.checked:
        return curses.color_pair( C_OK )
    return 0


def draw_pane( win, pane, active ):
    draw_box( win, pane.box, pane.title, active )
    draw_rows( win, pane.rows, ( pane.top, pane.cursor ), pane.inner, active, pane.plain )
