"""Gateways: `Ssh`, which leads to another machine, and the sync by manifest, through the agent over there
( ADR 0006 ), that sends the project there and brings results back.
"""
from __future__ import annotations

import os
import posixpath
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .. import agents, bootstrap
from .base import Command, Context, under
from .families import Gateway
from .schedulers import run_on
from .hosts import Over


# What is no part of a copy, and what is built over there, as a sync reads them ( ADR 0006 ).
NOT_COPIED  = [ ".git", "__pycache__", "*.pyc", ".mypy_cache", ".pytest_cache", ".errand-work" ]
DOWNLOADS   = "errand-cache"      # `errand.download`'s cache zone, every project's ( ADR 0013 )
BUILT_THERE = [ "build", "dist", "target", "node_modules", ".venv", "*.egg-info", "*.so", "*.o" ]


def own_paths() -> list:
    """What the layers of ALL the project's environments build into the project.

    Exact paths, anchored at the root, for a push to leave alone: an image is not
    a source to copy, and over there a push would take it for a file that was
    removed. All of them, not the ones of the environment being pushed:
    environments share a remote root.
    """
    from .. import config
    found = { os.path.normpath( p ) for e in config.envs.values() for _, layer in e.layers()
              if hasattr( layer, "kept" ) for p in layer.kept() }
    return sorted( f"/{p}" for p in found if not os.path.isabs( p ) and p != "." and not p.startswith( ".." ) )


def selection( local_root: Path, follow_links = False ):
    """What a push sends, as a sync reads it: the project, minus what is no part of a copy, minus
    its zones -- the project's ( `configure( zones = ... )` ), what the layers of all its
    environments build, and errand's outputs."""
    from .. import config
    from ..sync import Selection, Zone
    rel = config.outputs_rel( local_root )
    # errand's outputs at any depth: a project that holds others ( a checkout of several ) holds theirs too
    zones = [ Zone( f"/{rel}", "errand" ), Zone( f"/{config.LEGACY}", "errand" ),
              Zone( "errand-outputs", "errand" ), Zone( config.LEGACY.strip( "/" ), "errand" ),
              Zone( f"/{DOWNLOADS}", "cache" ),
              *[ Zone( p, kind ) for p, kind in config.zones().items() ],
              *[ Zone( p, "build" ) for p in own_paths() ],
              *[ Zone( p, "build" ) for p in BUILT_THERE ] ]
    return Selection( list( NOT_COPIED ), follow_links, zones )


