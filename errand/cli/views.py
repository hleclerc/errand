"""The views of a run elsewhere ( `errand.view` ), brought back as they are named, not at its end.

A run over there names a file worth looking at; its session says it here as a mark ( `footer.view` ),
by its path from the copy's root. `Views` brings that one file back at once, into the project here where
the run's own coming back would put it, and says where it opens: `OUTPUT: file://...`, once per file, a
link a terminal opens. Its date is kept, so the run's coming back finds it as it is and leaves it.

A view named again while it is on its way is brought back once more after: the last state always comes,
never one transfer per call. A run on this machine needs nothing brought: only said.
"""
from __future__ import annotations

import threading
from pathlib import Path

from .style import warn


class Views:
    """`Views( local_root, pull, where )`: `pull( rel )` brings the file `rel` ( from the copy's root ) into
    `local_root`, None when the copy is the project here. Called with each `view` mark."""

    def __init__( self, local_root, pull = None, where: str = "", say = None ):
        self.root, self.pull, self.where = Path( local_root ), pull, where
        self.say = say or ( lambda s: print( s, flush = True ) )
        self.lock = threading.Lock()
        self.busy: dict = { }            # path -> named again while on its way
        self.said: set = set()
        self.threads: list = [ ]

    def __call__( self, mark: dict ):
        path = mark.get( "path" )
        if not path:
            return
        if self.pull is None or Path( path ).is_absolute():
            # here, or outside the copy over there ( nothing here to bring it to ): said as it is
            self._said( path if self.pull is None else None, path )
            return
        with self.lock:
            if path in self.busy:
                self.busy[ path ] = True
                return
            self.busy[ path ] = False
        t = threading.Thread( target = self._bring, args = ( path, ), daemon = True )
        self.threads.append( t )
        t.start()

    def _bring( self, path: str ):
        while True:
            try:
                self.pull( path )
                self._said( path, None )
            except Exception as err:
                with self.lock:
                    first = path not in self.said
                    self.said.add( path )
                if first:
                    self.say( warn( f"  view {path}: not brought back from {self.where} ( {err} )" ) )
            with self.lock:
                if not self.busy.get( path ):
                    del self.busy[ path ]
                    return
                self.busy[ path ] = False

    def _said( self, here: str | None, there: str | None ):
        key = here or there
        with self.lock:
            if key in self.said:
                return
            self.said.add( key )
        if here is not None:
            p = Path( here )
            self.say( f"OUTPUT: { ( p if p.is_absolute() else self.root / p ).absolute().as_uri() }" )
        else:
            self.say( f"OUTPUT: {self.where}:{there}" )

    def wait( self, timeout = 60.0 ):
        """The views on their way, arrived: before the run's own coming back, and before this process ends."""
        for t in list( self.threads ):
            t.join( timeout )
