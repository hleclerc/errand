"""What a layer is: `Layer` and its families, and the `Artefact` mixin for what is built.
"""
from __future__ import annotations

import abc

from .base import Command, Context


#
# Every layer says what it is by what it derives from; an incomplete one fails
# when it is declared, not on its first run.
#
#     Layer                  describe( ); wrap( cmd, ctx ), changing nothing by default
#     ├── Overlay            wraps the command's surroundings           Vars, Module, Nix, Guix
#     ├── Launcher           starts the command, as many times as asked Mpi
#     ├── Interpreter        chooses `python`                            Venv, Micromamba, Uv
#     │   └── Container      + an image, mounts                         Apptainer, Docker, Podman
#     ├── Scheduler          an allocation                               Slurm
#     └── Gateway            leads elsewhere: run( inner, cmd, ctx )     Ssh, Windows
#     Artefact ( mixin )     a built thing: spec, probe, build, stamp   Venv, Micromamba, Uv, containers
#
# `Preload` is a Layer of its own: it changes no command, only how sessions start.

class Layer( abc.ABC ):
    when = None                    # a condition: an expression over the tags and `phase`

    @abc.abstractmethod
    def describe( self ) -> str:
        """What it is, in a few words, for `errand envs` and the arrow of a stack."""

    def wrap( self, cmd: "Command", ctx: "Context" ) -> "Command":
        return cmd


class Overlay( Layer ):
    """The command's surroundings: variables, a module, a shell of packages."""

    @abc.abstractmethod
    def wrap( self, cmd, ctx ):
        ...


class Launcher( Layer ):
    """How the command is started several times: ranks."""


class Interpreter( Layer ):
    """Which `python` runs: the first word of the command, replaced ( `under` )."""

    @abc.abstractmethod
    def wrap( self, cmd, ctx ):
        ...


class Container( Interpreter ):
    """An image the command runs in, with its own interpreter."""


class Scheduler( Layer ):
    """An allocation of a batch system: waited for, or submitted ( `--batch` )."""

    @abc.abstractmethod
    def wrap( self, cmd, ctx ):
        ...


class Gateway( Layer ):
    """Leads elsewhere: the layers after it run there ( `run` takes over from `wrap` )."""

    def wrap( self, cmd, ctx ):
        raise RuntimeError( f"{type( self ).__name__} must be the first layer of an environment" )

    @abc.abstractmethod
    def run( self, inner, cmd, ctx, pull = None, echo = print ) -> int:
        ...


class Artefact( abc.ABC ):
    """A layer that owns something built ( ADR 0004 ): what it is made from, whether it is there,
    how to make it, and what came out. Optional: `probe_shell` ( the same question, as a shell line for
    wherever it lives ), `stamp_shell`, `kept`, `aside`, `abandon`, `made`, `identity`."""

    @abc.abstractmethod
    def spec( self, ctx ) -> list:
        """What it is built from: what its fingerprint is taken of."""

    @abc.abstractmethod
    def probe( self, ctx ) -> bool:
        """Is it there?"""

    def stamp_shell( self, ctx ) -> str:
        """A shell line saying what came out ( a date, a size, an id ); nothing to say by default."""
        return "true"

    @abc.abstractmethod
    def build( self, ctx ) -> list:
        """The steps that make it: shell lines, or callables."""


def is_scheduler( layer ) -> bool:
    """A layer that puts the command in an allocation somebody else grants."""
    return isinstance( layer, Scheduler )


def batch_of( stack ):
    return next( ( l for l in stack if is_scheduler( l ) ), None )
