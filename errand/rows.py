"""Rows: a line a run says once per step, whose pieces errand aligns with those of the lines before it.

    errand.row( "adjust", [ "ctr=1", "pts=1250", "r=0.005" ], [ "loss 35.2", "→ 0.0035" ], [ "3.4 s" ] )

draws, under the lines of the same case,

    │ add_balls   n=1250 pts=1250 r=0.005
    │ adjust      ctr=1 pts=1250 r=0.005   loss 35.2    → 0.0035   3.4 s
    │ adjust      ctr=1 pts=1250 r=0.00706 loss 0.00347 → 0.00346  2.7 s

The step ( the head ) in a colour of its own, one column for the heads of the case; then the groups, two
spaces apart, their pieces one space apart. A piece takes the column of the same piece in the rows of the
same head: same group, same name ( before `=` ), else same place in the group. A column only grows: on a
terminal, the rows already drawn are drawn again when one does ( `cli.render` ).

The line written carries both: an escape no terminal shows, `MARK { json } END`, then the line as it reads
without errand -- what a file of the output shows. Outside errand ( no `$ERRAND_STEPS` ), only the latter.
Pieces may hold colours ( SGR ): they do not count in the widths.

Imported by `errand` itself: standard library only, and cheap."""
from __future__ import annotations

import json
import os
import re
import sys

MARK = "\x1b]errand-row;"           # an OSC: terminals read up to its end and show nothing
END  = "\x07"
_SGR = re.compile( r"\x1b\[[0-9;]*m" )


def visible( text: str ) -> int:
    return len( _SGR.sub( "", text ) )


def _groups( groups ) -> list:
    return [ [ str( g ) ] if isinstance( g, str ) else [ str( c ) for c in g ] for g in groups ]


def plain( head: str, groups ) -> str:
    """The row as it reads unaligned: `head  a b  c d`."""
    return "  ".join( [ str( head ) ] + [ " ".join( g ) for g in _groups( groups ) if g ] )


def text( head: str, *groups ) -> str:
    """The line `row` writes, without its end: marked under errand."""
    groups = _groups( groups )
    shown = plain( head, groups )
    if not os.environ.get( "ERRAND_STEPS" ):
        return shown
    return MARK + json.dumps( [ str( head ), groups ] ) + END + shown


def row( head: str, *groups, file = None ):
    """A row ( see the module ): `head`, then groups of pieces ( a string alone is a group of one )."""
    print( text( head, *groups ), file = file or sys.stdout, flush = True )


def parse( line: str ):
    """`( head, groups )` of a line `text` wrote, else None."""
    if not line.startswith( MARK ):
        return None
    body, sep, _ = line[ len( MARK ) : ].partition( END )
    if not sep:
        return None
    try:
        head, groups = json.loads( body )
        return str( head ), _groups( groups )
    except ( ValueError, TypeError ):
        return None


def _key( index: int, piece: str ):
    name, eq, _ = _SGR.sub( "", piece ).partition( "=" )
    return name if eq and name and " " not in name else index


class Table:
    """The widths of the columns of a case's rows: they only grow."""

    def __init__( self ):
        self.head = 0
        self.widths: dict = { }

    def add( self, head: str, groups ) -> bool:
        """-> whether a column grew that a row before this one uses."""
        grew = False
        if visible( head ) > self.head:
            grew, self.head = self.head > 0, visible( head )
        for g, group in enumerate( groups ):
            for i, piece in enumerate( group ):
                k = ( head, g, _key( i, piece ) )
                if visible( piece ) > self.widths.get( k, 0 ):
                    grew = grew or k in self.widths
                    self.widths[ k ] = visible( piece )
        return grew

    def draw( self, head: str, groups, colour = "" ) -> str:
        """The row at the widths known now, the head in `colour` ( an SGR ), no space at its end."""
        cells = [ ]
        for g, group in enumerate( groups ):
            for i, piece in enumerate( group ):
                width = self.widths.get( ( head, g, _key( i, piece ) ), 0 )
                cells.append( ( piece, width, "  " if i == 0 else " " ) )
        line = f"{colour}{head}\033[0m" if colour else head
        if cells:
            line += " " * ( self.head - visible( head ) )
        for n, ( piece, width, sep ) in enumerate( cells ):
            last = n == len( cells ) - 1
            line += sep + piece + ( "" if last else " " * ( width - visible( piece ) ) )
        return line
