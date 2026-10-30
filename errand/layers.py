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
import re
import shlex
import shutil
import subprocess
import sys
import time
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
    # `errand shell` with no command: somebody types into it. Only a layer that
    # stands between the terminal and the command -- ssh, a container engine, a
    # batch system -- has to be told to hand the terminal on.
    interactive: bool = False
    # Which pass this is: `prepare` resolves, builds and collects, `run` runs.
    # A scheduler sizes the second from the plan the first wrote.
    phase : str = "run"
    # Where a layer's OWN work runs -- booting a machine, copying into it --
    # as opposed to the command it wraps: whatever the layers before it lead
    # to. `Here` for the first layer; `Ssh` hands the next ones `Over`.
    host  : object = None
    # The project as THIS process sees it, wherever `root` is: what a layer
    # reads to know what it was declared with ( a script, a recipe ), since the
    # reading is done here even when the doing is not.
    origin: Path | None = None

    def __post_init__( self ):
        if self.host is None:
            self.host = Here( self.root )
        if self.origin is None:
            self.origin = self.root


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


# Every step a layer asks for is run FROM THE PROJECT ROOT -- this one when it
# is built here, the remote one when it is built over there. So a step names
# what it needs the way the project declares it: `containers/cuda.sif`, not
# `/home/me/proj/containers/cuda.sif`, which is a path that exists on exactly
# one of the two machines.


# ── layers that only record something ────────────────────────────────────────

INTERPRETERS = ( "python", "python3", "python2" )


def under( argv, python ):
    """`argv` with its interpreter replaced by `python`, when it HAS one.

    Every layer's job is to run the work with the interpreter of the place it
    describes -- a venv's python, the one inside the container. But a command
    is not always an interpreter call ( `errand shell --env gpu -- nvidia-smi` ), and
    substituting the first word blindly turns that one into `python
    nvidia-smi`. So: a first word that names an interpreter is replaced; any
    other is a command in its own right and is kept.
    """
    first = str( argv[ 0 ] ) if argv else ""
    if Path( first ).name in INTERPRETERS or first == sys.executable:
        return [ python, *argv[ 1 : ] ]
    return list( argv )


@dataclass
class Vars:
    """Environment variables for the child.

    `values` may be a callable taking the selected tags, which is how a single
    environment covers a whole dimension instead of being split into one per
    value: `Vars( lambda t: { "FTYPE": t.get( "fp", "64" ) } )`.
    """
    values: dict | object
    when  : str | None = None

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
class Uv:
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

    def build( self, ctx ):
        create = [ "uv", "venv", self.path ]
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
    # How the IMAGE is built, as opposed to how it is entered. `fakeroot`
    # builds without root on a host that allows it; `scratch` is a directory
    # with room -- apptainer unpacks whole layers, and the default /tmp is
    # where a build dies halfway, out of space, on a shared machine.
    fakeroot: bool = False
    scratch : str | None = None
    build_flags: list = field( default_factory = list )
    # A machine without internet -- a national cluster -- cannot build an image
    # whose recipe downloads anything. `build_on` is a machine that can ( an
    # `Ssh`, of the same architecture ): the image is built there and copied
    # to where it runs. `install` is a shell line run where it runs once the
    # copy is there ( `{image}`: its path in the project ), for a site that
    # only executes images from a place of its own -- and `run_from` is then
    # the image as entered, expanded by the shell
    # ( `$SINGULARITY_ALLOWED_DIR/main.sif` ). `exe`: `singularity` where
    # that is what the site calls it.
    build_on   : "Ssh | None" = None
    install    : str | None = None
    run_from   : str | None = None
    exe        : str = "apptainer"
    when       : str | None = None

    @property
    def container( self ):
        return Path( self.image ).name

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        binds = [ f for src, dst in self.mounts.items()
                  for f in ( "--bind", f"{ctx.root / src}:{dst}" ) ]
        # The container brings its own interpreter; a host path would not
        # generally resolve inside it.
        argv = under( cmd.argv, "python" )
        if self.run_from:
            # a path to expand where it runs: through a shell, the arguments
            # passed on untouched
            line = f'exec {sh( [ self.exe, "exec", *self.flags, *binds ] )} {self.run_from} "$@"'
            return Command( [ "sh", "-c", line, "sh", *argv ], cmd.env )
        return Command( [ self.exe, "exec", *self.flags, *binds,
                          str( ctx.root / self.image ), *argv ], cmd.env )

    def describe( self ):
        return f"apptainer:{self.container}"

    def spec( self, ctx ):
        # a recipe is a file of the project, or an image to convert ( `docker://...`, which needs
        # no root where building from a recipe needs `--fakeroot` ): the URI then IS the recipe
        recipe = self.recipe and ( self.recipe if "://" in self.recipe else ctx.root / self.recipe )
        return [ recipe, self.flags, self.pip, self.fakeroot, self.scratch, self.build_flags ]

    def probe( self, ctx ):
        return ( ctx.root / self.image ).exists()

    def probe_shell( self, ctx ):
        # Relative on purpose: the answer is wanted in the remote root, which
        # the caller has already `cd`-ed into, and which is not this one.
        return sh( [ "test", "-e", self.image ] )

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
        # ( the builder's own apptainer: `exe` is what the place it RUNS calls it )
        argv = [ "apptainer" if self.build_on else self.exe, "build", "--force",
                 *( [ "--fakeroot" ] if self.fakeroot else [ ] ), *self.build_flags,
                 self.image, self.recipe ]
        # Both, and to the same place: apptainer writes its unpacked layers to
        # one and its downloads to the other, and a build that runs out of room
        # in either dies the same way.
        room = [ f"{k}={self.scratch}" for k in ( "APPTAINER_TMPDIR", "APPTAINER_CACHEDIR" ) ] \
               if self.scratch else [ ]
        steps = [ " ".join( [ *room, sh( argv ) ] ) ]
        if self.pip:
            steps.append( sh( [ argv[ 0 ], "exec", self.image,
                                "python", "-m", "pip", "install", *self.pip ] ) )
        if self.build_on is not None:
            steps = [ _BuiltElsewhere( self, steps, ctx ) ]
        if self.install:
            steps.append( self.install.format( image = shlex.quote( self.image ) ) )
        return steps


