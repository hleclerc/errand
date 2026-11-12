"""Gateways: `Ssh`, which leads to another machine, and the rsync that sends the project there and
brings results back.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .. import agents, bootstrap
from .base import Command, Context, under
from .families import Gateway
from .schedulers import run_on
from .hosts import Over


RSYNC_EXCLUDES = [
    ".git", "runs", "build", "dist", "__pycache__", "*.pyc", "*.so", "*.o",
    "node_modules", "target", ".venv", "*.egg-info", ".mypy_cache", ".pytest_cache",
]


def own_paths() -> list:
    """What the layers of ALL the project's environments build into the project.

    Exact paths, anchored at the root, for rsync to leave alone: an image is not
    a source to copy, and over there `--delete` would take it for a file that
    was removed. All of them, not the ones of the environment being pushed:
    environments share a remote root.
    """
    from .. import config
    found = { os.path.normpath( p ) for e in config.envs.values() for layer in e.stack
              if hasattr( layer, "kept" ) for p in layer.kept() }
    return sorted( f"/{p}" for p in found if not os.path.isabs( p ) and p != "." and not p.startswith( ".." ) )


@dataclass
class Ssh( Gateway ):
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
        push( ctx.root, self.host, remote_ctx.root, self.options, echo = echo )
        for other in self.also:
            # `../loom` lands at `<remote root>/../loom`: the same layout as here
            push( Path( os.path.normpath( ctx.root / other ) ), self.host,
                  Path( os.path.normpath( remote_ctx.root / other ) ), self.options, echo = echo )

        if inner and isinstance( inner[ 0 ], Gateway ):
            # A layer that leads somewhere again -- a machine to boot over
            # there. It does its own work through `there`, and what it brings
            # back into the project's copy over there comes back here in turn.
            code = inner[ 0 ].run( inner[ 1 : ], cmd, remote_ctx, pull = pull, echo = echo )
            pull = [ *( pull or [ ] ), *getattr( inner[ 0 ], "fetch", [ ] ) ]
        elif bootstrap.is_errand( cmd.argv ):
            # errand itself: its sources go over there, and it starts on a
            # Python that is there -- found, or made for it ( `bootstrap` ).
            home = bootstrap.prepare( self, inner, there, echo = echo )
            sent = bootstrap.command( cmd, inner, home, self.python )
            code = run_on( there, inner, sent, remote_ctx, echo = echo )
        else:
            code = run_on( there, inner, Command( under( cmd.argv, self.python ), cmd.env ),
                           remote_ctx, echo = echo )

        if pull:
            echo( f"  rsync pull  <- {self.host}:{remote_ctx.root} [{', '.join( pull )}]" )
            fetch( pull, self.host, remote_ctx.root, ctx.root, self.options )
        return code


def _rsh( options, host = None, agent = True ):
    """rsync must reach the machine ssh reaches, so it gets the same options -- or, with a
    hub to go through, the agent over there is its remote shell, and nothing logs in again."""
    if host and agent and agents.mode() == "hub":
        return [ "-e", agents.upstream.rsh( host, options ) ]
    return [ "-e", "ssh " + " ".join( shlex.quote( o ) for o in options ) ] if options else [ ]


def _remote( host, options, line: str, agent = True ):
    """A shell line on `host`: through its agent when there is a hub, else one ssh."""
    if agent and agents.mode() == "hub":
        try:
            return agents.shell( agents.open( agents.upstream.of_host( host, options ) ), line, capture = True )
        except Exception:
            pass
    return subprocess.run( [ "ssh", *options, host, line ], capture_output = True, text = True,
                           stdin = subprocess.DEVNULL )


def push( local_root: Path, host: str, remote_root: Path, options = ( ), echo = print ):
    made = _remote( host, options, f"mkdir -p {shlex.quote( str( remote_root ) )}" )
    if made.returncode:
        raise subprocess.CalledProcessError( made.returncode, f"mkdir -p {remote_root}", made.stdout, made.stderr )
    # errand's own state is each side's: the records of the runs made over
    # there, its plans, what it built. Excluded, so `--delete` leaves it be.
    from .. import config
    state = config.state_rel( local_root )
    own = [ f"/{state}" ] if not os.path.isabs( state ) else [ ]
    done = subprocess.run( [ "rsync", "-a", "--delete", "-i", *_rsh( options, host ),
                             *[ f"--exclude={e}" for e in RSYNC_EXCLUDES + own + own_paths() ],
                             f"{local_root}/", f"{host}:{remote_root}/" ],
                           check = True, stdout = subprocess.PIPE, text = True, errors = "replace" )
    # Whatever is only over there goes, and it may be the one copy of something
    # somebody put there by hand: at least it does not go silently.
    gone = [ line.split( None, 1 )[ 1 ] for line in done.stdout.splitlines() if line.startswith( "*deleting" ) ]
    for name in gone[ : 20 ]:
        echo( f"    deleted on {host}: {name}" )
    if len( gone ) > 20:
        echo( f"    ...and {len( gone ) - 20} more" )


def fetch( paths, host: str, remote_root: Path, local_root: Path, options = ( ) ):
    """Best effort: a path the remote run never created is nothing to bring back."""
    for p in paths:
        target = local_root / p
        target.mkdir( parents = True, exist_ok = True )
        # A trailing slash on BOTH sides: without it rsync nests the remote
        # directory INSIDE the local one whenever the latter already exists.
        subprocess.run( [ "rsync", "-a", *_rsh( options, host ),
                          f"{host}:{remote_root}/{p}/", f"{target}/" ] )
