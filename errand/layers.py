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
    # What the work about to run asks of a machine, aggregated over the entries
    # this command carries. Only a layer that can ASK somebody for it -- a batch
    # system -- has any use for it.
    needs : dict = field( default_factory = dict )
    # `--batch`: let go rather than wait. Only a layer that has two ways of
    # starting something -- a batch system -- has anything to do with it.
    batch : bool = False


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
        if self.probe( ctx ):
            steps = ( [ sh( [ *self._exe( ctx ), "install", "-y", "-n", self.name,
                              *channels, *spec ] ) ] if self.packages or self.python else [ ] )
        else:
            steps = [ sh( [ *self._exe( ctx ), "create", "-y", "-n", self.name,
                            *channels, *( spec or [ "python" ] ) ] ) ]
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
        #
        # `--force` unconditionally: this is only ever called once it has been
        # decided that the image must be built, and apptainer's refusal to
        # overwrite would otherwise make a STALE image unfixable -- the one case
        # where rebuilding is the whole point.
        steps = [ sh( [ "apptainer", "build", "--force", str( ctx.root / self.image ),
                        str( ctx.root / self.recipe ) ] ) ]
        if self.pip:
            steps.append( sh( [ "apptainer", "exec", str( ctx.root / self.image ),
                                "python", "-m", "pip", "install", *self.pip ] ) )
        return steps


