"""The `Actions` part of the screen: what a key or a click does.
"""
from __future__ import annotations

from .. import session as S
from .terminal import PRESSED, TRACE, WHEEL, WHEEL_DOWN, WHEEL_UP
from .tree import _id
from .panes import PAGES
from .dialog import Dialog


class Actions:
    """What a key or a click does: move between pages and panes, fold, tick, open, launch."""

    def typed( self, text ):
        self.queries[ self.page ] = text
        self.build_cases() if self.page == "cases" else self.build_runs()

    def show( self, page ):
        self.page, self.active = page, 0

    def turn( self, delta ):
        """The page before, the page after. Two pages and two keys next to each
        other: there is nothing to aim at, only a direction."""
        self.show( PAGES[ ( PAGES.index( self.page ) + delta ) % len( PAGES ) ] )

    def step( self, delta ):
        """tab goes to the next rectangle OF THIS PAGE, and stays there.

        It used to run off the end into the other page; going somewhere by
        pressing the same key until you arrive is not going somewhere. The
        function keys are how you leave: one per rectangle, written in its
        title, one press from wherever you are.
        """
        self.active = ( self.active + delta ) % len( self.panes )

    def open_file( self ):
        row = self.files.current()
        if row is not None and row.kind == "file":
            self.message = S.open_file( row.data ) or f"opening {row.data.name}"
        else:
            self.message = "no file under the cursor"

    def fold( self, row ):
        if row.data[ 0 ] == "node":
            self.folded.symmetric_difference_update( { row.data[ 1 ] } )
        else:
            line = row.data[ 1 ]
            self.opened.symmetric_difference_update( { line } )
            if line in self.opened:
                self.states_for( line, fresh = True )

    def toggle_row( self ):
        row = self.pane().current()
        if row is None:
            return
        if row.open is not None:
            self.fold( row )
        elif row.kind == "case":
            self.ticked.symmetric_difference_update( { _id( row.data ) } )

    def enter( self ):
        pane, row = self.pane(), self.pane().current()
        if row is None:
            return
        if pane is self.cases:
            if row.kind == "case":
                # What was ticked, or what the cursor is on: pressing enter on
                # something is asking for THAT, and having to tick it first to
                # be taken seriously would be a ceremony.
                cases = [ e for e in self.session.entries if _id( e ) in self.ticked ] \
                        or [ row.data ]
                self.dialog = Dialog( self.session, cases )
            elif row.open is not None:
                self.fold( row )
        elif pane is self.runs:
            if row.kind == "group":
                self.fold( row )
            else:
                self.active = self.panes.index( self.files )   # its files are next
        elif pane in ( self.files, self.look ):
            self.open_file()

    def run_again( self ):
        row = self.runs.current()
        if row is None or row.kind != "group":
            self.message = "put the cursor on a command in `runs`"
            return
        self.launch( self.session.args_of( row.data[ 1 ] ) )

    def run_last( self ):
        """The last thing that was run, run again -- from either page, without
        going to look for it. It is the one thing you ask for twice."""
        lines = self.command_lines()
        if not lines:
            self.message = "nothing has been run from here yet"
            return
        self.launch( self.session.args_of( lines[ 0 ] ) )

    def reread( self ):
        self.session.discover()
        self.past.clear()
        self.message = ( f"{len( self.session.entries )} case(s)"
                         + ( f", {len( self.session.broken )} unreadable file(s)"
                             if self.session.broken else "" ) )

    def launch( self, argv ):
        why = self.session.launch( argv )
        self.message = why or self.session.command_line
        if why:
            return
        self.past.clear()
        self.opened.add( self.session.command_line[ len( "errand " ) : ] )
        self.show( "runs" )
        self.runs.cursor = 0

    def mouse( self, y, x, state ):
        if TRACE:
            open( TRACE, "a" ).write( f"mouse y={y} x={x} state={hex(state)} "
                                      f"boxes={[p.box for p in self.panes]}\n" )
        if y == 0 and state & PRESSED:
            for left, right, name in self.tabs:
                if left <= x < right:
                    self.show( name )
            return
        for index, pane in enumerate( self.panes ):
            if not pane.holds( y, x ):
                continue
            if state & WHEEL_UP:
                pane.scroll( -WHEEL )
            elif state & WHEEL_DOWN:
                pane.scroll( WHEEL )
            elif not state & PRESSED:
                return                        # a release, or a button we do not use
            else:
                # Clicking a pane makes it the one the arrows drive: pointing at
                # a thing is as good a way of choosing it as walking to it.
                self.active = index
                where = pane.row_at( y )
                if where is not None:
                    pane.cursor = where
                    row = pane.rows[ where ]
                    # The little triangle and the box are targets of their own,
                    # so clicking one folds or ticks instead of only selecting.
                    column = x - pane.inner[ 1 ] - 2 * row.depth
                    if row.open is not None and column < 2:
                        self.fold( row )
                    elif row.checked is not None and column < 4:
                        self.toggle_row()
            return
