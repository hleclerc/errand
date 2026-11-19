"""Overlays: the command's surroundings -- variables, a module, a Nix or Guix shell.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from .base import Command, Context
from .families import Overlay


@dataclass
class Vars( Overlay ):
    """Environment variables for the child.

    `values` may be a callable taking the selected tags, which is how a single
    environment covers a whole dimension instead of being split into one per
    value: `Vars( lambda t: { "FTYPE": t.get( "fp", "64" ) } )`.

    `{root}` in a value is the project's root where the command runs: its copy on a machine reached by `Ssh`, its
    copy in a guest ( `E:\\Projects-rsync` ), itself here -- `Vars( { "PYTHONPATH": "{root}/loom/src" } )`. Nothing
    else between braces is touched.
    """
    values: dict | object

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        values = self.values( ctx.tags ) if callable( self.values ) else self.values
        root = str( ctx.root )
        return Command( cmd.argv, { **cmd.env, **{ k: str( v ).replace( "{root}", root ) for k, v in values.items() } } )

    def describe( self ):
        return "vars"


@dataclass
class Nix( Overlay ):
    """`nix develop <flake> -c …`."""
    flake: str = "."
    shell: str | None = None

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        target = f"{self.flake}#{self.shell}" if self.shell else self.flake
        return Command( [ "nix", "develop", target, "-c", *cmd.argv ], cmd.env )

    def describe( self ):
        return f"nix:{self.flake}"


@dataclass
class Guix( Overlay ):
    """`guix shell -m <manifest> -- …`."""
    manifest: str | None = None
    packages: list = field( default_factory = list )

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        spec = [ "-m", self.manifest ] if self.manifest else list( self.packages )
        return Command( [ "guix", "shell", *spec, "--", *cmd.argv ], cmd.env )

    def describe( self ):
        return f"guix:{self.manifest or ' '.join( self.packages )}"


@dataclass
class Module( Overlay ):
    """Lmod / environment modules -- how a cluster picks a toolchain.

    `module` is a shell function, not a program, so this has to go through a
    login shell to exist at all. That is the whole layer.
    """
    names: list

    def __init__( self, *names ):
        self.names = list( names )

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        loads = " && ".join( f"module load {shlex.quote( n )}" for n in self.names )
        # `exec` takes a program, not assignments: `env` sets them ( after the
        # login shell's profile, which would otherwise be free to undo them )
        run = f"env {cmd.shell()}" if cmd.env else cmd.shell()
        return Command( [ "sh", "-lc", f"{loads} && exec {run}" ], { } )

    def describe( self ):
        return "module:" + ",".join( self.names )
