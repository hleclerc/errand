"""The step of a case as `errand run` shows it ( ADR 0010 ): one line at the bottom of the terminal.

    Footer      the line: kept at the bottom by a scroll region, the output scrolls above it
    Followed    a case's journal, followed while it runs: its line goes to the footer when the
                terminal is here, or out as a mark when a session runs elsewhere ( `sessions.follow`
                draws it there )
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
from pathlib import Path

from .. import steps

POLL = 0.25               # seconds between two looks at a journal


_SGR = re.compile( r"\x1b\[[0-9;]*m" )


def fit( text: str, cols: int ) -> str:
    """`text` cut to `cols` visible columns, its colors kept and closed."""
    out, seen, i = [ ], 0, 0
    while i < len( text ) and seen < cols:
        m = _SGR.match( text, i )
        if m:
            out.append( m.group() )
            i = m.end()
            continue
        out.append( text[ i ] )
        seen += 1
        i += 1
    return "".join( out ) + ( "\033[0m" if _SGR.search( text ) else "" )


class Footer:
    """Lines at the bottom of a terminal. The rows above them are a scroll region: whatever writes
    to the terminal, this process or a child, scrolls there and leaves the lines alone."""

    def __init__( self, stream = None ):
        self.stream = stream or sys.__stdout__
        self.rows   = None                  # the terminal's height when the region was set
        self.n      = 0                     # how many lines the region leaves below it
        self.lock   = threading.Lock()

    @staticmethod
    def usable( stream = None ) -> bool:
        stream = stream or sys.__stdout__
        try:
            return stream.isatty() and os.environ.get( "TERM", "dumb" ) != "dumb"
        except ( AttributeError, ValueError ):
            return False

    def show( self, text: str | None ):
        self.show_lines( [ text ] if text else [ ] )

    def show_lines( self, lines: list ):
        """These lines at the bottom, the region above made to leave room for exactly them."""
        if not lines:
            return self.clear()
        with self.lock:
            cols, rows = shutil.get_terminal_size()
            n = max( 1, min( len( lines ), rows - 2 ) )
            w = self.stream
            if self.rows != rows or self.n != n:
                grow = n if self.rows is None or self.rows != rows else max( 0, n - self.n )
                if self.rows == rows and n < self.n:
                    for r in range( rows - self.n + 1, rows - n + 1 ):      # rows given back to the output
                        w.write( f"\0337\033[{r};1H\033[2K\0338" )
                if grow:
                    w.write( "\n" * grow )                                 # rows for the lines
                # Setting the region moves the cursor: it is saved and put back around it.
                w.write( f"\0337\033[1;{rows - n}r\0338" )
                if grow:
                    w.write( f"\033[{grow}A" )
                self.rows, self.n = rows, n
            for i, line in enumerate( lines[ -n : ] ):
                w.write( f"\0337\033[{rows - n + 1 + i};1H\033[2K{fit( line, cols - 1 )}\0338" )
            w.flush()

    def clear( self ):
        with self.lock:
            if self.rows is None:
                return
            for r in range( self.rows - self.n + 1, self.rows + 1 ):
                self.stream.write( f"\0337\033[{r};1H\033[2K\0338" )
            self.stream.write( "\0337\033[r\0338" )
            self.stream.flush()
            self.rows, self.n = None, 0


def mark( text: str | None ):
    """The line of a case, said to the side that drives this session, outside the case's output."""
    from ..agents.ops import MARK
    out = sys.__stdout__
    out.flush()
    out.write( MARK + json.dumps( { "op": "step", "line": text } ) + "\n" )
    out.flush()


def want( what: dict ):
    """A file the case wants and cannot download ( `errand.download`, ADR 0013 ): asked of the side that
    drives this session, which answers in the file the case waits on."""
    from ..agents.ops import MARK
    out = sys.__stdout__
    out.flush()
    out.write( MARK + json.dumps( { "op": "want", **what } ) + "\n" )
    out.flush()


def view( path: str ):
    """A file the case shows ( `errand.view` ), by its path from the copy's root: the side that drives
    this session brings it back at once and says where it opens there ( `views.Views` )."""
    from ..agents.ops import MARK
    out = sys.__stdout__
    out.flush()
    out.write( MARK + json.dumps( { "op": "view", "path": path } ) + "\n" )
    out.flush()


class Followed:
    """`with Followed( journal, say ):` -- while the case runs, its line goes to `say` when it changes;
    `say( None )` when it ends. `want`: told each file the case asks up the chain for ( ADR 0013 ).
    `view`: told each view the case names ( `errand.view` ), from `root` when it is under it ( the copy's
    root, the same on both sides ), else absolute."""

    def __init__( self, journal, say, want = None, view = None, root = None ):
        self.journal, self.say, self.want, self.view = journal, say, want, view
        self.root   = Path( root ).resolve() if root is not None else None
        self.read_to = 0                    # how far the journal was read for wants
        self.stop   = threading.Event()
        self.seen   = None                  # ( size, mtime ) of the journal at the last look
        self.said   = None
        self.thread = threading.Thread( target = self._loop, daemon = True )

    def __enter__( self ):
        self.thread.start()
        return self

    def __exit__( self, *exc ):
        self.stop.set()
        self.thread.join()
        if self.view is not None:
            try:
                self.look()                 # a view named just before the end is still said
            except Exception:
                pass
        if self.said:
            self.say( None )

    def _loop( self ):
        while not self.stop.wait( POLL ):
            try:
                self.look()
            except Exception:
                pass                        # the line is a courtesy: never the case's failure

    def look( self ):
        try:
            st = os.stat( self.journal )
        except OSError:
            return
        if ( st.st_size, st.st_mtime ) == self.seen:
            return
        self.seen = ( st.st_size, st.st_mtime )
        if ( self.want is not None or self.view is not None ) and st.st_size > self.read_to:
            with open( self.journal, "rb" ) as f:
                f.seek( self.read_to )
                data = f.read( st.st_size - self.read_to )
            cut = data.rfind( b"\n" )                       # whole lines only: the last may be under way
            self.read_to += cut + 1
            for e in steps.parse( data[ : cut + 1 ] ):
                if isinstance( e.get( "want" ), dict ) and self.want is not None:
                    self.want( e[ "want" ] )
                if isinstance( e.get( "view" ), str ) and self.view is not None:
                    self.view( self.view_path( e[ "view" ] ) )
        text = steps.line( steps.summary( self.journal ) )
        if text and text != self.said:
            self.said = text
            self.say( text )

    def view_path( self, view: str ) -> str:
        """A view as the side that drives the session reads it: from the copy's root when it is under it."""
        p = Path( view )
        if not p.is_absolute():
            p = Path( self.journal ).parent / p
        p = p.resolve()
        if self.root is not None and ( p == self.root or self.root in p.parents ):
            return p.relative_to( self.root ).as_posix()
        return str( p )