@dataclass
class Ssh( Gateway ):
    """Must be the first layer. Everything after it runs on `host`.

    `options` are passed to ssh -- a port, an identity file, a `StrictHostKeyChecking` you have
    decided about. The project crosses by manifest, through the agent errand starts there ( ADR 0006 ).

    `user` and `jump` say what a `~/.ssh/config` entry would ( `User`, `ProxyJump` ), so that an
    environment file works for whoever has none: `jump` is a host or a list of them, gone through in
    order ( `"me@gate.example.org"` ), and ends up in `options` as `-J`.
    """
    host   : str
    root   : str | None = None
    python : str = "python3"
    options: list = field( default_factory = list )
    also   : list = field( default_factory = list )   # sibling checkouts the work needs, pushed with the project
    # Where errand writes for the project over there ( runs, builds, state ): a scratch disk, say.
    # The project's copy then holds a link to it, by its usual name ( `errand-outputs` ).
    errand_outputs_directory: str | None = None
    user   : str | None = None
    jump   : str | list | None = None

    def __post_init__( self ):
        # Folded into `host` and `options`, which is all the rest of errand reads ( and all `spec` carries )
        if self.user and "@" not in self.host:
            self.host = f"{self.user}@{self.host}"
        if self.jump:
            hops = [ self.jump ] if isinstance( self.jump, str ) else list( self.jump )
            self.options = [ "-J", ",".join( hops ), *self.options ]
        self.user = self.jump = None

    def describe( self ):
        return f"ssh:{self.host}"

    def remote_root( self, ctx ):
        from .base import WINDOWS
        if WINDOWS:
            there = windows_remote_root( self.root, ctx.root )
            # absolute: an agent's sessions do not start in the home folder
            return there if there.is_absolute() else PurePosixPath( remote_home( self.host, self.options ) ) / there
        return Path( self.root or ctx.root )

    def place( self, ctx ) -> "Over":
        """What the layers after this one are handed as `ctx.host`."""
        return Over( self, self.remote_root( ctx ) )

    def run( self, inner, cmd: Command, ctx: Context, pull = None, echo = print ):
        there = self.place( ctx )
        remote_ctx = Context( root = there.root, tags = ctx.tags, remote = True, host = there,
                              origin = ctx.origin, interactive = ctx.interactive,
                              needs = ctx.needs, batch = ctx.batch, phase = ctx.phase )

        echo( f"  sync push -> {self.host}:{remote_ctx.root}" )
        push( ctx.root, self.host, remote_ctx.root, self.options, echo = echo,
              outputs = self.errand_outputs_directory )
        for other in self.also:
            # `../loom` lands at `<remote root>/../loom`: the same layout as here
            push( Path( os.path.normpath( ctx.root / other ) ), self.host,
                  type( remote_ctx.root )( posixpath.normpath( remote_ctx.root / other ) ), self.options, echo = echo )

        if inner and isinstance( inner[ 0 ], Gateway ):
            # A machine to boot over there: errand runs in it through its agent ( `cli.guest` ), never here.
            raise RuntimeError( f"{inner[ 0 ].describe()} is reached through its agent, not by Ssh.run" )
        if bootstrap.is_errand( cmd.argv ):
            # errand itself: its sources go over there, and it starts on a
            # Python that is there -- found, or made for it ( `bootstrap` ).
            cache = bootstrap.prepare( self, inner, there, echo = echo )
            sent = bootstrap.command( cmd, inner, cache, self.python )
            code = run_on( there, inner, sent, remote_ctx, echo = echo )
        else:
            code = run_on( there, inner, Command( under( cmd.argv, self.python ), cmd.env ),
                           remote_ctx, echo = echo )

        pull = [ *( pull or [ ] ), *back_zones() ]
        if pull:
            echo( f"  sync pull  <- {self.host}:{remote_ctx.root} [{', '.join( pull )}]" )
            fetch( pull, self.host, remote_ctx.root, ctx.root, self.options )
        caches = cache_zones()
        if caches:
            echo( f"  sync pull  <- {self.host}:{remote_ctx.root} [{', '.join( caches )}] ( cache )" )
            fetch( caches, self.host, remote_ctx.root, ctx.root, self.options, keep = True )
        return code


def windows_remote_root( given, local: Path ) -> PurePosixPath:
    """Where the project goes on a POSIX machine reached from Windows, whose own paths mean nothing there: the
    `root` given, else the project's place under the home folder, kept under the remote one ( `Projects/x` ), as
    a POSIX machine mirrors it, else `errand-work/<name>` there. A relative one is under the remote home."""
    if given:
        return PurePosixPath( str( given ).replace( "\\", "/" ) )
    try:
        return PurePosixPath( Path( local ).relative_to( Path.home() ).as_posix() )
    except ValueError:
        return PurePosixPath( "errand-work", Path( local ).name )


_HOMES = { }


def remote_home( host, options ) -> str:
    """The home folder over there, asked once per host and process."""
    key = ( host, tuple( options or ( ) ) )
    if key not in _HOMES:
        got = _remote( host, options, 'printf "%s" "$HOME"', agent = False )
        stop = unreachable( host, got )
        if stop is not None:
            raise stop
        if got.returncode or not got.stdout.strip().startswith( "/" ):
            raise Unreachable( f"{host}: no home folder in what it said ( {( got.stderr or got.stdout ).strip()[ -200 : ]} )" )
        _HOMES[ key ] = got.stdout.strip()
    return _HOMES[ key ]


CONNECT_TIMEOUT = 10     # seconds per address: a host that does not answer is said so, not waited for
ALIVE = ( 15, 4 )        # ServerAliveInterval, ServerAliveCountMax: a dead connection is lost within a minute

# What ssh says, exit code 255, when it never got to run anything over there.
NOT_REACHED = ( "connect to host", "could not resolve hostname", "timed out", "no route to host",
                "connection refused", "connection closed by", "permission denied", "host key verification failed" )


