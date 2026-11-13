"""Containers: an Apptainer image, a Docker or Podman one, built from a recipe and kept current.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .base import _quiet, Command, Context, file_stamp, sh, under
from .families import Artefact, Container
from .gateways import push, Ssh, ssh_options
from .hosts import Over


@dataclass
class Apptainer( Container, Artefact ):
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

    # `apptainer exec` mounts the image ( squashfuse ) for as long as the process it
    # started runs: an agent detached from it would keep running on an unmounted image
    # ( `Transport endpoint is not connected` on its own interpreter ).
    agent_may_detach = False

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

    def identity( self ):
        return f"apptainer:{self.image}"     # `describe` alone: a/cuda.sif and b/cuda.sif are one thing

    @property
    def aside( self ):
        """Built next to the image it replaces: failing costs nothing, so a
        build can be attempted on no more than a suspicion."""
        return bool( self.recipe )

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

    def stamp_shell( self, ctx ):
        return file_stamp( shlex.quote( self.image ) )

    def kept( self ):
        return [ self.image, *[ f"{self.image}.{end}" for end in ( "new", "prev", "part" ) ] ]

    def abandon( self, ctx ):
        return sh( [ "rm", "-f", f"{self.image}.new" ] )

    def build( self, ctx ):
        if not self.recipe:
            return [ ]     # an image someone else builds; nothing to say about it
        # Never through wrap(): that runs a command INSIDE the image, which does
        # not exist yet while it is being built.
        #
        # Beside the image, which stays whole and usable until the new one is
        # complete: a build that fails has then cost nothing. On a builder the
        # image is only a copy on its way, and `relay` does the same at the end.
        #
        # `--force` unconditionally: a `.new` left by an interrupted build must
        # not stand in the way of the next one.
        # ( the builder's own apptainer: `exe` is what the place it RUNS calls it )
        target = self.image if self.build_on else f"{self.image}.new"
        argv = [ "apptainer" if self.build_on else self.exe, "build", "--force",
                 *( [ "--fakeroot" ] if self.fakeroot else [ ] ), *self.build_flags,
                 target, self.recipe ]
        # Both, and to the same place: apptainer writes its unpacked layers to
        # one and its downloads to the other, and a build that runs out of room
        # in either dies the same way.
        room = [ f"{k}={self.scratch}" for k in ( "APPTAINER_TMPDIR", "APPTAINER_CACHEDIR" ) ] \
               if self.scratch else [ ]
        steps = [ " ".join( [ *room, sh( argv ) ] ) ]
        if self.pip:
            steps.append( sh( [ argv[ 0 ], "exec", target,
                                "python", "-m", "pip", "install", *self.pip ] ) )
        if self.build_on is not None:
            steps = [ _BuiltElsewhere( self, steps, ctx ) ]
        else:
            steps.append( replace_line( target, self.image ) )
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
        push( self.ctx.origin, b.ssh.host, b.root, b.ssh.options, echo = echo )
        for step in self.steps:
            echo( f"    $ {step}    ( on {b.describe()} )" )
            if b.shell( step, tty = True ).returncode != 0:
                return 1
        echo( f"    copying {image}: {b.describe()} -> {self.ctx.host.describe()}" )
        return relay( b, b.root / image, self.ctx.host, image )


def replace_line( new, image ) -> str:
    """A shell line putting `new` in the place of `image`. The image it replaces
    is kept, once: a recipe that downloads what it likes cannot always rebuild
    it, and a build that succeeds can still give something that does not work."""
    new, image = shlex.quote( str( new ) ), shlex.quote( str( image ) )
    return f"if test -e {image}; then mv -f {image} {image}.prev; fi; mv -f {new} {image}"


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
            return subprocess.run( [ "ssh", *ssh_options( dest.ssh.options ), dest.ssh.host, root + line ], **how ).returncode
        return subprocess.run( [ "sh", "-c", line ], cwd = str( dest.root ), **how ).returncode

    src = subprocess.Popen( [ "ssh", *ssh_options( source.ssh.options ), source.ssh.host, f"cat {shlex.quote( str( path ) )}" ],
                            stdout = subprocess.PIPE )
    code = on_dest( f"mkdir -p \"$( dirname {q} )\" && cat > {q}.part", stdin = src.stdout )
    src.stdout.close()
    code = src.wait() or code
    return on_dest( f"rm -f {q}.part" ) or code if code else on_dest( replace_line( f"{rel}.part", rel ) )


@dataclass
class Docker( Container, Artefact ):
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

    def stamp_shell( self, ctx ):
        return sh( [ self.engine, "image", "inspect", "-f", "{{.Id}} {{.Created}}", self.image ] )

    def made( self, stamp ):
        created = stamp.split()[ -1 ].split( "." )[ 0 ].rstrip( "Z" )
        return datetime.fromisoformat( created ).replace( tzinfo = timezone.utc ).timestamp()

    @property
    def aside( self ):
        return bool( self.recipe )       # a tag only moves once `build -t` has succeeded

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
