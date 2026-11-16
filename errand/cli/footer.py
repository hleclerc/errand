"""The step of a case as `errand run` shows it ( ADR 0010 ): one line at the bottom of the terminal.

    Footer      the line: kept at the bottom by a scroll region, the output scrolls above it
    Followed    a case's journal, followed while it runs: its line goes to the footer when the
                terminal is here, or out as a mark when a session runs elsewhere ( `sessions.follow`
                draws it there )
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading

from .. import steps

POLL = 0.25               # seconds between two looks at a journal


class Footer:
    """One line at the bottom of a terminal. The rows above it are a scroll region: whatever writes
    to the terminal, this process or a child, scrolls there and leaves the line alone."""

    def __init__( self, stream = None ):
        self.stream = stream or sys.__stdout__
        self.rows   = None                  # the terminal's height when the region was set
        self.lock   = threading.Lock()

    @staticmethod
    def usable( stream = None ) -> bool:
        stream = stream or sys.__stdout__
        try:
            return stream.isatty() and os.environ.get( "TERM", "dumb" ) != "dumb"
        except ( AttributeError, ValueError ):
            return False

    def show( self, text: str | None ):
        if not text:
            return self.clear()
        with self.lock:
            cols, rows = shutil.get_terminal_size()
            w = self.stream
            if self.rows != rows:
                if self.rows is None:
                    w.write( "\n" )                                # a row for the line
                # Setting the region moves the cursor: it is saved and put back around it.
                w.write( f"\0337\033[1;{rows - 1}r\0338" )
                if self.rows is None:
                    w.write( "\033[1A" )
                self.rows = rows
            w.write( f"\0337\033[{rows};1H\033[2K{text[ : cols - 1 ]}\0338" )
            w.flush()

    def clear( self ):
        with self.lock:
            if self.rows is None:
                return
            self.stream.write( f"\0337\033[{self.rows};1H\033[2K\033[r\0338" )
            self.stream.flush()
            self.rows = None


def mark( text: str | None ):
    """The line of a case, said to the side that drives this session, outside the case's output."""
    from ..agents.ops import MARK
    out = sys.__stdout__
    out.flush()
    out.write( MARK + json.dumps( { "op": "step", "line": text } ) + "\n" )
    out.flush()


class Followed:
    """`with Followed( journal, say ):` -- while the case runs, its line goes to `say` when it changes;
    `say( None )` when it ends."""

    def __init__( self, journal, say ):
        self.journal, self.say = journal, say
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
        text = steps.line( steps.summary( self.journal ) )
        if text and text != self.said:
            self.said = text
            self.say( text )