@dataclass
class Docker:
    """A container, run through the docker CLI.

    `user` defaults to the caller's own. A run writes its results into the
    project, and a daemon-backed container writes them as root unless told
    otherwise -- so the output tree of a containerized run would come out
    owned by somebody who is not you, and the next run outside the container
    could not clear it. Podman, being rootless, already maps the caller, and
    sets this to nothing.
    """
    image : str
    recipe: str | None = None
    flags : list = field( default_factory = list )
    mounts: dict = field( default_factory = dict )
    pip   : list = field( default_factory = list )
    engine: str = "docker"
    user  : str | None = "caller"

    @property
    def container( self ):
        return self.image.replace( "/", "_" ).replace( ":", "-" )

    def _user_flags( self ):
        if self.user is None:
            return [ ]
        if self.user != "caller":
            return [ "--user", self.user ]
        if hasattr( os, "getuid" ):
            return [ "--user", f"{os.getuid()}:{os.getgid()}" ]
        return [ ]

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        binds = [ f for src, dst in self.mounts.items()
                  for f in ( "-v", f"{ctx.root / src}:{dst}" ) ]
        envs = [ f for k, v in cmd.env.items() for f in ( "-e", f"{k}={v}" ) ]
        return Command( [ self.engine, "run", "--rm", *self._user_flags(), *self.flags,
                          *binds, *envs,
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
    """The same, rootless: it already runs as the caller, so no `--user`."""
    engine: str = "podman"
    user  : str | None = None


@dataclass
class Nix:
    """`nix develop <flake> -c …`."""
    flake: str = "."
    shell: str | None = None

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        target = f"{self.flake}#{self.shell}" if self.shell else self.flake
        return Command( [ "nix", "develop", target, "-c", *cmd.argv ], cmd.env )

    def describe( self ):
        return f"nix:{self.flake}"


@dataclass
class Guix:
    """`guix shell -m <manifest> -- …`."""
    manifest: str | None = None
    packages: list = field( default_factory = list )

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        spec = [ "-m", str( ctx.root / self.manifest ) ] if self.manifest else list( self.packages )
        return Command( [ "guix", "shell", *spec, "--", *cmd.argv ], cmd.env )

    def describe( self ):
        return f"guix:{self.manifest or ' '.join( self.packages )}"


@dataclass
class Module:
    """Lmod / environment modules -- how a cluster picks a toolchain.

    `module` is a shell function, not a program, so this has to go through a
    login shell to exist at all. That is the whole layer.
    """
    names: list

    def __init__( self, *names ):
        self.names = list( names )

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        loads = " && ".join( f"module load {shlex.quote( n )}" for n in self.names )
        return Command( [ "sh", "-lc", f"{loads} && exec {cmd.shell()}" ], { } )

    def describe( self ):
        return "module:" + ",".join( self.names )


# ── going elsewhere ──────────────────────────────────────────────────────────

@dataclass
class Slurm:
    """A batch allocation. `srun` while you wait, `sbatch` under `--batch`.

    Not an interpreter-selecting layer: it puts the command inside an
    allocation and leaves it otherwise alone, so it stacks in front of a
    container or an environment exactly as `Ssh` does in front of it.

    EVERYTHING IS OPTIONAL, `partition` included. What is not stated is not
    passed, and Slurm then applies its own default -- which is the right answer
    far more often than a partition name copied out of somebody else's script:
    the cluster already knows which one is the default, and it is the one that
    stays correct when the cluster is rearranged.
    """
    partition: str | None = None     # None: the cluster's own default partition
    nodes    : int | None = None
    cpus     : int | None = None
    gpus     : int | None = None
    time     : str | None = None
    account  : str | None = None
    extra    : list = field( default_factory = list )

    def flags( self, ctx: Context | None = None ):
        """What was declared, filled in from what the work asks for.

        A batch system is a queue that already exists, so errand does not hold
        a second one on top of it -- it hands the numbers over instead. What
        the environment states explicitly always wins: the person who wrote
        `cpus = 16` knew something about the partition that the entry does not.
        """
        needs = ( ctx.needs if ctx else { } ) or { }
        cpus = self.cpus if self.cpus is not None else needs.get( "cpus" )
        gpus = self.gpus if self.gpus is not None else needs.get( "gpus" )
        ram  = needs.get( "ram" )

        out = [ ]
        for flag, value in ( ( "--partition", self.partition ), ( "--nodes", self.nodes ),
                             ( "--cpus-per-task", cpus ), ( "--gpus", gpus ),
                             ( "--time", self.time ), ( "--account", self.account ) ):
            if value is not None:
                out += [ flag, str( int( value ) if isinstance( value, float ) else value ) ]
        if ram:
            out += [ "--mem", f"{int( ram )}M" ]
        if needs.get( "exclusive" ):
            out += [ "--exclusive" ]
        return out + list( self.extra )

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        if ctx.batch:
            # `sbatch` IS the detachment: it returns as soon as the job is
            # queued. `--parsable` makes it print the id and nothing else.
            return Command( [ "sbatch", "--parsable", *self.flags( ctx ),
                              "--wrap", cmd.shell() ], { } )
        return Command( [ "srun", *self.flags( ctx ), *cmd.argv ], cmd.env )

    def describe( self ):
        return f"slurm:{self.partition or 'default partition'}"



RSYNC_EXCLUDES = [
    ".git", "runs", "build", "dist", "__pycache__", "*.pyc", "*.so", "*.o",
    "node_modules", ".venv", "*.sif", "*.egg-info", ".mypy_cache", ".pytest_cache",
]


@dataclass
class Ssh:
    """Must be the first layer. Everything after it runs on `host`.

    `options` are passed to both ssh and rsync -- a port, an identity file, a
    jump host, a `StrictHostKeyChecking` you have decided about. rsync has to
    get the same ones or it reaches a different machine than ssh does.
    """
    host   : str
    root   : str | None = None
    python : str = "python3"
    options: list = field( default_factory = list )

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
        push( ctx.root, self.host, remote_ctx.root, self.options )

        line = f"mkdir -p {shlex.quote( str( remote_ctx.root ) )} && " \
               f"cd {shlex.quote( str( remote_ctx.root ) )} && {wrapped.shell()}"
        # ssh runs non-interactively, so the remote shell never reads the rc
        # file that puts micromamba, cargo or nvm on PATH. Force an interactive
        # one, through the user's own $SHELL rather than a hard-coded bash.
        code = subprocess.run( [ "ssh", *self.options, self.host,
                                 f"$SHELL -ic {shlex.quote( line )}" ] ).returncode

        if pull:
            echo( f"  rsync pull  <- {self.host}:{remote_ctx.root} [{', '.join( pull )}]" )
            fetch( pull, self.host, remote_ctx.root, ctx.root, self.options )
        return code


def _rsh( options ):
    """rsync must reach the machine ssh reaches, so it gets the same options."""
    return [ "-e", "ssh " + " ".join( shlex.quote( o ) for o in options ) ] if options else [ ]


def push( local_root: Path, host: str, remote_root: Path, options = ( ) ):
    subprocess.run( [ "ssh", *options, host, f"mkdir -p {shlex.quote( str( remote_root ) )}" ],
                    check = True )
    subprocess.run( [ "rsync", "-a", "--delete", *_rsh( options ),
                      *[ f"--exclude={e}" for e in RSYNC_EXCLUDES ],
                      f"{local_root}/", f"{host}:{remote_root}/" ], check = True )


def fetch( paths, host: str, remote_root: Path, local_root: Path, options = ( ) ):
    """Best effort: a path the remote run never created is nothing to bring back."""
    for p in paths:
        target = local_root / p
        target.mkdir( parents = True, exist_ok = True )
        # A trailing slash on BOTH sides: without it rsync nests the remote
        # directory INSIDE the local one whenever the latter already exists.
        subprocess.run( [ "rsync", "-a", *_rsh( options ),
                          f"{host}:{remote_root}/{p}/", f"{target}/" ] )


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


# Paths that a compute node does not generally share with the machine you
# submitted from. Getting this wrong fails deep inside the job, with a message
# from the batch system about chdir and then an import error -- nothing that
# points at the actual cause.
NODE_LOCAL = ( "/tmp", "/var/tmp", "/dev/shm", "/scratch/local", "/localscratch" )


def batch_of( stack ):
    return next( ( l for l in stack if isinstance( l, Slurm ) ), None )


def warnings_for( stack, root ) -> list:
    """What is about to go wrong in a way the error will not explain."""
    out = [ ]
    if batch_of( stack ) is not None:
        where = str( root )
        if any( where == p or where.startswith( p + "/" ) for p in NODE_LOCAL ):
            out.append(
                f"{where} is node-local: a batch job runs on a compute node, which does not "
                f"share it with the machine you submit from.\n"
                f"  the job will not find the project -- put the root on a shared filesystem "
                f"( your home, /scratch, /work )" )
    return out


def container_of( stack ):
    """The innermost container in a stack, for `{place}` in the output path."""
    for layer in reversed( stack ):
        if isinstance( layer, ( Apptainer, Docker ) ):
            return layer.container
    return None


def ssh_of( stack ):
    return stack[ 0 ] if stack and isinstance( stack[ 0 ], Ssh ) else None
