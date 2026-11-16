"""Gateways: `Ssh`, which leads to another machine, and the rsync that sends the project there and
brings results back.
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


RSYNC_EXCLUDES = [
    ".git", "build", "dist", "__pycache__", "*.pyc", "*.so", "*.o",
    "node_modules", "target", ".venv", "*.egg-info", ".mypy_cache", ".pytest_cache",
]
# The same, as a sync reads them ( ADR 0006 ): what is no part of a copy, and what is built over there.
NOT_COPIED  = [ ".git", "__pycache__", "*.pyc", ".mypy_cache", ".pytest_cache" ]
BUILT_THERE = [ "build", "dist", "target", "node_modules", ".venv", "*.egg-info", "*.so", "*.o" ]


def own_paths() -> list:
    """What the layers of ALL the project's environments build into the project.

    Exact paths, anchored at the root, for rsync to leave alone: an image is not
    a source to copy, and over there `--delete` would take it for a file that
    was removed. All of them, not the ones of the environment being pushed:
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
              *[ Zone( p, kind ) for p, kind in config.zones().items() ],
              *[ Zone( p, "build" ) for p in own_paths() ],
              *[ Zone( p, "build" ) for p in BUILT_THERE ] ]
    return Selection( list( NOT_COPIED ), follow_links, zones )


@dataclass
class Ssh( Gateway ):
    """Must be the first layer. Everything after it runs on `host`.

    `options` are passed to both ssh and rsync -- a port, an identity file, a
    `StrictHostKeyChecking` you have decided about. rsync has to get the same
    ones or it reaches a different machine than ssh does.

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
    # How the project crosses: by manifest through the host's agent ( "sync", the default, ADR 0006 ), or
    # "rsync", whose delta wins for a large file that changes a little. `ERRAND_TRANSFER` overrides it.
    transfer: str | None = None
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

        echo( f"  {transfer( self.transfer )} push -> {self.host}:{remote_ctx.root}" )
        push( ctx.root, self.host, remote_ctx.root, self.options, echo = echo,
              outputs = self.errand_outputs_directory, transfer_by = self.transfer )
        for other in self.also:
            # `../loom` lands at `<remote root>/../loom`: the same layout as here
            push( Path( os.path.normpath( ctx.root / other ) ), self.host,
                  type( remote_ctx.root )( posixpath.normpath( remote_ctx.root / other ) ), self.options, echo = echo,
                  transfer_by = self.transfer )

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
            echo( f"  {transfer( self.transfer )} pull  <- {self.host}:{remote_ctx.root} [{', '.join( pull )}]" )
            fetch( pull, self.host, remote_ctx.root, ctx.root, self.options, transfer_by = self.transfer )
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


def rsync( ) -> list:
    """rsync on this machine: the one on the PATH, or, errand started on Windows, MSYS2's ( pinned, unpacked into
    errand's cache on first use ), which reads `/c/...` for `C:\\...`."""
    from .base import WINDOWS
    if not WINDOWS:
        return [ "rsync" ]
    from ..vm.box import local_rsync
    return [ str( local_rsync() ) ]


def here( path ) -> str:
    """A path of this machine, as `rsync()` reads it."""
    from .base import WINDOWS
    if not WINDOWS:
        return str( path )
    from ..vm.transfer import msys_path
    tail = "/" if str( path ).endswith( ( "/", "\\" ) ) else ""
    return msys_path( str( path ) ) + tail


def _rsh( options, host = None, agent = True ):
    """rsync must reach the machine ssh reaches, so it gets the same options -- or, with a
    hub to go through, the agent over there is its remote shell, and nothing logs in again."""
    if host and agent and agents.mode() == "hub":
        return [ "-e", agents.upstream.rsh( host, options ) ]
    from .base import WINDOWS
    ssh = "ssh"
    if WINDOWS:
        # MSYS2's rsync talks to MSYS2's ssh only: Windows' ssh.exe reads its pipes as closed
        from ..vm.box import local_ssh
        from ..vm.transfer import msys_path
        ssh = msys_path( str( local_ssh() ) )
    return [ "-e", ssh + " " + " ".join( shlex.quote( o ) for o in ssh_options( options ) ) ]


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


def transfer( chosen = None ) -> str:
    """How a push crosses: `ERRAND_TRANSFER`, else the `Ssh`'s `transfer`, else a sync ( ADR 0006 )."""
    got = ( os.environ.get( "ERRAND_TRANSFER" ) or chosen or "sync" ).strip().lower()
    if got not in ( "rsync", "sync" ):
        raise ValueError( f"transfer {got!r}: rsync or sync" )
    return got