class Unreachable( RuntimeError ):
    """ssh could not log in: nothing errand does on that host can work, so it stops, once."""


# What cmd.exe and PowerShell say of `true`, the first word errand sends a machine it meets: a Windows.
ON_WINDOWS = ( "is not recognized as an internal or external command", "is not recognized as the name of a cmdlet" )


def unreachable( host: str, got ) -> "Unreachable | None":
    """The error to stop with when `got` ( a finished ssh ) never reached `host` -- or reached a Windows, which an
    `Ssh` alone cannot work on."""
    said = ( getattr( got, "stderr", "" ) or "" ).strip()
    if getattr( got, "returncode", 0 ) and any( s in said for s in ON_WINDOWS ):
        return Unreachable( f"{host} is a Windows: reach it with [ Ssh( host = {host!r} ), WindowsBox() ], "
                            "and `errand setup` it once" )
    if getattr( got, "returncode", 0 ) != 255 or not any( s in said.lower() for s in NOT_REACHED ):
        return None
    last = [ l for l in said.splitlines() if l.strip() ][ -1 : ]
    return Unreachable( f"cannot reach {host}: {last[ 0 ] if last else 'ssh failed'}\n"
                        f"  `ssh {host} true` must work from this terminal. A cluster that only lets some\n"
                        f"  addresses in needs the name your ~/.ssh/config routes through a jump host ( ProxyJump )" )


def ssh_options( options ) -> list:
    """`options`, and unless they set them: a connect timeout -- a host behind a filter ( a cluster
    that only lets some addresses in ) otherwise hangs ssh without a word -- and keepalives -- a
    connection left half-open by a laptop asleep or a NAT that forgot it is said lost within a
    minute, instead of blocking whoever waits on it for ever ( ADR 0008 )."""
    options = list( options or [ ] )
    said = " ".join( str( o ) for o in options ).lower()
    for key, value in ( ( "ConnectTimeout", CONNECT_TIMEOUT ), ( "ServerAliveInterval", ALIVE[ 0 ] ),
                        ( "ServerAliveCountMax", ALIVE[ 1 ] ) ):
        if key.lower() not in said:
            options += [ "-o", f"{key}={value}" ]
    return options


def _remote( host, options, line: str, agent = True, interactive = False, input: bytes | None = None ):
    """A shell line on `host`: through its agent when there is a hub, else one ssh. `interactive`:
    in the user's interactive shell, as the agent's own is, for a line that needs what the
    profile sets ( `ERRAND_CACHE_DIR` ). `input`: bytes on its stdin ( errand's sources, a tar )."""
    if agent and agents.mode() == "hub":
        try:
            return agents.shell( agents.open( agents.upstream.of_host( host, options ) ), line, capture = True,
                                 input = input )
        except Exception as err:
            if "the agent: cannot reach " in str( err ):
                raise Unreachable( str( err ).split( "the agent: ", 1 )[ -1 ] ) from None
    if interactive:
        line = f"$SHELL -ic {shlex.quote( line )}"
    done = subprocess.run( [ "ssh", *ssh_options( options ), host, line ], capture_output = True,
                           input = input, stdin = None if input is not None else subprocess.DEVNULL )
    return subprocess.CompletedProcess( done.args, done.returncode, done.stdout.decode( errors = "replace" ),
                                        done.stderr.decode( errors = "replace" ) )


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
    # `true` first: on a Windows ( an `Ssh` without its `WindowsBox` ), nothing after it runs, and what it says tells.
    line = f"true && mkdir -p {q( str( remote_root ) )} && cd {q( str( remote_root ) )}"
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
    # errand's outputs are each side's: the records of the runs made over there, its plans, what it
    # built. Left by the push, as the project's zones ( `configure( zones = ... )` ) are.
    return _push_sync( local_root, host, remote_root, options, echo )


def _say_kept_runs( kept, host, echo ):
    from .. import results as R
    marks = { R.RESULT, *R.RUN_MARKS }
    runs = sorted( { k.rpartition( "/" )[ 0 ] for k in kept if "/" in k and k.rpartition( "/" )[ 2 ] in marks } )
    if runs:
        echo( f"    {len( runs )} run director{'y' if len( runs ) == 1 else 'ies'} made there, kept, "
              f"not in the project here ( {runs[ 0 ]}{', …' if len( runs ) > 1 else ''} ). Said once" )


