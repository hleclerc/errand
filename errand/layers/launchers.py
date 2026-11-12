"""How the command is started: several ranks ( `Mpi` ), or sessions forked from a process that has
already imported ( `Preload` ).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .base import Command, Context
from .families import Launcher, Layer


class Preload( Layer ):
    """Sessions forked from a process that has already imported ( ADR 0005, step 7 ).

        errand.Preload( "torch", "jax" )      these, imported ahead, and what sessions use ( learn )
        errand.Preload( learn = False )        nothing but what is named

    Each session is a fork of that process: a copy of its own, nothing left over from the one
    before; the project's own modules are always read again. Without this layer, every session is
    a Python started anew. It changes nothing in the command: it says how sessions start.
    """

    def __init__( self, *modules, learn = True, when = None ):
        self.modules, self.learn, self.when = list( modules ), bool( learn ), when

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        return cmd

    def describe( self ):
        return "preload" + ( f":{','.join( self.modules )}" if self.modules else "" )

    def __repr__( self ):
        return f"Preload( {', '.join( map( repr, self.modules ) )}, learn = {self.learn} )"


def preload_of( stack ):
    return next( ( l for l in stack if isinstance( l, Preload ) ), None )


@dataclass
class Mpi( Launcher ):
    """How the place starts several processes of one program: `mpiexec -n N`.

    It does not wrap the command errand runs -- errand runs once, in the place,
    whatever the number of ranks -- but the entries that ask for ranks
    ( `test( …, ranks = 4 )`, `--ranks 4` ): those, and only those, are started
    under the launcher, one process per rank ( `errand.mpi` ).

    Without this layer, the launcher is the `mpiexec` beside the interpreter of
    the place ( the MPI of a conda / micromamba environment ), else the one on
    its PATH. A cluster names its own: `Mpi( "srun", np = "--ntasks" )`.
    """
    launcher: str = "mpiexec"
    np      : str = "-n"                                 # the flag giving the number of processes
    flags   : list = field( default_factory = list )      # e.g. [ "--oversubscribe" ] for Open MPI
    when    : str | None = None

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        return cmd

    def describe( self ):
        return f"mpi:{self.launcher}"
