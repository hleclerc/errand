"""Drawing boxes and rows with curses.
"""
from __future__ import annotations

import curses

from .terminal import C_ACTIVE, C_BAD, C_OK, C_TITLE, C_WARN, dim, selected


BOX = "╭╮╰╯─│"

# control characters ( NUL makes curses raise, the others move the cursor )
# become one visible cell each, so the widths computed by callers still hold
_CONTROLS = { c: "·" for c in [ *range( 32 ), 127 ] }
_CONTROLS[ ord( "\t" ) ] = " "


# ── drawing ──────────────────────────────────────────────────────────────────

def put( win, y, x, text, width, attr = 0 ):
    if y < 0 or x < 0 or width <= 0:
        return
    try:
        win.addnstr( y, x, str( text ).translate( _CONTROLS ), width, attr )
    except curses.error:
        pass                # the bottom right cell of a terminal is a lie


def draw_box( win, box, title, active ):
    y, x, h, w = box
    if h < 2 or w < 4:
        return
    tl, tr, bl, br, hor, ver = BOX
    attr = dim()                                # the frame quiet; the active pane says so by its title
    head = f" {title} "[ : max( 0, w - 4 ) ]
    put( win, y, x, tl + head + hor * ( w - 2 - len( head ) ) + tr, w, attr )
    put( win, y, x + 1, head, len( head ), ( curses.color_pair( C_ACTIVE ) | curses.A_BOLD ) if active else dim() )
    for i in range( 1, h - 1 ):
        put( win, y + i, x, ver, 1, attr )
        put( win, y + i, x + w - 1, ver, 1, attr )
    put( win, y + h - 1, x, bl + hor * ( w - 2 ) + br, w, attr )


def _lead( row ) -> str:
    lead = "  " * row.depth
    if row.open is not None:
        lead += "▾ " if row.open else "▸ "
    elif row.checked is not None:
        lead += "[x] " if row.checked else "[ ] "
    elif row.mark is not None:
        lead += f"{SYMBOLS.get( row.mark, row.mark ):<2}" if row.mark in SYMBOLS else f"{row.mark:<5}"
    else:
        lead += "  "
    return lead


# A state as a sign, its colour from `_colour`: read at a glance down the left edge ( ADR 0016's console too ).
SYMBOLS = { "run": "●", "wait": "◌", "ok": "✓", "FAIL": "✗", "skip": "–", "lost": "?", "orph": "?" }


def draw_rows( win, rows, cursor, box_inner, active, plain = False ):
    top_y, left, height, width = box_inner
    # The gauges of every machine start at one column: read down at a glance, whatever the names.
    gauged = [ len( _lead( r ) + r.label ) for r in rows if r.meters ]
    meters_at = max( gauged ) + 2 if gauged else 0
    for i in range( height ):
        index = cursor[ 0 ] + i          # cursor is ( top, selected )
        if index >= len( rows ):
            break
        row = rows[ index ]
        y = top_y + i
        chosen = active and index == cursor[ 1 ]
        look = selected if chosen else ( lambda a: a )
        base = 0
        if row.kind == "out" and row.label[ 2 : 3 ] in ( "│", "┃" ):            # the gutter dim, the line as it is
            put( win, y, left, " " * width, width, look( 0 ) )
            put( win, y, left, row.label[ : 4 ], 4, look( dim() ) )
            put( win, y, left + 4, row.label[ 4 : ], width - 4, look( 0 ) )
            continue
        if row.kind == "cend":                                                   # `╰ PASS name  2.1 s`
            put( win, y, left, " " * width, width, look( 0 ) )
            put( win, y, left, row.label[ : 4 ], 4, look( dim() ) )
            tone = { "PASS": C_OK, "SKIP": C_WARN }.get( row.data, C_BAD )
            put( win, y, left + 4, row.label[ 4 : ], width - 4, look( curses.color_pair( tone ) | curses.A_BOLD ) )
            continue
        if plain:
            put( win, y, left, row.label.ljust( width ) if chosen else row.label, width, look( _colour( row ) ) )
            continue
        lead = _lead( row )
        text = lead + row.label
        if row.detail and not row.meters and len( text ) + len( row.detail ) + 2 > width:
            # the label gives way, not what is said at the right ( how long, where, when )
            room = max( 8, width - len( row.detail ) - 3 )
            text = text[ : room - 1 ] + "…"
        # a state's colour is its sign's ( ● ✓ ✗ ◌ ): the words stay plain, as the console's
        tone = 0 if row.mark in SYMBOLS else _colour( row )
        if row.meters:
            # the ground tinted under all of it; the gauges keep their colours
            put( win, y, left, " " * width, width, look( 0 ) if chosen and selected( 0 ) & curses.A_COLOR else 0 )
            put( win, y, left, text, len( text ), look( tone ) )
        else:
            put( win, y, left, text.ljust( width )[ : width ], width, look( tone ) )
        if row.mark in SYMBOLS:                                       # the sign in its colour
            put( win, y, left + len( lead ) - 2, lead[ -2 : ], 1, look( _colour( row ) | curses.A_BOLD ) )
        for i in row.hits:
            at = len( lead ) + i
            if at < width:
                put( win, y, left + at, row.label[ i ], 1,
                     look( curses.color_pair( C_ACTIVE ) | curses.A_BOLD ) )
        end = len( text )
        if row.meters:
            end = _meters( win, y, left, max( len( text ) + 2, meters_at ), width - len( row.detail or "" ) - 2,
                           row.meters, look )
        if row.detail:
            room = width - end - 2
            if room > 2:
                shown = row.detail[ : room ]
                put( win, y, left + width - len( shown ), shown, len( shown ), look( dim() ) )


