"""Layers: how to get from "run this program" to the actual subprocess.

A stack reads outside-in -- `[ Ssh( … ), Apptainer( … ), Vars( … ) ]` is ssh
around apptainer around the command -- and is folded innermost-first. There is
always a current interpreter, and most layers are a way to override it.

A layer may do three things, and only the first is required:

    wrap( cmd, ctx )   rewrite the command    -- every layer
    probe/create       say whether it is there, and build it   -- Micromamba, …
    detach( … )        launch and let go, for `--batch`        -- Ssh, Slurm, …

`Vars` and the tags of an environment are deliberately different things: a tag
SELECTS an environment, a layer ACTS once it is chosen. Keeping them apart is
what lets `--fp 32,64` mean two runs rather than one variable written twice.
"""
from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Command:
    argv: list
    env : dict = field( default_factory = dict )

    def shell( self ) -> str:
        assigns = [ f"{k}={shlex.quote( str( v ) )}" for k, v in self.env.items() ]
        return " ".join( assigns + [ shlex.quote( str( a ) ) for a in self.argv ] )


@dataclass
class Context:
    """What a layer needs to know that is not its own business."""
    root  : Path
    tags  : dict = field( default_factory = dict )   # the SELECTED tags
    remote: bool = False


def compose( stack, cmd: Command, ctx: Context ) -> Command:
    """Fold innermost-first: [ A, B, C ] -> A( B( C( cmd ) ) )."""
    for layer in reversed( stack ):
        cmd = layer.wrap( cmd, ctx )
    return cmd


def fingerprint( *parts ) -> str:
    """What a built environment is compared against to notice it has drifted."""
    h = hashlib.sha256()
    for part in parts:
        if isinstance( part, Path ):
            try:
                h.update( part.read_bytes() )
                continue
            except OSError:
                part = f"<missing {part}>"
        h.update( repr( part ).encode() )
    return h.hexdigest()[ : 16 ]


def sh( argv ) -> str:
    return " ".join( shlex.quote( str( a ) ) for a in argv )


# ── layers that only record something ────────────────────────────────────────

@dataclass
class Vars:
    """Environment variables for the child.

    `values` may be a callable taking the selected tags, which is how a single
    environment covers a whole dimension instead of being split into one per
    value: `Vars( lambda t: { "FTYPE": t.get( "fp", "64" ) } )`.
    """
    values: dict | object

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        values = self.values( ctx.tags ) if callable( self.values ) else self.values
        return Command( cmd.argv, { **cmd.env, **{ k: str( v ) for k, v in values.items() } } )

    def describe( self ):
        return "vars"


# ── interpreter-selecting layers ─────────────────────────────────────────────

@dataclass
class Venv:
    """A specific interpreter: a venv's python, or any installed one."""
    python      : str = "python"
    requirements: str | None = None
    pip         : list = field( default_factory = list )
    create      : bool = False          # make the venv if `python` is inside a missing one

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        return Command( [ self.python, *cmd.argv[ 1 : ] ], cmd.env )

    def describe( self ):
        return f"venv:{self.python}"

    def spec( self, ctx ):
        return [ self.python, self.requirements and ( ctx.root / self.requirements ), self.pip ]

    def probe( self, ctx ):
        return shutil.which( self.python ) is not None or Path( self.python ).exists()

    def build( self, ctx ):
        steps = [ ]
        if self.create:
            venv_dir = Path( self.python ).parent.parent
            steps.append( sh( [ "python3", "-m", "venv", str( venv_dir ) ] ) )
        steps += _install_steps( [ self.python, "-m", "pip", "install" ], self, ctx )
        return steps


