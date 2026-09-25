"""The command line."""
from __future__ import annotations

import argparse
import contextlib
import io
import itertools
import os
import sys
import time
import traceback
from pathlib import Path

from . import batch, config, discovery, entries as E, history, layers as L, local, providers as P, queue, results as R, setup

BOLD, DIM, GREEN, RED, YELLOW, CYAN, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[0m" )

if not sys.stdout.isatty() or os.environ.get( "NO_COLOR" ):
    BOLD = DIM = GREEN = RED = YELLOW = CYAN = RESET = ""


def dim( s ):   return f"{DIM}{s}{RESET}"
def head( s ):  return f"{BOLD}{CYAN}{s}{RESET}"
def bad( s ):   return f"{RED}{s}{RESET}"
def good( s ):  return f"{GREEN}{s}{RESET}"
def warn( s ):  return f"{YELLOW}{s}{RESET}"


KINDS = { "test": "test", "bench": "bench", "experiment": "experiment", "exp": "experiment" }

# Set on the child side of a dispatch: the environment has already been entered
# by the layers that wrapped this process, so re-selecting it here would send it
# round again -- and, over ssh, straight back out to the machine it is on.
IN_ENV = "ERRAND_IN_ENV"
TAGS   = "ERRAND_TAGS"


def find_root( start: Path | None = None ) -> Path:
    """The project root: the nearest ancestor holding an errand.py, else here.

    Deliberately not the git root. Walking up to one means that running from a
    subdirectory of a large repository silently widens the search to the whole
    of it -- and with no errand.py there is nothing that says where the project
    begins, so "here and below" is the answer least likely to surprise.
    """
    here = ( start or Path.cwd() ).resolve()
    for directory in [ here, *here.parents ]:
        if config.config_in( directory ) is not None:
            return directory
    return here


class Tee:
    def __init__( self, *streams ):
        self._streams = streams

    def write( self, s ):
        for st in self._streams:
            st.write( s )
        return len( s )

    def flush( self ):
        for st in self._streams:
            st.flush()

    def isatty( self ):
        return False


@contextlib.contextmanager
def capture( path: Path | None = None ):
    """Mirror stdout/stderr into a buffer -- and into `path` -- while still
    printing live.

    The file is written AS IT GOES, not at the end: it is the only place a case
    running elsewhere, or beside seven others under `-j`, says anything at all.
    `tail -f` works on it, and so does the screen, which is the same thing.
    """
    buf = io.StringIO()
    handle = None
    if path is not None:
        try:
            handle = open( path, "w", buffering = 1 )
        except OSError:
            handle = None                # a run must not fail over its own log
    old_out, old_err = sys.stdout, sys.stderr
    streams = [ old_out, buf ] + ( [ handle ] if handle else [ ] )
    sys.stdout, sys.stderr = Tee( *streams ), Tee( old_err, buf, *( [ handle ] if handle else [ ] ) )
    try:
        yield buf
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        if handle:
            handle.close()


@contextlib.contextmanager
def _with_env( values: dict ):
    """Set, then put back exactly what was there -- including nothing."""
    before = { k: os.environ.get( k ) for k in values }
    os.environ.update( values )
    try:
        yield
    finally:
        for k, old in before.items():
            if old is None:
                os.environ.pop( k, None )
            else:
                os.environ[ k ] = old


# ── matrices ─────────────────────────────────────────────────────────────────

def expand( raw_values: dict, params: dict ):
    """`--n=1000,5000` is an axis. -> [ ( varied, { name: value } ), ... ].

    Values arrive as strings precisely so a comma can be seen before the type
    is applied; `varied` holds only what actually had several values, so the
    non-matrix case stays silent.
    """
    axes = { }
    for name, raw in raw_values.items():
        if raw is None:
            continue
        p = params[ name ]
        parts = raw.split( "," ) if isinstance( raw, str ) else [ raw ]
        try:
            values = [ p.ptype( x ) for x in parts ]
        except ( TypeError, ValueError ):
            raise ValueError( f"--{name.replace( '_', '-' )}: cannot read {raw!r} "
                              f"as {p.ptype.__name__}" )
        if p.choices:
            wrong = [ v for v in values if v not in p.choices ]
            if wrong:
                raise ValueError( f"--{name.replace( '_', '-' )}: {wrong} not in {p.choices}" )
        axes[ name ] = values

    if not axes:
        return [ ( { }, { } ) ]
    names = list( axes )
    out = [ ]
    for combo in itertools.product( *( axes[ n ] for n in names ) ):
        chosen = dict( zip( names, combo ) )
        varied = { n: v for n, v in chosen.items() if len( axes[ n ] ) > 1 }
        out.append( ( varied, chosen ) )
    return out


def split_values( raw ):
    """A comma means a matrix, on a tag exactly as on a parameter."""
    if raw is None:
        return [ None ]
    return [ v.strip() for v in str( raw ).split( "," ) if v.strip() ]


# ── running, here ────────────────────────────────────────────────────────────

class Report:
    def __init__( self ):
        self.failed  = [ ]
        self.skipped = [ ]
        self.broken  = [ ]      # files that declare work and would not import


def aggregate_needs( entries ):
    """What one command carries, as one machine's worth of asking.

    A dispatched command runs SEVERAL entries in one allocation, so the
    allocation has to be the largest of them -- and exclusive if any one of
    them is.
    """
    out = { }
    for e in entries:
        for key, value in queue.normalize( e.resources ).items():
            out[ key ] = max( out.get( key, 0.0 ), value )
        if e.traits[ "exclusive" ]:
            out[ "exclusive" ] = True
    return out


def run_entries( entries, modules, *, root, out_root, overrides, env_name, tags,
                 version, report, queued = True, quiet = False, selectors = None ):
    E.set_tags( tags )
    selectors = selectors or { }
    where = R.place( env_name )
    if not quiet:
        print( head( f"\n{'=' * 10} {len( entries )} entr{'y' if len( entries ) == 1 else 'ies'}"
                     f"  {env_name}  {where} {'=' * 10}" ), flush = True )

    for e in entries:
        try:
            resolved = E.resolve_params( e.params, overrides )
        except ValueError as err:
            print( bad( f"  {e.name}: {err}" ) )
            report.failed.append( ( e, str( err ) ) )
            continue

        leaf, entry_root = R.dirs_for( out_root, e, resolved, where )
        R.clear( leaf )
        R.point_latest_at( leaf )

        site = f"{e.file.name}:{e.line}"
        if resolved:
            shown = ", ".join( f"{k}={v!r}" for k, v in resolved.items() )
            print( dim( f"  {e.name} ({site}) -- {shown}" ), flush = True )

        E.begin_run( e, resolved, leaf )
        status, error, hint = "PASS", None, None
        # The claim is taken OUTSIDE the timing: waiting for the machine is not
        # part of how long the work takes, and recording it as if it were would
        # make a benchmark's numbers depend on who else was busy.
        with queue.claim( e.resources, exclusive = e.traits[ "exclusive" ],
                          label = f"{e.file.name}::{e.name}", enabled = queued,
                          echo = lambda m: print( dim( m ), flush = True ) ) as granted:
            # Being told WHICH card is the whole point of asking for one: two
            # entries that both picked the first would share it and neither
            # would measure anything.
            # Everything this entry starts inherits the claim: an errand it
            # runs must not queue for a machine its own parent is holding.
            handed = { **granted.env(), **granted.handed_down() } if granted else { }
            with _with_env( handed ):
                if granted and granted.devices and granted.path:
                    print( dim( f"  gpu {','.join( str( d ) for d in granted.devices )}" ),
                           flush = True )
                started = time.perf_counter()
                with capture( leaf / R.OUTPUT ) as buf:
                    try:
                        if e.provider is None:
                            if e.module not in modules:
                                # It was registered while ANOTHER file imported
                                # this one: there are now two of every entry it
                                # declares, and this copy belongs to an import
                                # errand did not make and cannot repeat.
                                raise RuntimeError(
                                    f"{e.file.name} was imported by another file rather than "
                                    f"read on its own, so everything it declares is declared "
                                    f"twice.\n  a file that declares work is not a module to "
                                    f"import from -- move what is shared into one that declares "
                                    f"none ( a name starting with `_` is the usual sign )" )
                            discovery.import_file( modules[ e.module ], root )
                        else:
                            # Somebody else's suite: it runs itself, and only
                            # says what came of it. Everything around the run
                            # is the same as for anything here.
                            got = e.provider.run( e, P.RunContext(
                                root = root, out_dir = leaf, params = resolved,
                                env = dict( handed ), selector = selectors.get( e.name ) ) )
                            status, error = got.status, got.error
                            E.results.update( got.results )
                            if got.output:
                                print( got.output, end = "" )
                    except local.Skipped as s:
                        status, error, hint = "SKIP", s.reason, s.hint
                    except BaseException as exc:         # SystemExit included
                        status, error = "FAIL", f"{type( exc ).__name__}: {exc}"
                        traceback.print_exc()
                duration = time.perf_counter() - started
        E.end_run()

        if status == "PASS":
            print( f"{GREEN}PASS{RESET} {e.name} {dim( f'({site})' )}", flush = True )
            if e.traits[ "stable_path" ]:
                # What it produced IS the point, so name the files and the path
                # to open rather than leave it to be reconstructed.
                written = sorted( f.name for f in leaf.iterdir()
                                  if f.name not in ( R.RESULT, R.OUTPUT ) )
                print( dim( f"  {_short( leaf.parent / R.LATEST, root )}/" ) )
                for name in written:
                    print( dim( f"    {name}" ) )
        elif status == "SKIP":
            print( f"{YELLOW}SKIP{RESET} {e.name} {dim( f'({site})' )} - {error}", flush = True )
            report.skipped.append( ( e, error, hint ) )
        else:
            print( f"{RED}FAIL{RESET} {e.name} {dim( f'({site})' )} - {error}", flush = True )
            report.failed.append( ( e, error ) )

        R.write_result(
            leaf, entry = e, root = root, env_name = env_name, where = where, tags = tags,
            status = status, error = error, duration_s = duration, ram = R.ram_mb(),
            params = resolved, results = dict( E.results ), output_text = buf.getvalue(),
            version = version,
        )
        R.refresh( entry_root )

    return report


# ── running, several at once ─────────────────────────────────────────────────
#
# One process per entry, because the isolation between entries IS the module
# reload, and a reload only isolates within one interpreter. Serial runs stay
# in this process: they are faster that way and their output arrives live.
#
# A child is told which entry by call site (`--at file:line`) and what its
# parameters are through the environment -- not as flags, because a resolved
# value is allowed to contain a comma and a comma on the command line means a
# matrix.

PARAMS = "ERRAND_PARAMS"


def job_count( asked ) -> int:
    if asked in ( None, "", "1" ):
        return 1
    if str( asked ) == "auto":
        return max( 1, os.cpu_count() or 1 )
    try:
        return max( 1, int( asked ) )
    except ValueError:
        raise ValueError( f"-j: expected a number or `auto`, got {asked!r}" )


def run_in_processes( entries, combos, *, root, out_root, env, tags, how_many, report,
                      out_prefix ):
    """Each entry, in its own process, up to `how_many` at a time.

    What came of it is read back from the result file rather than parsed out of
    the child's chatter: the path was worked out before the child started, and
    the file is the record either way.
    """
    import subprocess

    from . import yamlish

    pending = [ ( e, values ) for _, values in combos for e in entries ]
    running, done = [ ], 0
    total = len( pending )
    print( head( f"\n{'=' * 10} {total} entr{'y' if total == 1 else 'ies'}"
                 f"  {env.name}  {out_prefix}  -j {how_many} {'=' * 10}" ), flush = True )

    def start( e, values ):
        child = dict( os.environ )
        child[ PARAMS ] = yamlish.dump( { k: v for k, v in values.items() } ).strip()
        child[ "PYTHONUNBUFFERED" ] = "1"
        argv = [ sys.executable, "-m", "errand", "--at", f"{e.file}:{e.line}",
                 "--root", str( root ), "--out", str( out_root ), "--env", env.name ]
        return ( e, values,
                 subprocess.Popen( argv, cwd = root, env = child, text = True,
                                   stdout = subprocess.PIPE, stderr = subprocess.STDOUT ) )

    while pending or running:
        while pending and len( running ) < how_many:
            running.append( start( *pending.pop( 0 ) ) )

        e, values, child = running.pop( 0 )
        output = child.communicate()[ 0 ]
        done += 1
        # In completion order, as a block: interleaved lines from several
        # entries at once are unreadable, and worse, unattributable.
        sys.stdout.write( output )
        sys.stdout.flush()

        resolved = E.resolve_params( e.params, values )
        leaf, _ = R.dirs_for( out_root, e, resolved, R.place( env.name ) )
        got = yamlish.read( leaf / R.RESULT ) or { }
        status = got.get( "status" ) or ( "PASS" if child.returncode == 0 else "FAIL" )
        if status == "SKIP":
            report.skipped.append( ( e, got.get( "error" ), None ) )
        elif status != "PASS":
            report.failed.append( ( e, got.get( "error" ) or f"exit {child.returncode}" ) )
    return report


def run_one( at, *, root, out_root, env_name, tags, version, report, queued ):
    """The child side of the above: exactly the entry at FILE:LINE."""
    from . import yamlish

    path, _, line = at.rpartition( ":" )
    entries, modules = discovery.select_at( Path( path ), int( line ), root )
    if not entries:
        print( bad( f"no entry at {at}" ) )
        return 1

    values = yamlish.load( os.environ.get( PARAMS, "" ) ) if os.environ.get( PARAMS ) else { }
    run_entries( entries, modules, root = root, out_root = out_root, overrides = values,
                 env_name = env_name, tags = tags, version = version,
                 report = report, queued = queued, quiet = True )
    return 1 if report.failed else 0


# ── running, elsewhere ───────────────────────────────────────────────────────

def dispatch( env, tags, argv, *, root, out_root, entries, overrides_list ):
    """Re-run this very command through `env`'s layers.

    The child does the real work -- discovery, selection, the run -- inside the
    environment; this side only wraps. What crosses is the environment's name
    and its resolved tags, NOT `--env`: re-selecting over there would send an
    ssh environment straight back out to the machine it is already on.
    """
    ctx = L.Context( root = root, tags = tags, needs = aggregate_needs( entries ) )
    child_env = {
        IN_ENV: env.name,
        TAGS  : ",".join( f"{k}={v}" for k, v in sorted( tags.items() ) ),
        "PYTHONUNBUFFERED": "1",
    }
    cmd = L.Command( [ "python", "-m", "errand", *argv ], child_env )

    for message in L.warnings_for( env.stack, ssh_root( env, root ) ):
        print( warn( f"  warning: {message}" ), flush = True )

    ssh = env.ssh
    if ssh is None:
        wrapped = L.compose( env.stack, cmd, ctx )
        merged = { **os.environ, **wrapped.env }
        print( dim( f"  $ {' '.join( str( a ) for a in wrapped.argv )}" ), flush = True )
        import subprocess
        return subprocess.run( wrapped.argv, env = merged, cwd = root ).returncode

    pull = sorted( { str( R.dirs_for( out_root, e, o, "x" )[ 1 ].relative_to( root ) )
                     for e in entries for o in overrides_list } )
    return ssh.run( env.stack[ 1 : ], cmd, ctx, pull = pull,
                    echo = lambda s: print( dim( s ), flush = True ) )


# ── letting go, and looking back ─────────────────────────────────────────────

def plan_of( targets, entries, combos, *, root, out_root ):
    """Every run this command is about to produce, and where to look for it.

    One row per ( environment, parameter combination, entry ). The case's own
    directory is predictable -- it is its file and its name -- while the run
    directory under it may not be, since its name carries the PLACE: a remote
    run carries the other machine's name, and a batch job carries whichever
    compute node the scheduler picked. So a row names the place when it is
    knowable and says so when it is not, and whoever reads the tree searches
    beneath `under`.

    Worked out here, once, for everyone who needs it before the fact: the
    targeted rsync pull, the completion signal, and the screen that wants to
    show each case's output as it is written.
    """
    runs = [ ]
    for env, tags in targets:
        unknowable = env.ssh is not None or L.batch_of( env.stack ) is not None
        for _, values in combos:
            for e in entries:
                resolved = E.resolve_params( e.params, values )
                _, entry_root = R.dirs_for( out_root, e, resolved, "?" )
                runs.append( { "label": e.name, "file": e.file.name, "env": env.name,
                               "place": "?" if unknowable else R.place( env.name ),
                               "params": _plain_params( resolved ),
                               "under": str( entry_root.relative_to( root ) ),
                               "entry_root": str( entry_root.relative_to( root ) ) } )
    return runs


def submit( targets, entries, combos, argv, *, root, out_root ):
    """Launch each environment's share and come straight back."""
    ident = batch.new_id( root )
    stripped = [ a for a in argv if a not in ( "--batch", "--status", "--watch" ) ]

    runs = plan_of( targets, entries, combos, root = root, out_root = out_root )
    pull = { r[ "entry_root" ] for r in runs }
    places = [ ]
    for env, tags in targets:
        child_argv = _without_value( stripped, "--env" ) + [ "--env", env.name ]
        got = batch.detach( env, tags, child_argv, root = root,
                            log = batch.batch_dir( root ) / f"{ident}-{R.slug( env.name )}.log",
                            child_env = { IN_ENV: env.name,
                                          TAGS: ",".join( f"{k}={v}" for k, v in sorted( tags.items() ) ),
                                          "PYTHONUNBUFFERED": "1" } )
        got[ "env" ] = env.name
        places.append( got )

    record = { "id": ident, "when": batch.now(), "command": " ".join( stripped ),
               "runs": runs, "places": places, "pull": sorted( pull ) }
    batch.save( root, record )

    failed = [ p for p in places if p[ "kind" ] == "failed" ]
    shown = ", ".join( f"{len( runs ) // max( 1, len( places ) )} on {p.get( 'host' ) or 'this machine'}"
                       f" ({p[ 'kind' ]} {p[ 'handle' ]})" for p in places if p not in failed )
    print( f"  submitted {BOLD}{ident}{RESET} - {len( runs )} run(s)" + ( f" - {shown}" if shown else "" ) )
    for p in failed:
        print( bad( f"  {p[ 'env' ]}: could not start - {p.get( 'error', '' )}" ) )
    print( dim( f"  errand --status    errand --watch" ) )
    return 1 if failed else 0


def _without_value( argv, flag ):
    out, skip_next = [ ], False
    for a in argv:
        if skip_next:
            skip_next = False
            continue
        if a == flag:
            skip_next = True
            continue
        if a.startswith( flag + "=" ):
            continue
        out.append( a )
    return out


def _plain_params( resolved ):
    return { k: ( v if isinstance( v, ( int, float, bool, str ) ) else repr( v ) )
             for k, v in resolved.items() }


MARKS = { batch.DONE: "ok", batch.RUNNING: "..", batch.LOST: "??" }


def show_batches( root, live = False ):
    records = batch.load_all( root )
    if not records:
        print( dim( "  nothing launched from here" ) )
        return 0
    try:
        while True:
            for record in records:
                batch.collect( root, record )
            if live:
                print( "\033[2J\033[H", end = "" )
            everything = [ ]
            for record in records:
                rows = batch.states( root, record )
                everything += rows
                _show_one( record, rows )
            if not live or batch.finished( everything ):
                return 0
            time.sleep( 2.0 )
    except KeyboardInterrupt:
        return 0


def _show_one( record, rows ):
    done = sum( 1 for r in rows if r[ "state" ] == batch.DONE )
    bar = "#" * ( 8 * done // max( 1, len( rows ) ) )
    print( head( f"\n{record[ 'id' ]}  {record[ 'command' ] or '(everything)'}" )
           + dim( f"   {record[ 'when' ]}   {done}/{len( rows )} [{bar:<8}]" ) )
    for place in record.get( "places", [ ] ):
        state = batch.alive( place )
        how = "running" if state else ( "finished" if state is False else "unknown" )
        print( dim( f"    {place[ 'env' ]}: {place[ 'kind' ]} {place.get( 'handle' ) or '-'}"
                    f" on {place.get( 'host' ) or 'this machine'} - {how}" ) )

    # Parameters down, places across: that is the shape a matrix actually has,
    # and a flat list of eight lines hides the one axis that was varied.
    places = sorted( { r[ "place" ] for r in rows } )
    keys = sorted( { _key( r ) for r in rows } )
    width = max( [ len( k ) for k in keys ] + [ 8 ] )
    print( "      " + f"{'':<{width}}  " + "  ".join( f"{p[ :22 ]:<22}" for p in places ) )
    for key in keys:
        cells = [ ]
        for place in places:
            row = next( ( r for r in rows if _key( r ) == key and r[ "place" ] == place ), None )
            cells.append( f"{_cell( row ):<22}" )
        print( "      " + f"{key:<{width}}  " + "  ".join( cells ) )


def _key( row ):
    params = ", ".join( f"{k}={v}" for k, v in ( row.get( "params" ) or { } ).items() )
    return f"{row[ 'label' ]}" + ( f"  {params}" if params else "" )


def _cell( row ):
    if row is None:
        return "-"
    if row[ "state" ] != batch.DONE:
        return "..." if row[ "state" ] == batch.RUNNING else "lost"
    mark = good( "ok" ) if row.get( "status" ) == "PASS" else (
        warn( "skip" ) if row.get( "status" ) == "SKIP" else bad( "FAIL" ) )
    numbers = [ f"{k}={v:g}" for k, v in ( row.get( "results" ) or { } ).items()
                if isinstance( v, ( int, float ) ) and not isinstance( v, bool ) ]
    seconds = row.get( "seconds" )
    detail = numbers[ 0 ] if numbers else ( f"{seconds:g}s" if seconds else "" )
    return f"{mark} {detail}".strip()


# ── listing ──────────────────────────────────────────────────────────────────

def print_envs( root ):
    print( head( "\nEnvironments" ) )
    if not config.envs:
        print( dim( "  none declared -- work runs in this interpreter" ) )
        print( dim( f"  declare some in {config.CONFIG_FILE} at the project root" ) )
        return 0
    default = config.default_env()
    width = max( len( n ) for n in config.envs )
    for name, e in config.envs.items():
        ctx = L.Context( root = root, tags = e.tags )
        state = setup.status( root, e, ctx )
        tags = "  ".join( k if v is True else f"{k}={v}" for k, v in sorted( e.tags.items() ) )
        mark = "  <- default" if e is default else ""
        note = "" if state == setup.OK else f"  {warn( state )}"
        print( f"  {name:{width}}  {tags:28}  {dim( e.describe() )}{note}{mark}" )
    print( dim( f"\n  choose one with --env <name>, or by tag: "
                f"{ ' '.join( '--' + n for n in config.tag_names() ) or '(no tags declared)' }" ) )
    return 0


def _put_src_on_path( root ):
    sys.path.insert( 0, str( root ) )
    for extra in ( config.settings.src or [ "src" ] ):
        if ( root / extra ).is_dir():
            sys.path.insert( 0, str( root / extra ) )


def ssh_root( env, root ):
    return env.ssh.remote_root( L.Context( root = root ) ) if env.ssh else root


def prepare_providers( entries, *, root, out_root, tags ):
    """Give each provider its one chance to get ready. -> [ ( who, why ) ] on trouble."""
    out = [ ]
    seen = [ ]
    for e in entries:
        if e.provider is not None and not any( e.provider is p for p in seen ):
            seen.append( e.provider )
    for p in seen:
        mine = [ e for e in entries if e.provider is p ]
        ctx = P.RunContext( root = root, out_dir = out_root, env = { } )
        why = p.prepare( mine, ctx )
        if why:
            out.append( ( p.name, why ) )
    return out


def print_queue( ):
    scheduler = queue.someone_else_is_scheduling()
    print( head( f"\nThe machine ({queue.host()})" ) )
    have = queue.capacity()
    print( dim( f"  has  cpus={have[ 'cpus' ]:g}  ram={have[ 'ram' ]:.0f}M  gpus={have[ 'gpus' ]:g}" ) )
    if scheduler:
        print( dim( f"  {scheduler} already decides what runs here; errand does not queue" ) )
        return 0
    lines = queue.describe()
    if not lines:
        print( dim( "  nothing held" ) )
    for line in lines:
        print( f"  {line}" )
    print( dim( f"  {queue.queue_dir()}" ) )
    return 0


def say_broken( ):
    """What declares work and would not import. Said wherever entries are
    listed, because a list that is short for a reason must give the reason."""
    if not discovery.broken:
        return
    print( bad( f"\n  {len( discovery.broken )} file(s) could not be read:" ) )
    for path, why, _ in discovery.broken:
        print( f"    {path}  {dim( why )}" )


def print_entries( entries ):
    if not entries:
        print( dim( "  nothing matched" ) )
        return
    for e in entries:
        print( head( f"\n{e.name}" ) + dim( f"  ({e.file}:{e.line})  [{e.kind}]" ) )
        if e.tags:
            print( dim( f"  tags: {', '.join( e.tags )}" ) )
        traits = [ k if v else f"!{k}" for k, v in e.traits.items() if v != E.TRAITS[ k ] ]
        if traits:
            print( dim( f"  traits: {' '.join( traits )}" ) )
        if e.resources:
            print( dim( f"  needs: {', '.join( f'{k}={v}' for k, v in e.resources.items() )}" ) )
        for name, p in e.params.items():
            flag = f"--{name.replace( '_', '-' )}"
            extra = f"  choices: {p.choices}" if p.choices else ""
            print( f"  {flag:22s} default={p.default!r}  {p.help}{extra}" )


# ── entry point ──────────────────────────────────────────────────────────────

def build_parser( tag_names = ( ) ):
    # No abbreviations. Parameter flags are named by whoever wrote the entry,
    # so any of them may one day be a prefix of a built-in one -- `--n=2,3` was
    # read as `--no-setup=2,3`, which is not a mistake anybody would have
    # thought to look for. An exact match, or nothing.
    p = argparse.ArgumentParser( prog = "errand", add_help = False, allow_abbrev = False,
        description =
        "Run work here, in a container or on another machine, and bring back what it produced." )
    p.add_argument( "pattern", nargs = "?", help = "file[::name] spec(s), comma-separated, globbable" )
    p.add_argument( "-k", "--kind", action = "append", default = [ ],
                    help = "test, bench, experiment (repeatable)" )
    p.add_argument( "-e", "--entry-tags", default = None, help = "filter entries by tag expression" )
    p.add_argument( "-t", "--env-tags", default = None, help = "choose environments by tag expression" )
    p.add_argument( "--env", default = None, help = "environment(s) by name, comma-separated" )
    p.add_argument( "--envs", action = "store_true", help = "list environments and stop" )
    p.add_argument( "--setup", nargs = "?", const = "yes", default = None,
                    help = "build/update environments now ('force' to start over)" )
    p.add_argument( "--no-setup", action = "store_true", help = "skip the freshness check" )
    p.add_argument( "--dry-run", action = "store_true", help = "say what setup would do" )
    p.add_argument( "--out", default = None, help = "output tree (default: runs)" )
    p.add_argument( "--root", default = None, help = "project root (default: found from the cwd)" )
    p.add_argument( "-j", "--jobs", default = "1",
                    help = "how many entries at once: a number, or `auto`" )
    p.add_argument( "--at", default = None,
                    help = argparse.SUPPRESS )   # internal: run exactly the entry at FILE:LINE
    p.add_argument( "--no-queue", action = "store_true",
                    help = "do not wait for the machine to be free" )
    p.add_argument( "--queue", action = "store_true", help = "what the host is busy with, and stop" )
    p.add_argument( "--batch", action = "store_true",
                    help = "launch it and give the shell back" )
    p.add_argument( "--tui", action = "store_true",
                    help = "the screen: tick what to run, watch each case as it talks" )
    p.add_argument( "--status", action = "store_true", help = "how the launched work is going" )
    p.add_argument( "--watch", action = "store_true", help = "the same, live" )
    p.add_argument( "--forget", default = None, help = "drop a submission from the list" )
    p.add_argument( "-h", "--help", action = "store_true", help = "show what matched, and its parameters" )
    p.add_argument( "-V", "--version", action = "store_true", help = "which errand this is" )
    for name in tag_names:
        p.add_argument( f"--{name.replace( '_', '-' )}", dest = f"tag_{name}", default = None,
                        help = f"environments whose {name} tag matches (comma = matrix)" )
    return p


def positional_of( parser, argv ):
    """The pattern, read out of argv before the parameter flags are known.

    Parameters cannot be declared until the entries are known, and the entries
    cannot be found without the pattern -- so the first pass meets flags it has
    never heard of. `parse_known_args` hands their VALUES back as leftovers,
    and argparse then happily takes the first of them as the positional: with
    `--n 3,4` it would look for a file called `3,4`. (`--n=3,4` survives, which
    is what kept this hidden.)

    So the pattern is read here instead: anything after an option it does not
    recognize belongs to that option.
    """
    takes_value = { }
    for action in parser._actions:
        for option in action.option_strings:
            takes_value[ option ] = action.nargs != 0

    i = 0
    while i < len( argv ):
        token = argv[ i ]
        if token == "--":
            return argv[ i + 1 ] if i + 1 < len( argv ) else None
        if token.startswith( "-" ) and token != "-":
            name = token.split( "=", 1 )[ 0 ]
            if "=" not in token and takes_value.get( name, True ):
                i += 1                       # unknown flags are assumed to take a value
            i += 1
            continue
        return token
    return None


def main( argv = None ):
    from . import __version__

    argv = list( sys.argv[ 1 : ] if argv is None else argv )

    pre, _ = build_parser().parse_known_args( argv )
    root = Path( pre.root ).resolve() if pre.root else find_root()

    config.load( root, warn = lambda m: print( warn( f"  warning: {m}" ), file = sys.stderr ) )
    local.load( root )

    out_root = Path( pre.out or config.settings.out )
    if not out_root.is_absolute():
        out_root = root / out_root

    parser = build_parser( config.tag_names() )
    known, _ = parser.parse_known_args( argv )
    known.pattern = positional_of( parser, argv )

    if known.version:
        # The version of the PACKAGE and the file it came out of: an editable
        # install and a copy on PYTHONPATH answer the same otherwise, and which
        # one is answering is exactly what is being asked.
        print( f"errand {__version__}  ({Path( __file__ ).resolve().parent})" )
        return 0

    if known.tui:
        # Imported here and nowhere else: it needs `curses`, which not every
        # interpreter carries, and a missing screen must not cost the command
        # line.
        from . import tui
        return tui.main( root = root, out_root = out_root )

    if known.envs:
        return print_envs( root )

    if known.forget:
        batch.forget( root, known.forget )
        return 0

    if known.status or known.watch:
        return show_batches( root, live = known.watch )

    if known.queue:
        return print_queue()

    if known.at:
        # A child running exactly one entry: no discovery over the tree, no
        # environment selection ( it is already inside one ), no epilogue.
        # `--env` names it when the parent dispatched to one of several; being
        # INSIDE one ( a container, another machine ) names it instead, and
        # wins, because that is where this process actually is.
        inside = os.environ.get( IN_ENV )
        env_obj = ( config.envs.get( inside ) if inside
                    else config.envs.get( known.env ) if known.env
                    else config.default_env() )
        _put_src_on_path( root )
        return run_one( known.at, root = root, out_root = out_root,
                        env_name = ( env_obj.name if env_obj else known.env or "default" ),
                        tags = _tags_from_env() or ( env_obj.tags if env_obj else { } ),
                        version = __version__, report = Report(),
                        queued = not known.no_queue )

    kinds = set()
    for k in known.kind:
        if k not in KINDS:
            print( bad( f"unknown kind {k!r}; expected one of {', '.join( sorted( KINDS ) )}" ) )
            return 2
        kinds.add( KINDS[ k ] )

    _put_src_on_path( root )

    try:
        selected, modules, selectors = discovery.select(
            known.pattern, root, kinds = kinds, entry_tags = known.entry_tags,
            bulk_only = not known.pattern and not kinds, exclude = config.settings.exclude,
            providers = config.providers,
        )
    except ValueError as err:
        print( bad( str( err ) ) )
        return 1

    # The parameters only exist once we know which entries matched.
    declared = { }
    for e in selected:
        declared.update( e.params )
    for name, p in declared.items():
        # type=str, not p.ptype: argparse would coerce too early for a matrix
        # like `--n=1000,5000` to still be visible as one string.
        parser.add_argument( f"--{name.replace( '_', '-' )}", dest = name, type = str,
                             default = None, help = p.help )
    args = parser.parse_args( argv )
    args.pattern = known.pattern

    if args.help:
        print_entries( selected )
        say_broken()
        return 0

    try:
        combos = expand( { n: getattr( args, n, None ) for n in declared }, declared )
        how_many = job_count( args.jobs )
    except ValueError as err:
        print( bad( str( err ) ) )
        return 1

    # Which environments, and with which tags. On the child side of a dispatch
    # there is exactly one, already entered.
    inside = os.environ.get( IN_ENV )
    if inside is not None:
        targets = [ ( config.envs.get( inside ) or config.Env( inside, [ ], { } ),
                      _tags_from_env() ) ]
    else:
        try:
            targets = _targets( args, config.tag_names() )
        except ValueError as err:
            print( bad( str( err ) ) )
            return 1

    if args.setup:
        rc = 0
        for env, tags in targets:
            rc |= setup.ensure( root, env, L.Context( root = root, tags = tags ),
                                force = args.setup == "force", echo = lambda s: print( dim( s ) ),
                                dry_run = args.dry_run )
        return rc

    if not selected:
        print( bad( f"nothing matched {args.pattern!r}" if args.pattern else "nothing to run" ) )
        if discovery.broken:
            # "nothing to run" when in fact nothing could be READ is the kind of
            # answer that sends somebody looking in the wrong place.
            say_broken()
            return 1
        _suggest( root )
        return 1

    # Recorded as the command it was, so it can be run again -- from the shell
    # or from the screen. Only on the side that was ASKED: the child of a
    # dispatch runs a command nobody typed, over there.
    if inside is None:
        history.push( root, argv )

    if args.batch:
        return submit( targets, selected, combos, argv, root = root, out_root = out_root )

    report = Report()
    report.broken = list( discovery.broken )
    rc = 0
    for env, tags in targets:
        if inside is None and env.wraps_anything():
            if not args.no_setup:
                if setup.ensure( root, env, L.Context( root = root, tags = tags ),
                                 echo = lambda s: print( dim( s ), flush = True ) ):
                    print( bad( f"  could not prepare {env.name}" ) )
                    rc = 1
                    continue
            print( dim( f"\n  -> {env.name}  {env.describe()}" ), flush = True )
            rc |= dispatch( env, tags, argv, root = root, out_root = out_root,
                            entries = selected, overrides_list = [ v for _, v in combos ] )
            continue

        # Running here rather than in a child, either because nothing needed
        # wrapping or because the wrapping already happened and this IS the
        # child. Either way no command is about to be rewritten, so what the
        # layers meant to put in the environment has to be put there directly --
        # and `Vars` is the only kind that can act without a new process at all.
        # (Composing the whole stack instead would reach the Ssh layer, whose
        # answer to being folded is to refuse.)
        os.environ.update( L.compose( [ l for l in env.stack if isinstance( l, L.Vars ) ],
                                      L.Command( [ "python" ] ),
                                      L.Context( root = root, tags = tags ) ).env )

        # Build once, here, before anything runs: a suite is built once and not
        # once per file, and under `-j` several children would otherwise write
        # the same binary at the same time.
        trouble = prepare_providers( selected, root = root, out_root = out_root, tags = tags )
        if trouble:
            for who, why in trouble:
                print( bad( f"  {who}: {why}" ) )
            rc = 1
            continue

        if how_many > 1:
            run_in_processes( selected, combos, root = root, out_root = out_root, env = env,
                              tags = tags, how_many = how_many, report = report,
                              out_prefix = R.place( env.name ) )
            continue

        for i, ( varied, values ) in enumerate( combos ):
            if varied:
                shown = ", ".join( f"{k.replace( '_', '-' )}={v}" for k, v in varied.items() )
                print( head( f"\n--- {i + 1}/{len( combos )}  {shown} ---" ), flush = True )
            run_entries( selected, modules, root = root, out_root = out_root,
                         overrides = values, env_name = env.name, tags = tags,
                         version = __version__, report = report,
                         queued = not args.no_queue, selectors = selectors )

    return _epilogue( report, rc )


def _tags_from_env( ) -> dict:
    out = { }
    for item in filter( None, os.environ.get( TAGS, "" ).split( "," ) ):
        k, _, v = item.partition( "=" )
        out[ k ] = v if v else True
    return out


def _targets( args, tag_names ):
    """The environments to run in, one entry per combination of tag values."""
    names = [ n.strip() for n in args.env.split( "," ) ] if args.env else None

    axes = { }
    for name in tag_names:
        values = split_values( getattr( args, f"tag_{name}", None ) )
        if values != [ None ]:
            axes[ name ] = values

    if not axes:
        return config.select( names = names, expression = args.env_tags )

    out = [ ]
    keys = list( axes )
    for combo in itertools.product( *( axes[ k ] for k in keys ) ):
        wanted = dict( zip( keys, combo ) )
        out += config.select( names = names, expression = args.env_tags, wanted_tags = wanted )
    return out


def _epilogue( report, rc ):
    print( "\n" + "=" * 46 )
    if report.broken:
        # Everything else still ran -- that is the point of being tolerant --
        # but a file that declares work and cannot be read is a failure, not a
        # detail, and it takes the return code with it.
        print( bad( f"  {len( report.broken )} file(s) could not be read:" ) )
        for path, why, _ in report.broken:
            print( f"    {path}  {dim( why )}" )
    if report.skipped:
        # A skip is not a pass. It gets its own block, with what was missing and
        # what to write where -- a suite that tested nothing must not look like
        # a suite that passed.
        print( warn( f"  {len( report.skipped )} skipped:" ) )
        for e, reason, hint in report.skipped:
            print( f"    {e.name}  {dim( f'({e.file.name}:{e.line})' )}  {reason}" )
            if hint:
                for line in hint.splitlines():
                    print( dim( f"      {line}" ) )
    if report.failed:
        for e, why in report.failed:
            print( f"  {bad( 'FAILED' )} {e.name}  ({e.file}:{e.line})  {why}" )
        return 1
    if report.broken:
        return 1
    if rc:
        return rc
    print( good( "  all good" ) + ( warn( f"  ({len( report.skipped )} skipped)" )
                                    if report.skipped else "" ) )
    return 0


def _short( path: Path, root: Path ):
    try:
        return path.relative_to( root )
    except ValueError:
        return path


def _suggest( root ):
    files = discovery.candidates( root )
    if files:
        print( dim( "\n  files that declare work:" ) )
        for p in files:
            print( dim( f"    {p.stem}  ({p.relative_to( root )})" ) )


if __name__ == "__main__":
    sys.exit( main() )
