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
    ".git", "build", "dist", "__pycache__", "*.pyc", "*.so", "*.o",
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
    # Where errand writes for the project over there ( runs, builds, state ): a scratch disk, say.
    # The project's copy then holds a link to it, by its usual name ( `errand-outputs` ).
    errand_outputs_directory: str | None = None

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
        push( ctx.root, self.host, remote_ctx.root, self.options, echo = echo,
              outputs = self.errand_outputs_directory )
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
            cache = bootstrap.prepare( self, inner, there, echo = echo )
            sent = bootstrap.command( cmd, inner, cache, self.python )
            code = run_on( there, inner, sent, remote_ctx, echo = echo )
        else:
            code = run_on( there, inner, Command( under( cmd.argv, self.python ), cmd.env ),
                           remote_ctx, echo = echo )

        if pull:
            echo( f"  rsync pull  <- {self.host}:{remote_ctx.root} [{', '.join( pull )}]" )
            fetch( pull, self.host, remote_ctx.root, ctx.root, self.options )
        return code


CONNECT_TIMEOUT = 10     # seconds per address: a host that does not answer is said so, not waited for

# What ssh says, exit code 255, when it never got to run anything over there.
NOT_REACHED = ( "connect to host", "could not resolve hostname", "timed out", "no route to host",
                "connection refused", "connection closed by", "permission denied", "host key verification failed" )


class Unreachable( RuntimeError ):
    """ssh could not log in: nothing errand does on that host can work, so it stops, once."""


def unreachable( host: str, got ) -> "Unreachable | None":
    """The error to stop with when `got` ( a finished ssh ) never reached `host`."""
    said = ( getattr( got, "stderr", "" ) or "" ).strip()
    if getattr( got, "returncode", 0 ) != 255 or not any( s in said.lower() for s in NOT_REACHED ):
        return None
    last = [ l for l in said.splitlines() if l.strip() ][ -1 : ]
    return Unreachable( f"cannot reach {host}: {last[ 0 ] if last else 'ssh failed'}\n"
                        f"  `ssh {host} true` must work from this terminal. A cluster that only lets some\n"
                        f"  addresses in needs the name your ~/.ssh/config routes through a jump host ( ProxyJump )" )


def ssh_options( options ) -> list:
    """`options`, and a connect timeout unless they set one: a host behind a filter
    ( a cluster that only lets some addresses in ) otherwise hangs ssh without a word."""
    options = list( options or [ ] )
    if any( "connecttimeout" in str( o ).lower() for o in options ):
        return options
    return [ *options, "-o", f"ConnectTimeout={CONNECT_TIMEOUT}" ]


def _rsh( options, host = None, agent = True ):
    """rsync must reach the machine ssh reaches, so it gets the same options -- or, with a
    hub to go through, the agent over there is its remote shell, and nothing logs in again."""
    if host and agent and agents.mode() == "hub":
        return [ "-e", agents.upstream.rsh( host, options ) ]
    return [ "-e", "ssh " + " ".join( shlex.quote( o ) for o in ssh_options( options ) ) ]


def _remote( host, options, line: str, agent = True, interactive = False ):
    """A shell line on `host`: through its agent when there is a hub, else one ssh. `interactive`:
    in the user's interactive shell, as the agent's own is, for a line that needs what the
    profile sets ( `ERRAND_CACHE_DIR` )."""
    if agent and agents.mode() == "hub":
        try:
            return agents.shell( agents.open( agents.upstream.of_host( host, options ) ), line, capture = True )
        except Exception as err:
            if "the agent: cannot reach " in str( err ):
                raise Unreachable( str( err ).split( "the agent: ", 1 )[ -1 ] ) from None
    if interactive:
        line = f"$SHELL -ic {shlex.quote( line )}"
    return subprocess.run( [ "ssh", *ssh_options( options ), host, line ], capture_output = True, text = True,
                           stdin = subprocess.DEVNULL )


LINK_OUTPUTS = r"""
o="$1"; d="$2"
mkdir -p "$d" || exit 1
if [ -d "$o" ] && [ ! -L "$o" ]; then           # what was written before: into the new place
    for p in "$o"/* "$o"/.[!.]*; do [ -e "$p" ] && [ ! -e "$d/${p##*/}" ] && mv "$p" "$d/"; done
    rmdir "$o" 2>/dev/null || { echo "errand: $o is not empty, $d not linked" >&2; exit 0; }
fi
ln -sfn "$d" "$o"
"""


def push( local_root: Path, host: str, remote_root: Path, options = ( ), echo = print, outputs = None ):
    """The project to its copy over there, which errand's outputs there are not part of. On the way,
    `outputs` ( `Ssh( errand_outputs_directory )` ) linked in, and a `.errand` of before moved."""
    from .. import config
    rel = config.outputs_rel( local_root )
    q = shlex.quote
    line = f"mkdir -p {q( str( remote_root ) )} && cd {q( str( remote_root ) )}"
    if outputs:
        line += f" && sh -c {q( LINK_OUTPUTS )} sh {q( rel )} {q( str( outputs ) )}"
    line += f" && sh -c {q( config.MIGRATE_SH )} sh {q( rel )}"
    made = _remote( host, options, line )
    stop = unreachable( host, made )
    if stop is not None:
        raise stop
    if made.returncode:
        raise subprocess.CalledProcessError( made.returncode, f"mkdir -p {remote_root}", made.stdout, made.stderr )
    for said in ( made.stderr or "" ).splitlines():
        if said.startswith( "errand:" ):
            echo( f"  {said}" )
    # errand's outputs are each side's: the records of the runs made over
    # there, its plans, what it built. Excluded, so `--delete` leaves them be.
    own = [ f"/{rel}", f"/{config.LEGACY}" ]
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