def push( local_root: Path, host: str, remote_root: Path, options = ( ), echo = print, outputs = None,
          transfer_by = None ):
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
    # errand's outputs are each side's: the records of the runs made over
    # there, its plans, what it built. Excluded, so `--delete` leaves them be,
    # as the project's zones ( `configure( zones = ... )` ) are.
    if transfer( transfer_by ) == "sync":
        return _push_sync( local_root, host, remote_root, options, echo )
    # The copy's manifest for the sync ( ADR 0006 ) too: switching between the two keeps it.
    own = [ f"/{rel}", f"/{config.LEGACY}", "/.errand-copy*" ]
    done = subprocess.run( [ *rsync(), "-a", "--delete", "-i", *_rsh( options, host ),
                             *[ f"--exclude={e}" for e in RSYNC_EXCLUDES + own + own_paths()
                                                          + list( config.zones() ) ],
                             here( f"{local_root}/" ), f"{host}:{remote_root}/" ],
                           check = True, stdout = subprocess.PIPE, text = True, errors = "replace" )
    # Whatever is only over there goes, and it may be the one copy of something
    # somebody put there by hand: at least it does not go silently.
    gone = [ line.split( None, 1 )[ 1 ] for line in done.stdout.splitlines() if line.startswith( "*deleting" ) ]
    for name in gone[ : 20 ]:
        echo( f"    deleted on {host}: {name}" )
    if len( gone ) > 20:
        echo( f"    ...and {len( gone ) - 20} more" )


def _push_sync( local_root: Path, host: str, remote_root, options, echo ):
    """The push by manifest, through the host's agent ( `agents/syncop.py` )."""
    from .. import config
    from ..agents import syncop, upstream
    conn = agents.open( upstream.of_host( host, options ) )
    r = syncop.push( conn, local_root, remote_root, selection( local_root ),
                     src_cache = config.state( local_root ) / "sync" / "src.json", where = host, say = echo )
    for name in r.deleted[ : 20 ]:
        echo( f"    deleted on {host}: {name}" )
    if len( r.deleted ) > 20:
        echo( f"    ...and {len( r.deleted ) - 20} more" )
    if r:
        echo( f"    {len( r.sent )} sent ( {r.bytes / 1e6:.1f} MB ), {len( r.touched )} touched, "
              f"{len( r.deleted )} deleted" )
    return r


def back_zones( env_name = None ) -> list:
    """The project's zones written over there to be brought back ( `configure( zones = ... )`, a runner's
    `zones` ), that name one path: those a command brings back. One named anywhere ( no leading `/` )
    is not looked for."""
    from .. import config
    return sorted( p.strip( "/" ) for p, kind in config.zones( env_name ).items()
                   if kind == "back" and p.startswith( "/" ) and not any( c in p for c in "*?[" ) )


def _fetch_sync( paths, host: str, remote_root, local_root: Path, options ):
    from ..agents import syncop, upstream
    from .base import WINDOWS
    conn = agents.open( upstream.of_host( host, options ) )
    return syncop.pull( conn, remote_root, local_root, [ Path( p ).as_posix() for p in paths ],
                        where = host, links = not WINDOWS )


def put( local_dir: Path, host: str, remote_dir, options = ( ), transfer_by = None, echo = print ):
    """`remote_dir` over there made the same as `local_dir` here, and nothing else touched: what a
    preparation built, carried to the copy that runs it ( ADR 0011 ). Dates are kept, so a build tool
    there finds it up to date."""
    if transfer( transfer_by ) == "sync":
        from .. import sync as S
        from ..agents import syncop, upstream
        conn = agents.open( upstream.of_host( host, options ) )
        return syncop.push( conn, local_dir, remote_dir, S.Selection( [ ], False, [ ] ), where = host, say = echo )
    remote = str( remote_dir )
    subprocess.run( [ *rsync(), "-a", "--delete", *_rsh( options, host ),
                      f"--rsync-path=mkdir -p {shlex.quote( remote )} && rsync",
                      here( f"{local_dir}/" ), f"{host}:{remote}/" ], check = True )


def fetch( paths, host: str, remote_root: Path, local_root: Path, options = ( ), transfer_by = None ):
    """Best effort: a path the remote run never created is nothing to bring back."""
    if transfer( transfer_by ) == "sync":
        return _fetch_sync( paths, host, remote_root, local_root, options )
    for p in paths:
        target = local_root / p
        p = Path( p ).as_posix()        # a path over there: `a/b`, though this is a Windows
        target.mkdir( parents = True, exist_ok = True )
        # A trailing slash on BOTH sides: without it rsync nests the remote
        # directory INSIDE the local one whenever the latter already exists.
        from .base import WINDOWS
        # a link ( a run's `latest` ) is not made on a Windows without its developer mode: left over there
        subprocess.run( [ *rsync(), "-a", *( [ "--no-links" ] if WINDOWS else [ ] ), *_rsh( options, host ),
                          f"{host}:{remote_root}/{p}/", here( f"{target}/" ) ] )
