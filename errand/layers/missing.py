"""`Missing`: an environment that cannot be reached from here, declared anyway so that it says why.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import Command, Context
from .families import Layer


@dataclass
class Missing( Layer ):
    """Stands for what this machine lacks to reach the environment: a host nobody named, a tool not installed.

    A package that declares environments for its users ( a provider ) declares this one rather than nothing: `errand envs`
    lists it as `missing`, and selecting it stops before anything is pushed or built, with `what` ( what is lacking ) and
    `hint` ( what to write, and where ).

        errand.envs[ "mylib-macos" ] = errand.Env( [ errand.Missing( "a Mac reachable by ssh",
                                                                     hint = "name one in mylib-hosts.py" ) ] )
    """
    what: str
    hint: str | None = None

    def describe( self ):
        return f"missing: {self.what}"

    def message( self, name = "" ) -> str:
        head = f"{name}: " if name else ""
        return f"{head}needs {self.what}" + ( f"\n  {self.hint}" if self.hint else "" )

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        # Only reached when something went around the refusal of `_targets`.
        raise RuntimeError( self.message() )


def missing_of( stack ):
    return next( ( l for l in stack if isinstance( l, Missing ) ), None )