@dataclass
class Micromamba:
    """A micromamba environment, by name."""
    name        : str
    python      : str | None = None
    channels    : list = field( default_factory = lambda: [ "conda-forge" ] )
    packages    : list = field( default_factory = list )
    requirements: str | None = None
    pip         : list = field( default_factory = list )

    def _exe( self, ctx ):
        """`micromamba`, pinned to the root prefix `-n <name>` must resolve against.

        Not pinning it is a real trap: the shell hook exports MAMBA_ROOT_PREFIX
        from an rc file, which only INTERACTIVE shells read. Started from make,
        from cron or from any plain subprocess, micromamba instead falls back to
        the envs directory beside its own binary -- so `-n x` silently names a
        different environment than the same command typed by hand.
        """
        if ctx.remote:
            return [ "micromamba" ]     # the remote side goes through an interactive shell
        root = os.environ.get( "MAMBA_ROOT_PREFIX" )
        if not root:
            for candidate in ( Path.home() / ".mamba", Path.home() / "micromamba" ):
                if ( candidate / "envs" ).is_dir():
                    root = str( candidate )
                    break
        return [ "micromamba" ] + ( [ "--root-prefix", root ] if root else [ ] )

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        if not ctx.remote:
            if self.name == os.environ.get( "CONDA_DEFAULT_ENV" ):
                return cmd                       # already active: nothing to wrap
            if shutil.which( "micromamba" ) is None:
                return cmd
        return Command( [ *self._exe( ctx ), "-n", self.name, "run", "python",
                          *cmd.argv[ 1 : ] ], cmd.env )

    def describe( self ):
        return f"micromamba:{self.name}"

    def spec( self, ctx ):
        return [ self.python, self.channels, self.packages,
                 self.requirements and ( ctx.root / self.requirements ), self.pip ]

    def probe( self, ctx ):
        return _quiet( [ *self._exe( ctx ), "-n", self.name, "run", "true" ] )

    def build( self, ctx ):
        spec = [ f"python={self.python}" if self.python else "python", "pip", *self.packages ]
        channels = [ f for c in self.channels for f in ( "-c", c ) ]
        steps = [ sh( [ *self._exe( ctx ), "create", "-y", "-n", self.name, *channels, *spec ] ) ]
        steps += _install_steps( [ *self._exe( ctx ), "-n", self.name, "run",
                                   "python", "-m", "pip", "install" ], self, ctx )
        return steps


@dataclass
class Conda( Micromamba ):
    """The same thing through `conda`."""

    def _exe( self, ctx ):
        return [ "conda" ]

    def describe( self ):
        return f"conda:{self.name}"


@dataclass
class Uv:
    """A uv-managed venv in the project."""
    path        : str = ".venv"
    python      : str | None = None
    requirements: str | None = None
    pip         : list = field( default_factory = list )

    def _python( self, ctx ):
        return str( ctx.root / self.path / "bin" / "python" )

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        return Command( [ self._python( ctx ), *cmd.argv[ 1 : ] ], cmd.env )

    def describe( self ):
        return f"uv:{self.path}"

    def spec( self, ctx ):
        return [ self.python, self.requirements and ( ctx.root / self.requirements ), self.pip ]

    def probe( self, ctx ):
        return Path( self._python( ctx ) ).exists()

    def build( self, ctx ):
        create = [ "uv", "venv", str( ctx.root / self.path ) ]
        if self.python:
            create += [ "--python", self.python ]
        steps = [ sh( create ) ]
        install = [ "uv", "pip", "install", "--python", self._python( ctx ) ]
        steps += _install_steps( install, self, ctx )
        return steps


# ── container layers ─────────────────────────────────────────────────────────

@dataclass
class Apptainer:
    image : str
    recipe: str | None = None
    flags : list = field( default_factory = list )
    mounts: dict = field( default_factory = dict )
    pip   : list = field( default_factory = list )

    @property
    def container( self ):
        return Path( self.image ).name

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        binds = [ f for src, dst in self.mounts.items()
                  for f in ( "--bind", f"{ctx.root / src}:{dst}" ) ]
        # The container brings its own interpreter; a host path would not
        # generally resolve inside it.
        return Command( [ "apptainer", "exec", *self.flags, *binds,
                          str( ctx.root / self.image ), "python", *cmd.argv[ 1 : ] ], cmd.env )

    def describe( self ):
        return f"apptainer:{self.container}"

    def spec( self, ctx ):
        return [ self.recipe and ( ctx.root / self.recipe ), self.flags, self.pip ]

    def probe( self, ctx ):
        return ( ctx.root / self.image ).exists()

    def build( self, ctx ):
        if not self.recipe:
            return [ ]     # an image someone else builds; nothing to say about it
        # Never through wrap(): that runs a command INSIDE the image, which does
        # not exist yet while it is being built.
        steps = [ sh( [ "apptainer", "build", str( ctx.root / self.image ),
                        str( ctx.root / self.recipe ) ] ) ]
        if self.pip:
            steps.append( sh( [ "apptainer", "exec", str( ctx.root / self.image ),
                                "python", "-m", "pip", "install", *self.pip ] ) )
        return steps