def level( fraction: float ) -> int:
    """The colour of a gauge: green, yellow from 60 %, red from 85 %."""
    return curses.color_pair( C_BAD if fraction >= 0.85 else C_WARN if fraction >= 0.6 else C_OK )


def gauge( fraction: float, cells = 5 ) -> tuple:
    """`██▌` and `··`: the part filled, in eighths, and the part empty -- no brackets, which some fonts draw
    as tall bars."""
    eighths = round( max( 0.0, min( 1.0, fraction ) ) * cells * 8 )
    full, part = divmod( eighths, 8 )
    filled = "█" * full + ( " ▏▎▍▌▋▊▉"[ part ] if part else "" )
    return filled, "·" * ( cells - len( filled ) )


def _meters( win, y, left, at, until, meters, look ) -> int:
    """`cpu ██▌·· 43%` for each gauge, from column `at` and before `until`. -> the column after the last one."""
    x = at
    for name, frac in meters:
        frac = max( 0.0, min( 1.0, frac ) )
        filled, empty = gauge( frac )
        piece = len( name ) + 1 + 5 + 4
        if x + piece > until:                          # the detail keeps its room
            break
        put( win, y, left + x, name, len( name ), look( dim() ) )
        put( win, y, left + x + len( name ) + 1, filled, len( filled ), look( level( frac ) ) )
        put( win, y, left + x + len( name ) + 1 + len( filled ), empty, len( empty ), look( dim() ) )
        put( win, y, left + x + len( name ) + 6, f"{frac * 100:3.0f}%", 4, look( level( frac ) ) )
        x += piece + 1
    return x


def _colour( row ):
    if row.kind == "dormant":
        return dim()
    if row.kind == "machine":
        return curses.color_pair( C_TITLE ) | curses.A_BOLD
    if row.kind in ( "group", "day" ):          # a history, a day: headings, not as loud as what they hold
        return dim() | ( curses.A_BOLD if row.kind == "day" else 0 )
    if row.kind == "chead":
        return curses.color_pair( C_TITLE ) | curses.A_BOLD
    if row.kind == "broken" or row.mark in ( "FAIL", "lost", "orph" ):
        return curses.color_pair( C_BAD )
    if row.mark in ( "ok", "run" ):
        return curses.color_pair( C_OK )
    if row.mark in ( "skip", "wait" ):
        return curses.color_pair( C_WARN )
    if row.kind in ( "note", "more", "head" ):
        return dim()
    return 0


def draw_pane( win, pane, active ):
    draw_box( win, pane.box, pane.title, active )
    draw_rows( win, pane.rows, ( pane.top, pane.cursor ), pane.inner, active, pane.plain )