def _push_sync( local_root: Path, host: str, remote_root, options, echo ):
    """The push by manifest, through the host's agent ( `agents/syncop.py` )."""
    from .. import config
    from ..agents import syncop, upstream
    conn = agents.open( upstream.of_host( host, options ) )
    r = syncop.push( conn, local_root, remote_root, selection( local_root ),
                     src_cache = config.state( local_root ) / "sync" / "src.json", where = host, say = echo )
    for name in r.deleted[ : 20 ]:
        echo( f"    deleted there: {name}" )
    if len( r.deleted ) > 20:
        echo( f"    ...and {len( r.deleted ) - 20} more" )
    _say_kept_runs( r.kept_runs, host, echo )
    return r                    # its numbers: in the journal of each run ( `drive._counted`, ADR 0016 )


def back_zones( env_name = None ) -> list:
    """The project's zones written over there to be brought back ( `configure( zones = ... )`, a runner's
    `zones` ), that name one path: those a command brings back. One named anywhere ( no leading `/` )
    is not looked for."""
    from .. import config
    return sorted( p.strip( "/" ) for p, kind in config.zones( env_name ).items()
                   if kind == "back" and p.startswith( "/" ) and not any( c in p for c in "*?[" ) )


def cache_zones( env_name = None ) -> list:
    """The project's cache zones ( ADR 0012 ) that name one path: those a command brings back, adding
    only what is missing here. One named anywhere is only pushed."""
    from .. import config
    return sorted( { DOWNLOADS, *( p.strip( "/" ) for p, kind in config.zones( env_name ).items()
                                   if kind == "cache" and p.startswith( "/" ) and not any( c in p for c in "*?[" ) ) } )


def _fetch_sync( paths, host: str, remote_root, local_root: Path, options, finished_only = False, keep = False ):
    from ..agents import syncop, upstream
    from .base import WINDOWS
    from ..sync import Selection
    conn = agents.open( upstream.of_host( host, options ) )
    return syncop.pull( conn, remote_root, local_root, [ Path( p ).as_posix() for p in paths ],
                        sel = Selection( list( NOT_COPIED ) ) if keep else None,
                        where = host, links = not WINDOWS, finished_only = finished_only, keep = keep )


def put( local_dir: Path, host: str, remote_dir, options = ( ), echo = print ):
    """`remote_dir` over there made the same as `local_dir` here, and nothing else touched: what a
    preparation built, carried to the copy that runs it ( ADR 0011 ). Dates are kept, so a build tool
    there finds it up to date."""
    from .. import sync as S
    from ..agents import syncop, upstream
    conn = agents.open( upstream.of_host( host, options ) )
    return syncop.push( conn, local_dir, remote_dir, S.Selection( [ ], False, [ ] ), where = host, say = echo )


def fetch_file( path: str, host: str, remote_root, local_root: Path, options = ( ), say = print ):
    """One file of the copy, `path` from its root, brought back at once ( a view, `cli.views` ), its date kept:
    the run's own coming back finds it as it is and leaves it. Raises when it could not come."""
    path = Path( path ).as_posix()
    target = Path( local_root ) / path
    target.parent.mkdir( parents = True, exist_ok = True )
    from ..agents import syncop, upstream
    conn = agents.open( upstream.of_host( host, options ) )
    for _ in range( 3 ):                    # rewritten while read, twice: read again, the run is still at it
        if not syncop.pull( conn, remote_root, local_root, [ path ], where = host, say = say ).unstable:
            break
    if not target.is_file():
        raise FileNotFoundError( f"{host}:{remote_root}/{path}" )


def fetch( paths, host: str, remote_root: Path, local_root: Path, options = ( ), finished_only = False, keep = False ):
    """Best effort: a path the remote run never created is nothing to bring back. Nothing here is
    deleted. `finished_only`: the paths are run trees, and a run comes back only once it has written
    its `result.yaml` ( `results.unfinished_runs` ): never half of one. `keep`: the paths are caches
    ( ADR 0012 ), and a file already here is not replaced."""
    return _fetch_sync( paths, host, remote_root, local_root, options, finished_only = finished_only, keep = keep )