class _BuiltElsewhere:
    """The build steps of an image, run on `layer.build_on`, then the image
    copied to where it runs ( `ctx.host` ). A step of `setup.ensure`: called
    with `echo`, says how it went."""

    def __init__( self, layer: Apptainer, steps, ctx: Context ):
        self.layer, self.steps, self.ctx = layer, steps, ctx
        # its own root, else the layout of the project HERE: the remote root
        # `ctx` carries is the one of the machine it runs on, not of the builder
        b = layer.build_on
        self.builder = Over( b, Path( b.root or ctx.origin ) )

    def __str__( self ):
        b = self.builder
        return f"on {b.describe()}: {' && '.join( self.steps )}; then copied to {self.ctx.host.describe()}"

    def __call__( self, echo = print ) -> int:
        b, image = self.builder, self.layer.image
        # The recipe is a file of the project HERE, which the builder builds
        # from its own copy: pushed first, as `Ssh` does before a run.
        echo( f"    rsync push -> {b.ssh.host}:{b.root}" )
        push( self.ctx.origin, b.ssh.host, b.root, b.ssh.options )
        for step in self.steps:
            echo( f"    $ {step}    ( on {b.describe()} )" )
            if b.shell( step, tty = True ).returncode != 0:
                return 1
        echo( f"    copying {image}: {b.describe()} -> {self.ctx.host.describe()}" )
        return relay( b, b.root / image, self.ctx.host, image )


