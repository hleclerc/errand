"""Interpreters: a venv, a micromamba or conda environment, a uv project -- each built and kept current.
"""
from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .. import bootstrap
from .base import _install_steps, _quiet, Command, Context, file_stamp, sh, SITE_STAMP, under, WINDOWS
from .families import Artefact, Interpreter


@dataclass
class Venv( Interpreter, Artefact ):
    """A specific interpreter: a venv's python, or any installed one."""
    python      : str = "python"
    requirements: str | None = None
    pip         : list = field( default_factory = list )
    create      : bool = False          # make the venv if `python` is inside a missing one

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
    name        : str = ""          # empty only in a declaration something completes ( a package's own layers ): refused when used
    python      : str | None = None
    channels    : list = field( default_factory = lambda: [ "conda-forge" ] )
    packages    : list = field( default_factory = list )
    requirements: str | None = None
    pip         : list = field( default_factory = list )
    root_prefix : str | None = None     # where `-n <name>` resolves; wins over MAMBA_ROOT_PREFIX and the guesses below
    executable  : str | None = None     # the micromamba binary, when it is not on PATH -- e.g. on a compute node

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

    def _python( self, ctx ):
        if WINDOWS and not ctx.remote:          # a venv on Windows: Scripts\python.exe
            return str( ctx.root / self.path / "Scripts" / "python.exe" )
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
        return sh( [ self._python( ctx ) if WINDOWS and not ctx.remote else f"{self.path}/bin/python", "-c", SITE_STAMP ] )

    def kept( self ):
        return [ self.path ]

    def build( self, ctx ):
        # Where uv is not installed ( a cluster's nodes ), the one errand fetches for itself ( `bootstrap` ):
        # every step finds it first, since each is a shell line of its own
        posix = ctx.remote or not WINDOWS
        find, uv = ( UV_FIND + " && ", '"$uv"' ) if posix else ( "", "uv" )
        create = [ "venv", self.path ]
        if self.python:
            create += [ "--python", self.python ]
        install = [ "pip", "install", "--python", self._python( ctx ) ]
        return [ f"{find}{uv} {step}" for step in [ sh( create ), *_install_steps( install, self, ctx ) ] ]


# A shell line that leaves in `$uv` the uv of the PATH, of its usual places, or of errand's cache, fetched
# there from astral.sh when there is none ( never on the PATH, never in a shell profile ): the way `bootstrap`
# finds the one it makes its Python with, so that the two share it.
UV_FIND = ( 'uv=$( command -v uv 2>/dev/null ); base=' + bootstrap.SH_BASE + '; '
            'for c in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" "$base/uv/uv"; do '
            '[ -z "$uv" ] && [ -x "$c" ] && uv="$c"; done; '
            'if [ -z "$uv" ]; then echo "errand: no uv here: fetching one into $base/uv" >&2; mkdir -p "$base"; '
            'if command -v curl >/dev/null 2>&1; then curl -LsSf https://astral.sh/uv/install.sh; '
            'else wget -qO- https://astral.sh/uv/install.sh; fi | env UV_UNMANAGED_INSTALL="$base/uv" sh >&2; '
            'uv="$base/uv/uv"; fi; [ -x "$uv" ]' )
