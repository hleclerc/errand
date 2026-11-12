"""Interpreters: a venv, a micromamba or conda environment, a uv project -- each built and kept current.
"""
from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .base import _install_steps, _quiet, Command, Context, file_stamp, sh, SITE_STAMP, under
from .families import Artefact, Interpreter


@dataclass
class Venv( Interpreter, Artefact ):
    """A specific interpreter: a venv's python, or any installed one."""
    python      : str = "python"
    requirements: str | None = None
    pip         : list = field( default_factory = list )
    create      : bool = False          # make the venv if `python` is inside a missing one
    when        : str | None = None     # a condition: an expression over the tags and `phase`

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        return Command( under( cmd.argv, self.python ), cmd.env )

    def describe( self ):
        return f"venv:{self.python}"

    def spec( self, ctx ):
        return [ self.python, self.requirements and ( ctx.root / self.requirements ), self.pip ]

    def probe( self, ctx ):
        return shutil.which( self.python ) is not None or Path( self.python ).exists()

    def probe_shell( self, ctx ):
        return sh( [ "command", "-v", self.python ] )

    def stamp_shell( self, ctx ):
        return sh( [ self.python, "-c", SITE_STAMP ] )

    def kept( self ):
        return [ str( Path( self.python ).parent.parent ) ] if self.create else [ ]

    def build( self, ctx ):
        steps = [ ]
        if self.create:
            venv_dir = Path( self.python ).parent.parent
            steps.append( sh( [ "python3", "-m", "venv", str( venv_dir ) ] ) )
        steps += _install_steps( [ self.python, "-m", "pip", "install" ], self, ctx )
        return steps


@dataclass
class Micromamba( Interpreter, Artefact ):
    """A micromamba environment, by name."""
    name        : str
    python      : str | None = None
    channels    : list = field( default_factory = lambda: [ "conda-forge" ] )
    packages    : list = field( default_factory = list )
    requirements: str | None = None
    pip         : list = field( default_factory = list )
    root_prefix : str | None = None     # where `-n <name>` resolves; wins over MAMBA_ROOT_PREFIX and the guesses below
    executable  : str | None = None     # the micromamba binary, when it is not on PATH -- e.g. on a compute node
    when        : str | None = None     # a condition: an expression over the tags and `phase`

    def _exe( self, ctx ):
        """`micromamba`, pinned to the root prefix `-n <name>` must resolve against.

        Not pinning it is a real trap: the shell hook exports MAMBA_ROOT_PREFIX
        from an rc file, which only INTERACTIVE shells read. Started from make,
        from cron or from any plain subprocess, micromamba instead falls back to
        the envs directory beside its own binary -- so `-n x` silently names a
        different environment than the same command typed by hand.

        Over there, only what was DECLARED is passed: the guesses below look at
        this machine's home, which says nothing about the other one. A command
        that reaches a compute node through `srun` has no rc file at all, so
        that is where `executable` and `root_prefix` stop being optional.
        """
        exe = self.executable or "micromamba"
        root = self.root_prefix
        if not ctx.remote and not root:
            root = os.environ.get( "MAMBA_ROOT_PREFIX" )
            for candidate in ( ( ) if root else ( Path.home() / ".mamba", Path.home() / "micromamba" ) ):
                if ( candidate / "envs" ).is_dir():
                    root = str( candidate )
                    break
        return [ exe ] + ( [ "--root-prefix", root ] if root else [ ] )

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        if not ctx.remote:
            if self.name == os.environ.get( "CONDA_DEFAULT_ENV" ):
                return cmd                       # already active: nothing to wrap
            if shutil.which( self.executable or "micromamba" ) is None:
                return cmd
        return Command( [ *self._exe( ctx ), "-n", self.name, "run",
                          *under( cmd.argv, "python" ) ], cmd.env )

    def describe( self ):
        return f"micromamba:{self.name}"

    def spec( self, ctx ):
        return [ self.python, self.channels, self.packages,
                 self.requirements and ( ctx.root / self.requirements ), self.pip ]

    def probe( self, ctx ):
        return _quiet( [ *self._exe( ctx ), "-n", self.name, "run", "true" ] )

    def probe_shell( self, ctx ):
        return sh( [ *self._exe( ctx ), "-n", self.name, "run", "true" ] )

    def stamp_shell( self, ctx ):
        # rewritten by every install into the prefix, whoever asked for it
        return sh( [ *self._exe( ctx ), "-n", self.name, "run", "sh", "-c",
                     file_stamp( '"$CONDA_PREFIX/conda-meta/history"' ) ] )

    def build( self, ctx ):
        """Create it when it is not there, install into it when it is.

        `micromamba create -y -n x` on an environment that EXISTS is not a
        no-op and not an update: it resolves the named specs into it, and
        `python=3.13` over a 3.14 environment takes every package installed for
        3.14 out with it. An environment somebody is working in must never be
        the collateral of a declaration being read for the first time.
        """
        channels = [ f for c in self.channels for f in ( "-c", c ) ]
        spec = [ *( [ f"python={self.python}" ] if self.python else [ ] ), "pip",
                 *self.packages ]
        install = sh( [ *self._exe( ctx ), "install", "-y", "-n", self.name, *channels, *spec ] )
        create  = sh( [ *self._exe( ctx ), "create" , "-y", "-n", self.name, *channels, *( spec or [ "python" ] ) ] )
        if ctx.remote:
            # Whether it exists is a question for the machine it lives on, and
            # the step is run there: let that machine answer it.
            steps = [ *( [ fetch_micromamba( self.executable ) ] if self.executable else [ ] ),
                      f"if {self.probe_shell( ctx )} >/dev/null 2>&1; then "
                      f"{install if self.packages or self.python else 'true'}; else {create}; fi" ]
        elif self.executable and not os.access( self.executable, os.X_OK ):
            steps = [ fetch_micromamba( self.executable ), create ]
        elif self.probe( ctx ):
            steps = [ install ] if self.packages or self.python else [ ]
        else:
            steps = [ create ]
        steps += _install_steps( [ *self._exe( ctx ), "-n", self.name, "run",
                                   "python", "-m", "pip", "install" ], self, ctx )
        return steps