@dataclass
class Docker:
    image : str
    recipe: str | None = None
    flags : list = field( default_factory = list )
    mounts: dict = field( default_factory = dict )
    pip   : list = field( default_factory = list )
    engine: str = "docker"

    @property
    def container( self ):
        return self.image.replace( "/", "_" ).replace( ":", "-" )

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        binds = [ f for src, dst in self.mounts.items()
                  for f in ( "-v", f"{ctx.root / src}:{dst}" ) ]
        envs = [ f for k, v in cmd.env.items() for f in ( "-e", f"{k}={v}" ) ]
        return Command( [ self.engine, "run", "--rm", *self.flags, *binds, *envs,
                          "-v", f"{ctx.root}:{ctx.root}", "-w", str( ctx.root ),
                          self.image, "python", *cmd.argv[ 1 : ] ], { } )

    def describe( self ):
        return f"{self.engine}:{self.image}"

    def spec( self, ctx ):
        return [ self.recipe and ( ctx.root / self.recipe ), self.flags, self.pip ]

    def probe( self, ctx ):
        return _quiet( [ self.engine, "image", "inspect", self.image ] )

    def build( self, ctx ):
        if not self.recipe:
            return [ ]
        return [ sh( [ self.engine, "build", "-t", self.image,
                       "-f", str( ctx.root / self.recipe ), str( ctx.root ) ] ) ]


@dataclass
class Podman( Docker ):
    engine: str = "podman"


# ── going elsewhere ──────────────────────────────────────────────────────────

RSYNC_EXCLUDES = [
    ".git", "runs", "build", "dist", "__pycache__", "*.pyc", "*.so", "*.o",
    "node_modules", ".venv", "*.sif", "*.egg-info", ".mypy_cache", ".pytest_cache",
]


@dataclass
class Ssh:
    """Must be the first layer. Everything after it runs on `host`."""
    host  : str
    root  : str | None = None
    python: str = "python3"

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        # Never folded like the others: `run` takes over, because getting there
        # means syncing first and fetching afterwards.
        raise RuntimeError( "Ssh must be the first layer of an environment" )

    def describe( self ):
        return f"ssh:{self.host}"

    def remote_root( self, ctx ):
        return Path( self.root or ctx.root )

    def run( self, inner, cmd: Command, ctx: Context, pull = None, echo = print ):
        remote_ctx = Context( root = self.remote_root( ctx ), tags = ctx.tags, remote = True )
        wrapped = compose( inner, Command( [ self.python, *cmd.argv[ 1 : ] ], cmd.env ), remote_ctx )

        echo( f"  rsync push -> {self.host}:{remote_ctx.root}" )
        push( ctx.root, self.host, remote_ctx.root )

        line = f"cd {shlex.quote( str( remote_ctx.root ) )} && {wrapped.shell()}"
        # ssh runs non-interactively, so the remote shell never reads the rc
        # file that puts micromamba, cargo or nvm on PATH. Force an interactive
        # one, through the user's own $SHELL rather than a hard-coded bash.
        code = subprocess.run( [ "ssh", self.host, f"$SHELL -ic {shlex.quote( line )}" ] ).returncode

        if pull:
            echo( f"  rsync pull  <- {self.host}:{remote_ctx.root} [{', '.join( pull )}]" )
            fetch( pull, self.host, remote_ctx.root, ctx.root )
        return code


def push( local_root: Path, host: str, remote_root: Path ):
    subprocess.run( [ "rsync", "-a", "--delete",
                      *[ f"--exclude={e}" for e in RSYNC_EXCLUDES ],
                      f"{local_root}/", f"{host}:{remote_root}/" ], check = True )


def fetch( paths, host: str, remote_root: Path, local_root: Path ):
    """Best effort: a path the remote run never created is nothing to bring back."""
    for p in paths:
        target = local_root / p
        target.mkdir( parents = True, exist_ok = True )
        # A trailing slash on BOTH sides: without it rsync nests the remote
        # directory INSIDE the local one whenever the latter already exists.
        subprocess.run( [ "rsync", "-a", f"{host}:{remote_root}/{p}/", f"{target}/" ] )


# ── helpers ──────────────────────────────────────────────────────────────────

def _install_steps( pip_argv, layer, ctx ):
    steps = [ ]
    if layer.requirements:
        steps.append( sh( [ *pip_argv, "-r", str( ctx.root / layer.requirements ) ] ) )
    if layer.pip:
        steps.append( sh( [ *pip_argv, *layer.pip ] ) )
    return steps


def _quiet( argv ) -> bool:
    try:
        return subprocess.run( argv, stdout = subprocess.DEVNULL,
                               stderr = subprocess.DEVNULL ).returncode == 0
    except OSError:
        return False


def container_of( stack ):
    """The innermost container in a stack, for `{place}` in the output path."""
    for layer in reversed( stack ):
        if isinstance( layer, ( Apptainer, Docker ) ):
            return layer.container
    return None


def ssh_of( stack ):
    return stack[ 0 ] if stack and isinstance( stack[ 0 ], Ssh ) else None
