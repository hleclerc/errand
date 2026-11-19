"""Where a run goes, as one line before its cases ( ADR 0016 ): `▸ lmo → micromamba lmo-torch`, the layers
in their order, and on the right what it took to get there -- drawn live while it is under way, then kept
with its numbers. What the sync says meanwhile goes under it, behind a `┆`, in context.

    ▸ lmo → micromamba lmo-torch                         ↑ 126 files · 1.1 MB · 0.8 s
      ┆ data/raw.h5: appeared on lmo ( 2026-11-19 10:02:11 ), not in the project -- moved aside
    ▸ pencil (lmo-torch)  exp_2d_real.py:70 · n=5000
      │ …
      ╰ PASS pencil  14.2 s
      ↓ 3 files · 12 kB · 0.4 s

The coming back has a line of its own, the same way, under the last case ( `Place( back = True )` ).
While a `Place` is open, `bottom.working` draws on it rather than at the bottom of the terminal.
"""
from __future__ import annotations

import shutil
import sys
import threading
import time

from .style import dim, warn

current = None            # the place line open: what `bottom.working` and `drive.say` draw on
drawn = False             # a place line was drawn in this process: the cases' banner need not say where


def title( env, phase = "run" ) -> str:
    """`lmo → micromamba lmo-torch`: the layers of `env`, from the outside in; a stack that does not
    leave this machine starts with its name."""
    from ..layers import base as L
    parts, local = [ ], True
    for layer in env.stack_for( phase ):
        said = layer.describe()
        if said in ( "", "here" ):
            continue
        kind, _, arg = said.partition( ":" )
        if kind == "ssh":
            local = False
            parts.append( arg )
        else:
            parts.append( f"{kind} {arg}".strip() )
    if local:
        import socket
        parts.insert( 0, socket.gethostname().split( "." )[ 0 ] )
    return " → ".join( parts )


def _size( n ) -> str:
    for unit in ( "B", "kB", "MB", "GB" ):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000


class Place:
    """`with Place( text ):` -- the line drawn, what is under way on its right; its numbers when it ends."""

    def __init__( self, text: str, back = False, out = None ):
        self.text, self.back = text, back
        self.out = out or sys.stdout
        try:
            self.live = self.out.isatty()
        except ( AttributeError, ValueError ):
            self.live = False
        self.doing = None                  # ( text, since ) of what is under way
        self.records = [ ]                 # what crossed ( `bottom.Work.record` )
        self.notes = [ ]                   # what was said meanwhile, under the line when it is done
        self.started = time.time()
        self.lock = threading.Lock()
        self.stop = threading.Event()

    # -- the line ---------------------------------------------------------------

    def _left( self ) -> str:
        if self.back:
            return f"  {dim( '↓ ' + self.text )}"
        from .render import PLACE, RESET, colors_on
        return f"{PLACE}▸ {self.text}{RESET}" if colors_on( self.out ) else f"▸ {self.text}"

    def _right( self, done: bool ) -> str:
        if not done:
            if self.doing is None:
                return ""
            what, since = self.doing
            return f"{what} · {time.time() - since:.0f} s"
        files = sum( r.get( "files", 0 ) for r in self.records )
        size = sum( r.get( "bytes", 0 ) for r in self.records )
        took = time.time() - self.started
        said = [ f"{files} file{'s' if files != 1 else ''}" ] if files else [ ]
        if size:
            said.append( _size( size ) )
        if took >= 0.05:
            said.append( f"{took:.1f} s" )
        arrow = "" if self.back else "↑ "
        return arrow + " · ".join( said ) if said else ""

    def _line( self, done: bool ) -> str:
        left, right = self._left(), self._right( done )
        if self.back:
            right = right.removeprefix( "↓ " )
            return "  " + dim( f"↓ {right}" if right else "↓ …" )
        if not right:
            return left
        visible = len( _plain( left ) )
        width = shutil.get_terminal_size( ( 100, 24 ) ).columns
        gap = max( 2, min( width, 120 ) - 1 - visible - len( right ) )
        return left + " " * gap + dim( right )

    def _draw( self ):
        with self.lock:
            if self.live:
                self.out.write( "\r\x1b[K" + self._line( False ) )
                self.out.flush()

    # -- what is said on it ------------------------------------------------------

    def doing_now( self, text: str | None ):
        """What is under way, on the right, with the time it takes ( `bottom.working` )."""
        self.doing = ( text, time.time() ) if text else None
        self._draw()

    def crossed( self, record: dict ):
        self.records.append( record )

    def note( self, text: str, tone = dim ):
        """Said while it is under way: under the line, once it is done."""
        self.notes.append( ( text.strip(), tone ) )

    # -- open, close -------------------------------------------------------------

    def __enter__( self ):
        global current, drawn
        current = self
        if not self.back:
            drawn = True
        if self.live:
            self._draw()

            def tick():
                while not self.stop.wait( 0.5 ):
                    if self.doing is not None:
                        self._draw()

            threading.Thread( target = tick, daemon = True ).start()
        return self

    def __exit__( self, *exc ):
        global current
        self.stop.set()
        current = None
        if self.back and not self.records and not self.notes:
            if self.live:                                 # nothing came back: no line
                with self.lock:
                    self.out.write( "\r\x1b[K" )
                    self.out.flush()
            return False
        with self.lock:
            self.out.write( ( "\r\x1b[K" if self.live else "" ) + self._line( True ) + "\n" )
            for text, tone in self.notes:
                self.out.write( f"  {dim( '┆' )} {tone( text )}\n" )
            self.out.flush()
        return False


def _plain( s: str ) -> str:
    import re
    return re.sub( r"\x1b\[[0-9;]*m", "", s )


def say( text: str, tone = dim ) -> bool:
    """`text` under the place line open, if one is. -> whether it was taken."""
    if current is None:
        return False
    current.note( text, tone )
    return True


def warned( text: str ) -> bool:
    return say( text, warn )
