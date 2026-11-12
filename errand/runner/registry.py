"""`errand.runners`: the dict of runners by name, filled with the ones errand comes with.
"""
from __future__ import annotations

from .base import Runner
from .own import Errand
from .pytest import Pytest
from .catch2 import Catch2
from .cargo import Cargo
from .files import Executable, Python


class Runners( dict ):
    """`errand.runners`: name -> runner.

    `errand.runners[ "bench" ] = errand.Pytest( … )` adds an instance `-r bench`
    picks; `replace` puts a configured runner in place of the built-in one of
    its kind, rather than beside it, where the two would tie over every file."""

    def __setitem__( self, name, runner ):
        if not isinstance( runner, Runner ):
            raise TypeError( f"runners[ {name!r} ] must be a runner, not {type( runner ).__name__}" )
        runner.name = name
        super().__setitem__( name, runner )

    def update( self, other = ( ), **kw ):
        for k, v in dict( other, **kw ).items():
            self[ k ] = v

    def replace( self, runner ):
        """-> runner, under the name of the kind it replaces."""
        kind = type( runner )
        names = [ n for n, r in self.items() if type( r ) is kind ]
        for n in names:
            del self[ n ]
        self[ names[ 0 ] if names else type( runner ).name ] = runner
        return runner

    def entry_runners( self ):
        return [ r for r in self.values() if r.takes_entries ]


def defaults( ) -> dict:
    """The runners that come with errand, by name."""
    return { r.name: r for r in ( Errand(), Pytest(), Catch2(), Cargo(), Python(), Executable() ) }
