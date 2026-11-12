"""Rows, and the panes that hold them: a cursor, a scroll, and keeping the cursor on the same row
when the rows are rebuilt.
"""
from __future__ import annotations

import curses


PAGES = ( "cases", "runs" )

# **The letters are the search, so the verbs are the function keys.** There are
# twelve of them; a screen that has to be typed at cannot also be driven by
# letters, and a verb on a function key is a verb nothing else can claim.
def _f( n ):
    return curses.KEY_F0 + n


# ── rows and panes ───────────────────────────────────────────────────────────

class Row:
    __slots__ = ( "label", "detail", "kind", "data", "depth", "checked", "mark", "open",
                  "hits" )

    def __init__( self, label, detail = "", *, kind = "plain", data = None, depth = 0,
                  checked = None, mark = None, open = None, hits = ( ) ):
        self.label, self.detail, self.kind, self.data = label, detail, kind, data
        self.depth   = depth
        self.checked = checked      # None: not something that can be ticked
        self.mark    = mark         # what stands where the box would be
        self.open    = open         # None: not something that can be folded
        # Which letters of the label answered the search. Shown in bold: a list
        # that says WHY a row is in it is one you can trust after a glance.
        self.hits    = tuple( hits )


class Pane:
    """A titled box of rows, with its own cursor and its own scroll."""

    def __init__( self, name, title ):
        self.name, self.title = name, title
        self.rows   : list = [ ]
        self.cursor = 0
        self.top    = 0
        self.box    = ( 0, 0, 0, 0 )      # y, x, height, width
        self.plain  = False               # text, rather than a list of choices

    @property
    def inner( self ):
        y, x, h, w = self.box
        return y + 1, x + 1, max( 0, h - 2 ), max( 0, w - 2 )

    def current( self ):
        return self.rows[ self.cursor ] if 0 <= self.cursor < len( self.rows ) else None

    def move( self, delta ):
        if self.rows:
            self.cursor = max( 0, min( len( self.rows ) - 1, self.cursor + delta ) )
        self.reveal()

    def scroll( self, delta ):
        """The wheel moves the window and not the cursor: looking is not
        choosing, and a list that jumped its selection under the pointer would
        be choosing for you."""
        height = self.inner[ 2 ]
        self.top = max( 0, min( max( 0, len( self.rows ) - height ), self.top + delta ) )

    def reveal( self ):
        height = self.inner[ 2 ]
        if height:
            self.top = max( self.cursor - height + 1, min( self.top, self.cursor ) )
            self.top = max( 0, min( self.top, max( 0, len( self.rows ) - height ) ) )

    def holds( self, y, x ):
        by, bx, h, w = self.box
        return by <= y < by + h and bx <= x < bx + w

    def row_at( self, y ):
        index = self.top + ( y - self.inner[ 0 ] )
        return index if 0 <= index < len( self.rows ) else None

    def keep( self, rows, key ):
        """Replace the rows, leaving the cursor on the same thing when it is
        still there -- these lists are rebuilt twice a second."""
        was = self.current()
        self.rows = rows
        if was is not None:
            for i, row in enumerate( rows ):
                if key( row ) == key( was ):
                    self.cursor = i
                    break
            else:
                self.cursor = min( self.cursor, max( 0, len( rows ) - 1 ) )
        else:
            self.cursor = min( self.cursor, max( 0, len( rows ) - 1 ) )
        # The scroll is NOT brought back to the cursor here. These lists are
        # rebuilt twice a second, and a rebuild that dragged the view back to
        # the selection would undo, half a second later, every turn of the
        # wheel -- which is exactly what a wheel is not for.
        self.top = max( 0, min( self.top, max( 0, len( rows ) - self.inner[ 2 ] ) ) )