def relay( source: "Over", path, dest, rel ) -> int:
    """`path` on `source` to `rel` ( relative to its root ) on `dest`, streamed
    through this process: the two machines need not reach each other -- a
    cluster behind a jump host is reached from here, not from the builder.
    Written aside and renamed once the source has said it was all there, so
    that an interrupted copy is never taken for an image."""
    q = shlex.quote( str( rel ) )

    def on_dest( line, **how ):
        if dest.remote:
            root = f"cd {shlex.quote( str( dest.root ) )} && " if dest.root is not None else ""
            return subprocess.run( [ "ssh", *dest.ssh.options, dest.ssh.host, root + line ], **how ).returncode
        return subprocess.run( [ "sh", "-c", line ], cwd = str( dest.root ), **how ).returncode

    src = subprocess.Popen( [ "ssh", *source.ssh.options, source.ssh.host, f"cat {shlex.quote( str( path ) )}" ],
                            stdout = subprocess.PIPE )
    code = on_dest( f"mkdir -p \"$( dirname {q} )\" && cat > {q}.part", stdin = src.stdout )
    src.stdout.close()
    code = src.wait() or code
    return on_dest( f"rm -f {q}.part" ) or code if code else on_dest( f"mv {q}.part {q}" )


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
    when  : str | None = None

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
        return Command( [ self.engine, "run", "--rm", *( [ "-it" ] if ctx.interactive else [ ] ),
                          *self._user_flags(), *self.flags,
                          *binds, *envs,
                          "-v", f"{ctx.root}:{ctx.root}", "-w", str( ctx.root ),
                          self.image, *under( cmd.argv, "python" ) ], { } )

    def describe( self ):
        return f"{self.engine}:{self.image}"

    def spec( self, ctx ):
        return [ self.recipe and ( ctx.root / self.recipe ), self.flags, self.pip ]

    def probe( self, ctx ):
        return _quiet( [ self.engine, "image", "inspect", self.image ] )

    def probe_shell( self, ctx ):
        return sh( [ self.engine, "image", "inspect", self.image ] ) + " >/dev/null 2>&1"

    def build( self, ctx ):
        if not self.recipe:
            return [ ]
        return [ sh( [ self.engine, "build", "-t", self.image,
                       "-f", self.recipe, "." ] ) ]


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
    when : str | None = None

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
    when    : str | None = None

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        spec = [ "-m", self.manifest ] if self.manifest else list( self.packages )
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
    when : str | None = None

    def __init__( self, *names, when = None ):
        self.names = list( names )
        self.when  = when

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        loads = " && ".join( f"module load {shlex.quote( n )}" for n in self.names )
        # `exec` takes a program, not assignments: `env` sets them ( after the
        # login shell's profile, which would otherwise be free to undo them )
        run = f"env {cmd.shell()}" if cmd.env else cmd.shell()
        return Command( [ "sh", "-lc", f"{loads} && exec {run}" ], { } )

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
    nodelist : str | list | None = None   # `node15`, `node[1-4]` or [ "node15", "node16" ]
    # A name, or a function of the time asked ( in seconds ) giving one: the clusters whose qos is a matter
    # of how long the job is
    qos      : object = None
    # Waiting through `sbatch` rather than `srun`: the job is submitted, then asked how it is going every
    # `watch` seconds at most, each time over a connection of its own ( see `watch_job` ). For a cluster that
    # does not keep a connection open as long as the queue and the job last. It sizes the job from what is
    # declared here, and needs a time ( here, or `--time` ).
    watch    : float | None = None
    extra    : list = field( default_factory = list )
    when     : str | None = None

    def flags( self, ctx: Context | None = None ):
        """What was declared, filled in from what the work asks for.

        A batch system is a queue that already exists, so errand does not hold
        a second one on top of it -- it hands the numbers over instead. What
        the environment states explicitly always wins: the person who wrote
        `cpus = 16` knew something about the partition that the entry does not.
        """
        # Preparing is one process, sized from nothing: the entries it would be
        # sized from are what it is about to find out.
        prepare = ctx is not None and ctx.phase == "prepare"
        needs = { } if prepare else ( ( ctx.needs if ctx else { } ) or { } )
        cpus = self.cpus if self.cpus is not None else needs.get( "cpus" )
        gpus = self.gpus if self.gpus is not None else needs.get( "gpus" )
        ram  = needs.get( "ram" )
        # the time asked for this command ( `--time` ) wins over the environment's
        time = ( ( ctx.needs if ctx else { } ) or { } ).get( "time" ) or self.time
        qos  = self.qos( slurm_seconds( time ) if time else None ) if callable( self.qos ) else self.qos

        out = [ ]
        for flag, value in ( ( "--partition", self.partition ),
                             ( "--nodes", 1 if prepare and self.nodes else self.nodes ),
                             ( "--ntasks", 1 if prepare else None ),
                             ( "--cpus-per-task", cpus ), ( "--gpus", gpus ),
                             ( "--time", time ), ( "--account", self.account ), ( "--qos", qos ),
                             ( "--nodelist", self._nodelist() ) ):
            if value is not None:
                out += [ flag, str( int( value ) if isinstance( value, float ) else value ) ]
        if ram:
            out += [ "--mem", f"{int( ram )}M" ]
        if needs.get( "exclusive" ):
            out += [ "--exclusive" ]
        return out + list( self.extra )

    def _nodelist( self ):
        if isinstance( self.nodelist, ( list, tuple ) ):
            return ",".join( self.nodelist ) or None
        return self.nodelist

    def watched( self, ctx: Context ) -> bool:
        """Waited for by submitting and asking, rather than by `srun`."""
        return bool( self.watch ) and not ctx.batch and not ctx.interactive

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        if ctx.batch:
            # `sbatch` IS the detachment: it returns as soon as the job is
            # queued. `--parsable` makes it print the id and nothing else.
            return Command( [ "sbatch", "--parsable", *self.flags( ctx ),
                              "--wrap", cmd.shell() ], { } )
        if self.watched( ctx ):
            flags = self.flags( ctx )
            if "--time" not in flags:
                # the job is sized from the declaration alone: the cluster's default time is
                # its longest more often than not, which is the queue's longest wait
                raise ValueError( "a watched slurm job needs a time: `--time 1:00:00`, "
                                  "or `time =` in the environment's Slurm( ... )" )
            # what `watch_job` reads: the output, then the return code, once it is over
            log = watch_dir( ctx )
            return Command( [ "sbatch", "--parsable", *flags, "--output", f"{log}/slurm-%j.out",
                              "--wrap", f"{cmd.shell()}; echo $? > {log}/slurm-$SLURM_JOB_ID.rc" ], { } )
        return Command( [ "srun", *self.flags( ctx ), *( [ "--pty" ] if ctx.interactive else [ ] ),
                          *cmd.argv ], cmd.env )

    def describe( self ):
        nodes = self._nodelist()
        return f"slurm:{self.partition or 'default partition'}" + ( f"@{nodes}" if nodes else "" )