MICROMAMBA_URL = "https://micro.mamba.pm/api/micromamba/{platform}/latest"


def fetch_micromamba( exe: str ) -> str:
    """A shell line that puts the micromamba binary at `exe` when it is not there.

    Only for a DECLARED path: a bare `micromamba` says nothing about where to
    put it, nor that the commands that follow would find it there. The platform
    is asked of the machine the line runs on -- the cluster, not this mac.
    """
    q = shlex.quote( exe )
    tmp = shlex.quote( exe + ".part" )
    url = shlex.quote( MICROMAMBA_URL ).replace( "{platform}", "'\"$p\"'" )
    return ( f"test -x {q} || {{ case \"$(uname -s)-$(uname -m)\" in "
             "Linux-x86_64) p=linux-64;; Linux-aarch64) p=linux-aarch64;; Linux-ppc64le) p=linux-ppc64le;; "
             "Darwin-arm64) p=osx-arm64;; Darwin-x86_64) p=osx-64;; "
             "*) echo \"micromamba: no build for $(uname -sm)\" >&2; false;; esac && "
             f"mkdir -p \"$(dirname {q})\" && "
             f"{{ curl -fsSL {url} || wget -qO- {url}; }} | tar -xjO bin/micromamba > {tmp} && "
             f"chmod +x {tmp} && mv {tmp} {q}; }}" )


@dataclass
class Conda( Micromamba ):
    """The same thing through `conda`."""

    def _exe( self, ctx ):
        return [ "conda" ]

    def describe( self ):
        return f"conda:{self.name}"


@dataclass
class Uv( Interpreter, Artefact ):
    """A uv-managed venv in the project."""
    path        : str = ".venv"
    python      : str | None = None
    requirements: str | None = None
    pip         : list = field( default_factory = list )
    when        : str | None = None     # a condition: an expression over the tags and `phase`

    def _python( self, ctx ):
        return str( ctx.root / self.path / "bin" / "python" )

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        return Command( under( cmd.argv, self._python( ctx ) ), cmd.env )

    def describe( self ):
        return f"uv:{self.path}"

    def spec( self, ctx ):
        return [ self.python, self.requirements and ( ctx.root / self.requirements ), self.pip ]

    def probe( self, ctx ):
        return Path( self._python( ctx ) ).exists()

    def probe_shell( self, ctx ):
        return sh( [ "test", "-x", f"{self.path}/bin/python" ] )

    def stamp_shell( self, ctx ):
        return sh( [ f"{self.path}/bin/python", "-c", SITE_STAMP ] )

    def kept( self ):
        return [ self.path ]

    def build( self, ctx ):
        create = [ "uv", "venv", self.path ]
        if self.python:
            create += [ "--python", self.python ]
        steps = [ sh( create ) ]
        install = [ "uv", "pip", "install", "--python", self._python( ctx ) ]
        steps += _install_steps( install, self, ctx )
        return steps
