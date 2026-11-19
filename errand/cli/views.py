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
import time
from pathlib import Path

from .style import warn


class Views:
    """`Views( local_root, pull, where )`: `pull( rel )` brings the file `rel` ( from the copy's root ) into
    `local_root`, None when the copy is the project here. Called with each `view` mark."""

    def __init__( self, local_root, pull = None, where: str = "", say = None ):
        self.root, self.pull, self.where = Path( local_root ), pull, where
        if say is None:
            from .render import Renderer
            say = Renderer().view               # on a line of its own, among the cases ( ADR 0016 )
        self.say = say
        self.lock = threading.Lock()
        self.busy: dict = { }            # path -> named again while on its way
        self.said: set = set()
        self.threads: list = [ ]
        self.renders: dict = { }         # path -> the renderer of the session that named it
        self.idle = threading.Condition( self.lock )

    def __call__( self, mark: dict, render = None ):
        """`render`: the session's renderer ( `render.Renderer.view` ): the link inside its case."""
        path = mark.get( "path" )
        if not path:
            return
        if render is not None:
            self.renders[ path ] = render
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
                    self.idle.notify_all()
                    return
                self.busy[ path ] = False

    def settle( self, timeout = 20.0 ):
        """The views on their way, arrived -- before a case's end is drawn, so that its link is inside it."""
        end = time.monotonic() + timeout
        with self.lock:
            while self.busy and time.monotonic() < end:
                self.idle.wait( max( 0.0, end - time.monotonic() ) )

    def _said( self, here: str | None, there: str | None ):
        key = here or there
        with self.lock:
            if key in self.said:
                return
            self.said.add( key )
        if here is not None:
            p = Path( here )
            link = ( p if p.is_absolute() else self.root / p ).absolute().as_uri()
        else:
            link = f"{self.where}:{there}"
        render = self.renders.get( key )
        if render is not None:
            render.view( link )
        else:
            self.say( link )

    def wait( self, timeout = 60.0 ):
        """The views on their way, arrived: before the run's own coming back, and before this process ends."""
        for t in list( self.threads ):
            t.join( timeout )