RSYNC_EXCLUDES = [
    ".git", "runs", "build", "dist", "__pycache__", "*.pyc", "*.so", "*.o",
    "node_modules", "target", ".venv", "*.sif", "*.egg-info", ".mypy_cache", ".pytest_cache",
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
    also   : list = field( default_factory = list )   # sibling checkouts the work needs, pushed with the project
    when   : str | None = None

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        # Never folded like the others: `run` takes over, because getting there
        # means syncing first and fetching afterwards.
        raise RuntimeError( "Ssh must be the first layer of an environment" )

    def describe( self ):
        return f"ssh:{self.host}"

    def remote_root( self, ctx ):
        return Path( self.root or ctx.root )

    def place( self, ctx ) -> "Over":
        """What the layers after this one are handed as `ctx.host`."""
        return Over( self, self.remote_root( ctx ) )

    def run( self, inner, cmd: Command, ctx: Context, pull = None, echo = print ):
        there = self.place( ctx )
        remote_ctx = Context( root = there.root, tags = ctx.tags, remote = True, host = there,
                              origin = ctx.origin, interactive = ctx.interactive,
                              needs = ctx.needs, batch = ctx.batch, phase = ctx.phase )

        echo( f"  rsync push -> {self.host}:{remote_ctx.root}" )
        push( ctx.root, self.host, remote_ctx.root, self.options )
        for other in self.also:
            # `../loom` lands at `<remote root>/../loom`: the same layout as here
            push( Path( os.path.normpath( ctx.root / other ) ), self.host,
                  Path( os.path.normpath( remote_ctx.root / other ) ), self.options )

        if inner and hasattr( inner[ 0 ], "run" ):
            # A layer that leads somewhere again -- a machine to boot over
            # there. It does its own work through `there`, and what it brings
            # back into the project's copy over there comes back here in turn.
            code = inner[ 0 ].run( inner[ 1 : ], cmd, remote_ctx, pull = pull, echo = echo )
            pull = [ *( pull or [ ] ), *getattr( inner[ 0 ], "fetch", [ ] ) ]
        else:
            code = run_on( there, inner, Command( under( cmd.argv, self.python ), cmd.env ),
                           remote_ctx, echo = echo )

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
    # errand's own state is each side's: the records of the runs made over
    # there, its plans, what it built. Excluded, so `--delete` leaves it be.
    from . import config
    state = config.state_rel( local_root )
    own = [ f"/{state}" ] if not os.path.isabs( state ) else [ ]
    subprocess.run( [ "rsync", "-a", "--delete", *_rsh( options ),
                      *[ f"--exclude={e}" for e in RSYNC_EXCLUDES + own ],
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


# ── where a layer's own work runs ────────────────────────────────────────────
#
# Most layers only rewrite the command. A few must DO something before it can
# run -- build an image, boot a machine, copy the project into it -- and where
# that happens is not their business: it is wherever the layers before them
# lead. So it is handed down, as `ctx.host`: a way to run a shell line THERE
# and read what it answered. The deciding stays in this process; only the
# doing goes over there, one line at a time, as many as it takes.
#
#     shell( line, capture =, quiet =, input =, timeout =, tty = )
#                     -> a CompletedProcess, from the project root of that place

def _how( quiet, capture, input ) -> dict:
    how = { }
    if capture:
        how.update( capture_output = True, text = True )
    elif quiet:
        how.update( stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL )
    if input is not None:
        how.update( input = input, text = True )
    elif capture or quiet:
        # Asked, not watched: it must not read the terminal's keystrokes --
        # ssh would, and swallow what was typed for something else.
        how.update( stdin = subprocess.DEVNULL )
    return how


class Here:
    """This machine, from the project root: what the first layer is handed."""
    remote = False

    def __init__( self, root ):
        self.root = Path( root )

    def shell( self, line: str, *, quiet = False, tty = False, capture = False, input = None,
               timeout = None ):
        return subprocess.run( [ "sh", "-c", line ], cwd = str( self.root ), timeout = timeout,
                               **_how( quiet, capture, input ) )

    def describe( self ):
        return "here"

    def spec( self ) -> dict:
        return { "here": str( self.root ) }


class Over:
    """Another machine, through `Ssh`, from the project's copy over there:
    what the layers after an `Ssh` are handed."""
    remote = True

    def __init__( self, ssh: Ssh, root = None ):
        self.ssh  = ssh
        self.root = Path( root ) if root is not None else None

    def shell( self, line: str, *, quiet = False, tty = False, capture = False, input = None,
               timeout = None ):
        if self.root is not None:
            line = f"cd {shlex.quote( str( self.root ) )} && {line}"
        # ssh runs non-interactively, so the remote shell never reads the rc
        # file that puts micromamba, cargo or nvm on PATH. Force an interactive
        # one, through the user's own $SHELL rather than a hard-coded bash.
        # `-t` when somebody watches: a build can ask for a password, and draws
        # a progress bar nobody sees without a terminal.
        return subprocess.run( [ "ssh", *( [ "-t" ] if tty else [ ] ), *self.ssh.options, self.ssh.host,
                                 f"$SHELL -ic {shlex.quote( line )}" ], timeout = timeout,
                               **_how( quiet, capture, input ) )

    def describe( self ):
        return self.ssh.host

    def spec( self ) -> dict:
        return { "ssh": { "host": self.ssh.host, "options": list( self.ssh.options ),
                          "python": self.ssh.python },
                 "root": None if self.root is None else str( self.root ) }


def host_of( spec: dict ):
    """`spec` the other way round: for another process that must reach the same place."""
    if "here" in spec:
        return Here( spec[ "here" ] )
    return Over( Ssh( **spec[ "ssh" ] ), spec.get( "root" ) )


# ── helpers ──────────────────────────────────────────────────────────────────

def _install_steps( pip_argv, layer, ctx ):
    steps = [ ]
    if layer.requirements:
        steps.append( sh( [ *pip_argv, "-r", layer.requirements ] ) )
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


def is_scheduler( layer ) -> bool:
    """A layer that puts the command in an allocation somebody else grants."""
    return isinstance( layer, Slurm ) or getattr( layer, "is_scheduler", False )


def batch_of( stack ):
    return next( ( l for l in stack if is_scheduler( l ) ), None )


def slurm_seconds( time: str ) -> int:
    """`MM`, `MM:SS`, `HH:MM:SS`, `D-HH`, `D-HH:MM`, `D-HH:MM:SS`: slurm's ways of saying how long."""
    days, _, rest = str( time ).rpartition( "-" )
    parts = [ int( p ) for p in rest.split( ":" ) ]
    if days:
        parts += [ 0 ] * ( 3 - len( parts ) )          # after a day, the first number is hours
        h, m, s = parts
    else:
        h, m, s = { 1: [ 0, parts[ 0 ], 0 ], 2: [ 0, *parts ], 3: parts }[ len( parts ) ]
    return ( ( int( days or 0 ) * 24 + h ) * 60 + m ) * 60 + s


# ── a job waited for from afar ───────────────────────────────────────────────

def watch_dir( ctx: Context ) -> str:
    """Where a watched job writes its output and return code, over there."""
    from . import config
    return str( ctx.root / config.state_rel( ctx.root ) / "batch" )


def run_on( host, stack, cmd: Command, ctx: Context, echo = print ) -> int:
    """`cmd` through `stack`, from `host`: waited for as each layer waits, or,
    under a watched scheduler, submitted and then asked about ( `watch_job` )."""
    wrapped = compose( stack, cmd, ctx )
    sched = batch_of( stack )
    if not ( isinstance( sched, Slurm ) and sched.watched( ctx ) ):
        return host.shell( wrapped.shell(), tty = ctx.interactive ).returncode
    return watch_job( host, wrapped, watch_dir( ctx ), sched.watch, echo )


def watch_job( host, submit: Command, log: str, every: float, echo = print, first = 10.0 ) -> int:
    """Submit, then ask how the job is going until it is over, and say how it went.

    Each question is a connection of its own, at growing intervals ( `first`
    seconds, doubling up to `every` ): a connection that drops loses one
    question, never the job. What the job writes is shown as it comes, and its
    return code is the one it wrote ( absent: killed -- the time ran out, it was
    cancelled -- and slurm's own account says which ).

    Interrupted here ( ctrl-C ), the job is cancelled, as `srun` would be.
    """
    got = host.shell( f"mkdir -p {shlex.quote( log )} && {submit.shell()}", capture = True )
    lines = [ l.strip() for l in ( got.stdout or "" ).splitlines() ]
    job = next( ( l.split( ";" )[ 0 ] for l in reversed( lines ) if re.fullmatch( r"\d+(;\S+)?", l ) ), None )
    if got.returncode or job is None:
        echo( f"  could not submit: {( got.stderr or got.stdout or '' ).strip()[ -400 : ]}" )
        return got.returncode or 1
    out, rc = f"{log}/slurm-{job}.out", f"{log}/slurm-{job}.rc"
    echo( f"  slurm job {job}, asked about every {int( every )} s at most ( ctrl-C cancels it )" )

    shown, state, wait, lost = 0, None, first, False
    try:
        while True:
            time.sleep( wait )
            wait = min( wait * 2, every )
            # one connection: the state, then what was written since the last time
            try:
                q = host.shell( f"squeue -h -j {job} -o '%T %N' 2>/dev/null; echo ERRAND_SEP; "
                                f"tail -c +{shown + 1} {out} 2>/dev/null", capture = True, timeout = 300 )
            except subprocess.TimeoutExpired:
                q = None
            if q is None or "ERRAND_SEP" not in ( q.stdout or "" ):
                if not lost:
                    echo( f"  ( cannot ask about job {job} right now: asking again later )" )
                lost = True
                continue
            lost = False
            now, _, text = q.stdout.partition( "ERRAND_SEP\n" )
            if text:
                print( text, end = "", flush = True )
                shown += len( text.encode() )
            now = now.strip().splitlines()[ -1 ] if now.strip() else ""
            if now and now != state:
                echo( f"  job {job}: {now.lower()}" )
                state = now
            if not now:
                break
    except KeyboardInterrupt:
        host.shell( f"scancel {job}", quiet = True, timeout = 120 )
        echo( f"  job {job} cancelled" )
        return 130
    end = host.shell( f"tail -c +{shown + 1} {out} 2>/dev/null; echo ERRAND_RC=$( cat {rc} 2>/dev/null )",
                      capture = True, timeout = 300 )
    text, _, code = ( end.stdout or "" ).rpartition( "ERRAND_RC=" )
    if text:
        print( text, end = "", flush = True )
    if code.strip().isdigit():
        return int( code.strip() )
    how = host.shell( f"sacct -n -X -P -j {job} -o State", capture = True, timeout = 120 )
    echo( f"  job {job} ended without a return code: {( how.stdout or '' ).strip() or 'killed'}" )
    return 1


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


def interpreters_of( stack ):
    """The layers of `stack` that only CHOOSE AN INTERPRETER ( a venv, a micromamba or conda environment, a uv venv ), in order:
    what a command that only needs errand itself goes through -- the submission a `--batch` preparation makes from inside its
    allocation -- where a container, a module or a variable is not wanted."""
    return [ l for l in stack if isinstance( l, ( Venv, Micromamba, Uv ) ) ]


def ssh_of( stack ):
    return stack[ 0 ] if stack and isinstance( stack[ 0 ], Ssh ) else None


def vm_of( stack ):
    """A machine errand boots ( `errand.Windows` ), recognized by what it says
    of itself so that this module need not import the one that defines it.
    First, or right after the `Ssh` that leads to the machine it runs on."""
    return next( ( l for l in stack if getattr( l, "is_vm", False ) ), None )
