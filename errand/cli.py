"""The command line."""
from __future__ import annotations

import argparse
import contextlib
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

from . import batch, config, discovery, entries as E, history, layers as L, local, queue, runner as P, results as R, setup

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
    """The project root: the nearest ancestor holding an errand-*.py, else here.

    Deliberately not the git root. Walking up to one means that running from a
    subdirectory of a large repository silently widens the search to the whole
    of it -- and with no errand-*.py there is nothing that says where the project
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

def alternatives( text: str ) -> list[ str ]:
    """A comma makes a grid, wherever it is: `a,b` is two values, `a,,b` three
    -- the middle one empty -- and `a\\,b` is one, with a comma in it. No other
    backslash means anything."""
    out, cur, i = [ ], [ ], 0
    while i < len( text ):
        if text.startswith( "\\,", i ):
            cur.append( "," )
            i += 2
            continue
        if text[ i ] == ",":
            out.append( "".join( cur ) )
            cur = [ ]
        else:
            cur.append( text[ i ] )
        i += 1
    return out + [ "".join( cur ) ]


def expand( raw_values: dict, params: dict, raw = ( ) ):
    """`--n=1000,5000` is an axis, and so is any argument of the target's own
    with a comma in it. -> [ ( varied, { name: value, ARGS: [ ... ] } ), ... ].

    Values arrive as strings precisely so a comma can be seen before the type
    is applied; `varied` holds only what actually had several values, so the
    non-matrix case stays silent.
    """
    axes = { }
    for name, given in raw_values.items():
        if given is None:
            continue
        p = params[ name ]
        parts = alternatives( given ) if isinstance( given, str ) else [ given ]
        try:
            values = [ p.ptype( x ) for x in parts ]
        except ( TypeError, ValueError ):
            raise ValueError( f"--{name.replace( '_', '-' )}: cannot read {given!r} "
                              f"as {p.ptype.__name__}" )
        if p.choices:
            wrong = [ v for v in values if v not in p.choices ]
            if wrong:
                raise ValueError( f"--{name.replace( '_', '-' )}: {wrong} not in {p.choices}" )
        axes[ name ] = values

    # The target's own arguments: each one with a comma is an axis of its own --
    # on the value of an `--option=value`, as on a declared parameter.
    def axis( token ):
        name, eq, value = token.partition( "=" )
        if token.startswith( "-" ) and eq:
            return [ name + eq + v for v in alternatives( value ) ]
        return alternatives( token )
    tokens = [ axis( t ) for t in raw ]
    args_vary = any( len( t ) > 1 for t in tokens )

    names = list( axes )
    out = [ ]
    for combo in itertools.product( *( axes[ n ] for n in names ) ):
        for args in itertools.product( *tokens ):
            chosen = dict( zip( names, combo ) )
            varied = { n: v for n, v in chosen.items() if len( axes[ n ] ) > 1 }
            if args_vary:
                varied[ ARGS ] = " ".join( args )
            chosen[ ARGS ] = list( args )
            out.append( ( varied, chosen ) )
    return out


def describe_grid( combos ) -> str:
    """`4 runs: n = 2 | 3, args = --size 1 | --size 2` -- said once, before
    anything starts, so a comma that was not meant as a grid is seen in time."""
    axes = { }
    for varied, _ in combos:
        for k, v in varied.items():
            seen = axes.setdefault( k, [ ] )
            if v not in seen:
                seen.append( v )
    shown = ", ".join( f"{k.replace( '_', '-' )} = {' | '.join( str( v ) for v in vs )}"
                       for k, vs in axes.items() )
    return f"{len( combos )} runs: {shown}"


def split_values( raw ):
    """A comma means a matrix, on a tag exactly as on a parameter."""
    if raw is None:
        return [ None ]
    return [ v.strip() for v in alternatives( str( raw ) ) if v.strip() ]


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

        shown = shown_params( resolved, overrides )
        leaf, entry_root = R.dirs_for( out_root, e, shown, where, root )
        R.clear( leaf )
        R.point_latest_at( leaf )

        site = f"{e.file.name}:{e.line}" if e.line else e.file.name
        if shown:
            told = ", ".join( f"{k}={v!r}" for k, v in shown.items() )
            print( dim( f"  {e.name} ({site}) -- {told}" ), flush = True )

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
                        if e.runner is None:
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
                            # The target's arguments are its `sys.argv`, as
                            # they would be for `python file.py args…`.
                            kept_argv = sys.argv
                            sys.argv = [ str( e.file ), *target_argv( e, resolved, overrides ) ]
                            try:
                                discovery.import_file( modules[ e.module ], root )
                            finally:
                                sys.argv = kept_argv
                        else:
                            # Somebody else's suite: it runs itself, and only
                            # says what came of it. Everything around the run
                            # is the same as for anything here.
                            got = e.runner.run( e, P.RunContext(
                                root = root, out_dir = leaf, params = resolved,
                                env = dict( handed ), selector = selectors.get( e.name ),
                                build_dir = build_dir_for( root, env_name ),
                                args = target_argv( e, resolved, overrides ) ) )
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
            params = shown, results = dict( E.results ), output_text = buf.getvalue(),
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
    from . import yamlish

    pending = [ ( e, values ) for _, values in combos for e in entries ]
    running, done = [ ], 0
    total = len( pending )
    print( head( f"\n{'=' * 10} {total} entr{'y' if total == 1 else 'ies'}"
                 f"  {env.name}  {out_prefix}  -j {how_many} {'=' * 10}" ), flush = True )

    def start( e, values ):
        child = dict( os.environ )
        child[ PARAMS ] = json.dumps( values )
        child[ "PYTHONUNBUFFERED" ] = "1"
        argv = [ sys.executable, "-m", "errand", "run", "--at", f"{e.file}:{e.line}",
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
        leaf, _ = R.dirs_for( out_root, e, shown_params( resolved, values ), R.place( env.name ), root )
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

    values = json.loads( os.environ[ PARAMS ] ) if os.environ.get( PARAMS ) else { }
    run_entries( entries, modules, root = root, out_root = out_root, overrides = values,
                 env_name = env_name, tags = tags, version = version,
                 report = report, queued = queued, quiet = True )
    return 1 if report.failed else 0


# ── running, elsewhere ───────────────────────────────────────────────────────

def run_here( known, command ):
    """`errand shell [-x] -- <command>`: that command on this machine, once the queue
    lets it, under a memory ceiling, and at low priority unless it is exclusive.
    What `job` used to be: the machine is shared by every session and project."""
    needs = { k: v for k, v in ( ( "cpus", known.cpus ), ( "ram", known.ram ) ) if v }
    mem = known.mem or ( "24G" if known.exclusive else "8G" )
    wrap = [ ]
    scope = [ "systemd-run", "--user", "--scope", "-q", "-p", f"MemoryMax={mem}" ]
    # Without a user bus ( ssh, cron, a changed XDG_RUNTIME_DIR ) the scope cannot
    # be made; the command still runs, only without its ceiling.
    if shutil.which( "systemd-run" ) and subprocess.run( scope + [ "true" ], capture_output = True ).returncode == 0:
        wrap += scope
    if not known.exclusive:
        wrap += [ "nice", "-n", "5" ]
    label = known.label or " ".join( command )
    say = lambda m: None if known.quiet else print( m, file = sys.stderr, flush = True )
    with queue.claim( needs, exclusive = known.exclusive, label = label,
                      enabled = not known.no_queue, echo = say ) as granted:
        env = { **os.environ, **( granted.env() if granted else { } ),
                **( granted.handed_down() if granted else { } ),
                "JOB_CLASS": "bench" if known.exclusive else "generic" }
        say( f"[errand {os.getpid()} {'exclusive' if known.exclusive else 'shared'}] {label}" )
        try:
            if known.log:
                with open( known.log, "w" ) as out:
                    rc = subprocess.run( wrap + list( command ), env = env,
                                         stdout = out, stderr = subprocess.STDOUT ).returncode
            else:
                rc = subprocess.run( wrap + list( command ), env = env ).returncode
        except FileNotFoundError as err:
            say( f"errand: {err}" )
            rc = 127
        say( f"[errand {os.getpid()}] done, code {rc}" )
    return rc


def run_there( known, command, *, root, interactive = False ):
    """`errand shell --env X [-- <command>]`: that command, or a shell, in that environment.

    Not a feature of the runner so much as of the environments. They are
    already declared here, once, with the layers that lead to them -- a venv, a
    container, another machine -- so being let into one, to look at a toolchain
    or to ask a card what it is, is a smaller thing than a second tool that
    would have to describe them all over again.

    The first word is replaced by the interpreter of the place when it names an
    interpreter, and kept when it does not ( see `layers.under` ).
    """
    try:
        targets = _targets( known, config.tag_names() )
    except ValueError as err:
        print( bad( str( err ) ) )
        return 1

    rc = 0
    for env, tags in targets:
        ctx = L.Context( root = root, tags = tags, interactive = interactive )
        # The same question as before any work: is the place ready? Being let
        # into an environment that has not been built yet is the one moment
        # where you MOST want it built -- there is nothing else about to do it.
        if not known.no_setup:
            if setup.ensure( root, env, ctx,
                             echo = lambda s: print( dim( s ), flush = True ) ):
                print( bad( f"  could not prepare {env.name}" ) )
                rc = 1
                continue
        # The same sources the work itself would see. Being let into the
        # environment to look at something is pointless if what you look at is
        # somebody else's checkout of the same package.
        path = os.pathsep.join( _src_paths( root ) + [ os.environ.get( "PYTHONPATH", "" ) ] )
        cmd = L.Command( list( command ),
                         { TAGS: ",".join( f"{k}={v}" for k, v in sorted( tags.items() ) ),
                           "PYTHONPATH": path.rstrip( os.pathsep ) } )
        print( dim( f"\n  -> {env.name}  {env.describe()}" ), flush = True )
        # The first layer leads somewhere -- another machine, a machine to
        # boot -- and takes over; it hands whatever follows it on itself.
        lead = env.stack[ 0 ] if env.stack and hasattr( env.stack[ 0 ], "run" ) else None
        if lead is not None:
            rc |= lead.run( env.stack[ 1 : ], cmd, ctx, pull = known.pull or None,
                            echo = lambda s: print( dim( s ), flush = True ) )
        else:
            wrapped = L.compose( env.stack, cmd, ctx )
            print( dim( f"  $ {' '.join( str( a ) for a in wrapped.argv )}" ), flush = True )
            rc |= subprocess.run( wrapped.argv, env = { **os.environ, **wrapped.env },
                                  cwd = root ).returncode
    return rc


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
                resolved = shown_params( E.resolve_params( e.params, values ), values )
                _, entry_root = R.dirs_for( out_root, e, resolved, "?", root )
                runs.append( { "label": e.name, "file": e.file.name, "env": env.name,
                               "place": "?" if unknowable else R.place( env.name ),
                               "params": _plain_params( resolved ),
                               "under": str( entry_root.relative_to( root ) ),
                               "entry_root": str( entry_root.relative_to( root ) ) } )
    return runs


def submit( targets, rest, argv, *, root, out_root ):
    """Launch each environment's share and come straight back.

    Where a run has to be sized from what preparing finds, the preparation is
    what is launched, and it submits the run itself once it knows."""
    ident = batch.new_id( root )
    stripped = [ a for a in argv if a != "--batch" ]
    forward = list( rest )

    places = [ ]
    for env, tags in targets:
        log = batch.batch_dir( root ) / f"{ident}-{R.slug( env.name )}.log"
        two = env.wraps_anything( tags ) and not env.single_pass( tags )
        got = batch.detach( env, tags,
                            [ "run", "--phase", "prepare", *forward ] if two else [ "run", *forward ],
                            root = root, log = log, child_env = child_env_for( env, tags ),
                            phase = "prepare" if two else "run",
                            then = [ "run", "--submit-run", *forward ] if two else None )
        got[ "env" ] = env.name
        got[ "plan" ] = str( plan_path( root, env.name ).relative_to( root ) )
        places.append( got )

    record = { "id": ident, "when": batch.now(), "command": " ".join( stripped ),
               "stamp": R.stamp(), "places": places }
    batch.save( root, record )

    failed = [ p for p in places if p[ "kind" ] == "failed" ]
    shown = ", ".join( f"{p[ 'env' ]} on {p.get( 'host' ) or 'this machine'} ({p[ 'kind' ]} {p[ 'handle' ]})"
                       for p in places if p not in failed )
    print( f"  submitted {BOLD}{ident}{RESET}" + ( f" - {shown}" if shown else "" ) )
    for p in failed:
        print( bad( f"  {p[ 'env' ]}: could not start - {p.get( 'error', '' )}" ) )
    print( dim( f"  errand status    errand watch" ) )
    return 1 if failed else 0


def submit_run( env, tags, rest, *, root ):
    """The end of a preparation launched by `--batch`: submit the run it has
    just prepared, sized from its plan, and say which job that is.

    This process is on the machine the scheduler is, inside the preparation's
    allocation but outside the layers after its scheduler -- so the run goes
    through the run phase's layers from here on, the leading `Ssh` aside."""
    import json
    plan = read_plan( root, env.name )
    if plan is None:
        print( bad( f"  {env.name}: no plan to submit a run from" ) )
        return 1
    stack = env.stack_for( "run", tags )
    if L.ssh_of( stack ) is not None:
        stack = stack[ 1 : ]
    ctx = L.Context( root = root, tags = tags, batch = True, phase = "run", needs = plan[ "needs" ] )
    cmd = L.Command( [ sys.executable, "-m", "errand", "run", "--from-plan", *rest ],
                     child_env_for( env, tags ) )
    if L.batch_of( stack ) is None:
        # Nothing to submit to: the session this runs in is the detachment,
        # and the run simply follows the preparation in it.
        ctx.batch = False
        wrapped = L.compose( stack, cmd, ctx )
        return subprocess.run( wrapped.argv, cwd = root, env = { **os.environ, **wrapped.env } ).returncode
    wrapped = L.compose( stack, cmd, ctx )
    got = subprocess.run( wrapped.argv, cwd = root, capture_output = True, text = True,
                          env = { **os.environ, **wrapped.env } )
    record = batch._from_submission( got, kind = "batch" )
    batch.submitted_path( plan_path( root, env.name ) ).write_text( json.dumps( record ) )
    if record[ "kind" ] == "failed":
        print( bad( f"  {env.name}: could not submit the run - {record.get( 'error', '' )}" ) )
        return 1
    print( dim( f"  submitted the run of {env.name}: job {record[ 'handle' ]}" ) )
    return 0


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
                _show_one( root, record, rows )
            if not live or batch.finished( everything ):
                return 0
            time.sleep( 2.0 )
    except KeyboardInterrupt:
        return 0


def _show_one( root, record, rows ):
    done = sum( 1 for r in rows if r[ "state" ] == batch.DONE )
    bar = "#" * ( 8 * done // max( 1, len( rows ) ) )
    print( head( f"\n{record[ 'id' ]}  {record[ 'command' ] or '(everything)'}" )
           + dim( f"   {record[ 'when' ]}   {done}/{len( rows )} [{bar:<8}]" ) )
    for place in record.get( "places", [ ] ):
        then = batch.run_job( root, place )
        state = batch.alive( then if then is not None else place )
        how = "running" if state else ( "finished" if state is False else "unknown" )
        job = f"{place[ 'kind' ]} {place.get( 'handle' ) or '-'}" + (
            f", then {then[ 'kind' ]} {then.get( 'handle' ) or '-'}" if then is not None else "" )
        print( dim( f"    {place[ 'env' ]}: {job} on {place.get( 'host' ) or 'this machine'} - {how}" ) )

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
        return { batch.RUNNING: "...", batch.PREPARING: "preparing" }.get( row[ "state" ], "lost" )
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
        print( dim( f"  declare some in {config.ENVS_FILE} at the project root" ) )
        return 0
    default = config.default()
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


def _src_paths( root ):
    """Where this project's own code lives, nearest first."""
    return [ str( root / extra ) for extra in ( config.settings.src or [ "src" ] )
             if ( root / extra ).is_dir() ] + [ str( root ) ]


def _put_src_on_path( root ):
    for path in reversed( _src_paths( root ) ):
        sys.path.insert( 0, path )


def ssh_root( env, root ):
    return env.ssh.remote_root( L.Context( root = root ) ) if env.ssh else root


def build_dir_for( root, env_name ) -> Path:
    """`build/<env>/`: where the runners' builds go for that environment."""
    return Path( root ) / config.settings.build / R.slug( env_name or "default" )


def prepare_runners( entries, *, root, out_root, tags, env_name = None ):
    """Give each runner its one chance to get ready. -> [ ( who, why ) ] on trouble."""
    out = [ ]
    seen = [ ]
    for e in entries:
        if e.runner is not None and not any( e.runner is p for p in seen + discovery.built ):
            seen.append( e.runner )
    for p in seen:
        mine = [ e for e in entries if e.runner is p ]
        ctx = P.RunContext( root = root, out_dir = out_root, env = { },
                            build_dir = build_dir_for( root, env_name ) )
        ctx.build_dir.mkdir( parents = True, exist_ok = True )
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
        site = f"{os.path.relpath( e.file )}:{e.line}" if e.line else os.path.relpath( e.file )
        runner = f"  {e.runner.name}" if e.runner is not None else ""
        print( head( f"\n{e.name}" ) + dim( f"  ({site})  [{e.kind}]{runner}" ) )
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

# What each verb does, in the order the help lists them, and which of the
# options are its own. The rest of the options -- choosing environments, where
# the project and its output are -- are everybody's, and may stand before the
# verb or after it.
VERBS = {
    "run"   : ( "run entries, and record what came of them",
                [ "kind", "entry_tags", "jobs", "no_queue", "no_setup", "batch", "at", "phase",
                  "from_plan", "submit_run" ] ),
    "list"  : ( "what a pattern matches, with its parameters", [ "kind", "entry_tags", "no_setup" ] ),
    "shell" : ( "a shell in an environment, or `-- cmd` run in it; nothing is recorded",
                [ "pull", "no_queue", "no_setup", "exclusive", "cpus", "ram", "mem", "label",
                  "quiet", "log" ] ),
    "envs"  : ( "the declared environments, and the state they are in", [ ] ),
    "setup" : ( "build or update environments now, and nothing else", [ "force", "dry_run" ] ),
    "init"  : ( "write an errand-project.py from what this directory holds", [ "force" ] ),
    "tui"   : ( "the screen: tick what to run, watch each case as it talks", [ ] ),
    "queue" : ( "what this machine has, and what is holding it", [ ] ),
    "wait"  : ( "wait until nothing holds the machine", [ ] ),
    "status": ( "how the launched ( --batch ) work is going", [ ] ),
    "watch" : ( "the same, live", [ ] ),
    "forget": ( "drop a submission from the list: errand forget ID", [ ] ),
    "vm"    : ( "the virtual machines kept warm between commands: errand vm stop", [ ] ),
}
COMMON = [ "env", "env_tags", "root", "out", "help", "version" ]


def build_parser( tag_names = ( ) ):
    # No abbreviations. Parameter flags are named by whoever wrote the entry,
    # so any of them may one day be a prefix of a built-in one -- `--n=2,3` was
    # read as `--no-setup=2,3`, which is not a mistake anybody would have
    # thought to look for. An exact match, or nothing.
    p = argparse.ArgumentParser( prog = "errand", add_help = False, allow_abbrev = False )
    p.add_argument( "pattern", nargs = "?", help = "path[::name] target(s): paths from the cwd, globs on both sides, comma-separated" )

    # everybody's
    p.add_argument( "--env", default = None, help = "environment(s) by name, comma-separated" )
    p.add_argument( "-t", "--env-tags", default = None, help = "choose environments by tag expression" )
    p.add_argument( "--root", default = None, help = "project root (default: found from the cwd)" )
    p.add_argument( "--out", default = None, help = "output tree (default: runs)" )
    p.add_argument( "-h", "--help", action = "store_true", help = "this help; after a verb, that verb's" )
    p.add_argument( "-V", "--version", action = "store_true", help = "which errand this is" )

    # run, list
    p.add_argument( "-k", "--kind", action = "append", default = [ ],
                    help = "test, bench, experiment (repeatable)" )
    p.add_argument( "-e", "--entry-tags", default = None, help = "filter entries by tag expression" )
    p.add_argument( "-j", "--jobs", default = "1",
                    help = "how many entries at once: a number, or `auto`" )
    p.add_argument( "--batch", action = "store_true", help = "launch it and give the shell back" )
    p.add_argument( "--at", default = None,
                    help = argparse.SUPPRESS )   # internal: run exactly the entry at FILE:LINE
    # internal: which phase this process is, when a command is run in two
    p.add_argument( "--phase", default = None, choices = ( "prepare", "run" ), help = argparse.SUPPRESS )
    p.add_argument( "--from-plan", action = "store_true", help = argparse.SUPPRESS )
    p.add_argument( "--submit-run", action = "store_true", help = argparse.SUPPRESS )

    # run, shell
    p.add_argument( "--no-queue", action = "store_true",
                    help = "do not wait for the machine to be free" )
    p.add_argument( "--no-setup", action = "store_true", help = "skip the freshness check" )

    # shell
    p.add_argument( "--pull", action = "append", default = [ ], metavar = "DIR",
                    help = "on another machine: bring this directory ( relative to the project root ) back afterwards; may be repeated" )
    p.add_argument( "-x", "--claim-exclusive", dest = "exclusive", action = "store_true",
                    help = "with no --env: the machine to itself ( a benchmark )" )
    p.add_argument( "--claim-cpus", dest = "cpus", default = None, help = "with no --env: cores the command needs" )
    p.add_argument( "--claim-ram", dest = "ram", default = None, help = "with no --env: memory the command needs, e.g. 8G" )
    p.add_argument( "-m", "--claim-mem", dest = "mem", default = None,
                    help = "with no --env: memory ceiling of the command ( default 8G, 24G exclusive )" )
    p.add_argument( "-n", "--claim-label", dest = "label", default = None, help = "with no --env: its name in the queue" )
    p.add_argument( "-q", dest = "quiet", action = "store_true", help = "with no --env: no banner" )
    p.add_argument( "-l", "--claim-log", dest = "log", default = None, help = "with no --env: stdout and stderr go there" )

    # setup, init
    p.add_argument( "--force", action = "store_true",
                    help = "setup: from scratch; init: replace what is there" )
    p.add_argument( "--dry-run", action = "store_true", help = "say what setup would do, and do nothing" )

    for name in tag_names:
        p.add_argument( f"--{name.replace( '_', '-' )}", dest = f"tag_{name}", default = None,
                        help = f"environments whose {name} tag matches (comma = matrix)" )
    return p


def _takes_value( parser ):
    out = { }
    for action in parser._actions:
        for option in action.option_strings:
            out[ option ] = action.nargs != 0
    return out


def split_verb( parser, argv ):
    """-> ( the verb, argv without it ), or ( None, argv ).

    The verb is the first word that is not an option or an option's value, so
    the options everybody shares may stand on either side of it:
    `errand --env gpu run …` and `errand run --env gpu …` are the same command.
    """
    takes_value = _takes_value( parser )
    i = 0
    while i < len( argv ):
        token = argv[ i ]
        if token.startswith( "-" ) and token != "-":
            name = token.split( "=", 1 )[ 0 ]
            if "=" not in token and takes_value.get( name, False ):
                i += 1
            i += 1
            continue
        return token, argv[ : i ] + argv[ i + 1 : ]
    return None, list( argv )


def misplaced( parser, known, verb ):
    """Options given that belong to another verb. -> a message, or None.

    Said rather than ignored: `errand shell --batch -- make` would otherwise
    run the command right there and come back as if it had been launched."""
    allowed = set( COMMON ) | set( VERBS[ verb ][ 1 ] )
    for action in parser._actions:
        dest = action.dest
        if dest in allowed or dest == "pattern" or dest.startswith( "tag_" ):
            continue
        if getattr( known, dest, action.default ) != action.default:
            owners = [ v for v, ( _, own ) in VERBS.items() if dest in own ]
            return ( f"{action.option_strings[ 0 ]} is not an option of `errand {verb}`"
                     + ( f" ( it belongs to {', '.join( owners )} )" if owners else "" ) )
    return None


def print_help( parser, verb = None ):
    def options( dests ):
        for action in parser._actions:
            if action.dest in dests and action.help != argparse.SUPPRESS:
                flags = ", ".join( action.option_strings )
                if action.nargs != 0:
                    flags += f" {action.metavar or action.dest.upper()}"
                print( f"  {flags:28s} {action.help}" )

    if verb is None:
        print( "usage: errand [options] <verb> [arguments]\n" )
        print( "Run work here, in a container or on another machine, and bring back what it produced.\n" )
        print( "verbs:" )
        for name, ( what, _ ) in VERBS.items():
            print( f"  {name:8s} {what}" )
        print( "\noptions, before or after the verb:" )
        options( COMMON )
        tags = [ a for a in parser._actions if a.dest.startswith( "tag_" ) ]
        if tags:
            print( f"  {' '.join( a.option_strings[ 0 ] for a in tags )}   environments by tag value" )
        print( dim( "\n  errand <verb> --help   what that verb takes" ) )
        return

    what, own = VERBS[ verb ]
    usage = { "run"   : "errand run [options] [target [what the target takes…]]",
              "list"  : "errand list [options] [target [what the target takes…]]",
              "shell" : "errand shell [--env NAME] [-- command…]",
              "setup" : "errand setup [--env NAME] [--force] [--dry-run]",
              "forget": "errand forget ID",
              "vm"    : "errand vm stop" }.get( verb, f"errand {verb}" )
    print( f"usage: {usage}\n\n{what}" )
    if own:
        print( "\noptions:" )
        options( own )
    print( "\noptions everybody takes:" )
    options( COMMON )


def split_target( parser, rest ):
    """-> ( errand's options, the target or None, the target's arguments ).

    The target is the first word that is not one of errand's options or an
    option's value. Before it, every option must be errand's: a parameter
    written there is a mistake worth hearing about, since it belongs to the
    target -- and after it, nothing is errand's, `--env` included.
    """
    takes = _takes_value( parser )
    i = 0
    while i < len( rest ):
        token = rest[ i ]
        if token.startswith( "-" ) and token != "-":
            name = token.split( "=", 1 )[ 0 ]
            if name not in takes and not token.startswith( "--" ) and token[ : 2 ] in takes:
                i += 1                               # `-j4`: a short option and its value, attached
                continue
            if name not in takes:
                raise ValueError(
                    f"{name} is not an option of errand -- what the target takes goes after it: "
                    f"`errand run <target> {token}` ( `.` is everything under here )" )
            if "=" not in token and takes[ name ]:
                i += 1
            i += 1
            continue
        return rest[ : i ], token, rest[ i + 1 : ]
    return list( rest ), None, [ ]


def own_part( parser, argv, lenient = False ):
    """The part of a command line that is errand's: up to the target, or the
    `--` of a shell. Leniently, before the project's tag options are known, an
    unknown option is taken to have a value."""
    verb, rest = split_verb( parser, argv )
    if "--" in rest:
        rest = rest[ : rest.index( "--" ) ]
    if verb not in ( "run", "list" ):
        return rest
    if not lenient:
        return split_target( parser, rest )[ 0 ]
    takes = _takes_value( parser )
    i = 0
    while i < len( rest ):
        token = rest[ i ]
        if not token.startswith( "-" ) or token == "-":
            return rest[ : i ]
        if "=" not in token and takes.get( token, True ):
            i += 1
        i += 1
    return rest


ARGS = "args"       # the target's own arguments, in the parameters of a run


def split_args( after, declared ):
    """The target's arguments -> ( { declared parameter: raw value }, [ the rest ] ).

    A declared parameter is read wherever it is ( `--n=5`, `--n 5` ); anything
    else is the target's own business and passes through as it was written --
    after a `--`, everything does.
    """
    values, raw = { }, [ ]
    i = 0
    while i < len( after ):
        token = after[ i ]
        if token == "--":
            raw += after[ i : ]
            break
        if token.startswith( "--" ) and len( token ) > 2:
            name, eq, value = token[ 2 : ].partition( "=" )
            key = name.replace( "-", "_" )
            if key in declared:
                if not eq:
                    if i + 1 >= len( after ):
                        raise ValueError( f"--{name} needs a value" )
                    value = after[ i + 1 ]
                    i += 1
                values[ key ] = value
                i += 1
                continue
        raw.append( token )
        i += 1
    return values, raw


def shown_params( resolved, values ) -> dict:
    """What tells two runs of one case apart: the parameters, and the target's
    own arguments when there were any -- `--size 4096` and `--size 8192` are
    two runs, and must be two directories."""
    raw = values.get( ARGS ) or [ ]
    return { **resolved, ARGS: " ".join( raw ) } if raw else dict( resolved )


def target_argv( e, resolved, values ) -> list:
    """The arguments a run of `e` is handed: its declared parameters as they
    were resolved for it, then the rest as written."""
    declared = [ f"--{n.replace( '_', '-' )}={v}" for n, v in resolved.items() ]
    return declared + list( values.get( ARGS ) or [ ] )


def main( argv = None ):
    from . import __version__

    argv = list( sys.argv[ 1 : ] if argv is None else argv )

    # `--root` and `--out` are needed before the project's tags are known, so
    # this first reading takes errand's own part of the command leniently.
    pre, _ = build_parser().parse_known_args( own_part( build_parser(), argv, lenient = True ) )
    root = Path( pre.root ).resolve() if pre.root else find_root()

    config.load( root, warn = lambda m: print( warn( f"  warning: {m}" ), file = sys.stderr ) )

    out_root = Path( pre.out or config.settings.out )
    if not out_root.is_absolute():
        out_root = root / out_root

    parser = build_parser( config.tag_names() )
    verb, rest = split_verb( parser, argv )

    # Everything after a bare `--` is a command to run IN the environment
    # rather than arguments to errand: `errand shell --env gpu -- python -m
    # loom.toolchain`. The environments are described here, once, with the
    # layers that lead to them; being let into one is a smaller thing than a
    # second tool that describes them again.
    handed = None
    if verb == "shell" and "--" in rest:
        at = rest.index( "--" )
        rest, handed = rest[ : at ], rest[ at + 1 : ]

    # errand's options, then the target, then what belongs to the target --
    # its own arguments, as `python script.py args…` has them.
    target, after = None, [ ]
    if verb in ( "run", "list" ):
        try:
            before, target, after = split_target( parser, rest )
        except ValueError as err:
            print( bad( f"errand {verb}: {err}" ) )
            return 2
        known, _ = parser.parse_known_args( before )
    else:
        known, _ = parser.parse_known_args( rest )
    known.pattern, known.target_args = target, after

    if known.version and verb is None:
        # The version of the PACKAGE and the file it came out of: an editable
        # install and a copy on PYTHONPATH answer the same otherwise, and which
        # one is answering is exactly what is being asked.
        print( f"errand {__version__}  ({Path( __file__ ).resolve().parent})" )
        return 0

    if verb is None:
        # No verb runs nothing: an implicit `run` would make a file called
        # `list` or `setup.py` a verb.
        print_help( parser )
        return 0 if known.help or not argv else 2

    if verb not in VERBS:
        print( bad( f"errand: unknown verb {verb!r}" ) + dim( "   ( errand --help lists them )" ) )
        return 2

    if known.help:
        print_help( parser, verb )
        return 0

    why = misplaced( parser, known, verb )
    if why:
        print( bad( f"errand: {why}" ) )
        return 2

    # The verbs that take no pattern take no word either, `forget`'s id and
    # `vm`'s action aside: a stray word is a mistake worth hearing about.
    words = [ ]
    if verb not in ( "run", "list" ):
        known, extra = parser.parse_known_args( rest )
        words = ( [ known.pattern ] if known.pattern else [ ] ) + extra
        unknown = [ w for w in words if w.startswith( "-" ) ]
        if unknown:
            print( bad( f"errand {verb}: unknown option {unknown[ 0 ]}" ) )
            return 2
        wanted = { "forget": 1, "vm": 1, "setup": None }.get( verb, 0 )
        if wanted is not None and len( words ) != wanted:
            print( bad( f"errand {verb}: " + ( f"takes no argument ( got {' '.join( words )} )"
                                               if not wanted else "expects one argument" ) ) )
            print_help( parser, verb )
            return 2

    if verb == "tui":
        # Imported here and nowhere else: it needs `curses`, which not every
        # interpreter carries, and a missing screen must not cost the command
        # line.
        from . import tui
        return tui.main( root = root, out_root = out_root )

    if verb == "init":
        from . import detect
        return detect.init( root, force = known.force, echo = lambda s: print( dim( s ) ) )

    if verb == "envs":
        return print_envs( root )

    if verb == "shell":
        if handed is None:
            # Somebody types into it. Through the environment's own layers,
            # the default one when none is named: a shell HERE is the one you
            # typed this in. The user's own shell when the place has it -- a
            # container rarely has the zsh of the machine outside it.
            login = [ "sh", "-c", 'command -v "${SHELL:-}" >/dev/null 2>&1 && exec "$SHELL" -i; exec sh -i' ]
            return run_there( known, login, root = root, interactive = True )
        if not handed:
            print( bad( "errand shell: nothing after `--`" ) )
            return 2
        if not ( known.env or known.env_tags or _tag_values( known ) ):
            return run_here( known, handed )
        return run_there( known, handed, root = root )

    if verb == "wait":
        return queue.wait_idle()

    if verb == "forget":
        batch.forget( root, words[ 0 ] )
        return 0

    if verb in ( "status", "watch" ):
        return show_batches( root, live = verb == "watch" )

    if verb == "queue":
        return print_queue()

    if verb == "vm":
        if words != [ "stop" ]:
            print( bad( f"errand vm: unknown action {words[ 0 ]!r} ( only `stop` )" ) )
            return 2
        from . import vm
        # Every keeper is here, wherever its machine runs: stopping it stops that.
        return vm.stop_all( echo = lambda s: print( dim( s ) ) )

    if verb == "setup":
        if words:
            # `errand setup gpu,cluster` reads as well as `--env gpu,cluster`.
            known.env = ",".join( ( [ known.env ] if known.env else [ ] ) + words )
        try:
            targets = _targets( known, config.tag_names() )
        except ValueError as err:
            print( bad( str( err ) ) )
            return 1
        rc = 0
        for env, tags in targets:
            rc |= setup.ensure( root, env, L.Context( root = root, tags = tags ),
                                force = known.force, echo = lambda s: print( dim( s ) ),
                                dry_run = known.dry_run )
        return rc

    # run, list
    if known.at:
        # A child running exactly one entry: no discovery over the tree, no
        # environment selection ( it is already inside one ), no epilogue.
        # `--env` names it when the parent dispatched to one of several; being
        # INSIDE one ( a container, another machine ) names it instead, and
        # wins, because that is where this process actually is.
        inside = os.environ.get( IN_ENV )
        env_obj = ( config.envs.get( inside ) if inside
                    else config.envs.get( known.env ) if known.env
                    else config.default() )
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

    # Which environments, and with which tags. On the child side of a dispatch
    # there is exactly one, already entered.
    inside = os.environ.get( IN_ENV )
    if inside is not None:
        targets = [ ( config.envs.get( inside ) or config.Env.make( inside, [ ], { } ),
                      _tags_from_env() ) ]
    else:
        try:
            targets = _targets( known, config.tag_names() )
        except ValueError as err:
            print( bad( str( err ) ) )
            return 1

    # Recorded as the command it was, so it can be run again -- from the shell
    # or from the screen. Only on the side that was ASKED: the child of a
    # dispatch runs a command nobody typed, over there.
    if inside is None and verb == "run":
        history.push( root, argv )

    if inside is None and verb == "run" and known.batch:
        forward = [ a for a in before if a != "--batch" ] + ( [ target ] if target else [ ] ) + after
        return submit( targets, forward, argv, root = root, out_root = out_root )

    if known.submit_run:
        env, tags = targets[ 0 ]
        return submit_run( env, tags, [ a for a in before if a != "--submit-run" ]
                                      + ( [ target ] if target else [ ] ) + after, root = root )

    report = Report()
    rc, dispatched = 0, 0
    for env, tags in targets:
        if inside is None and env.wraps_anything( tags ):
            # This side only chooses where, and hands the command over as it
            # was typed: what it designates is for that place to say.
            if not known.no_setup:
                if setup.ensure( root, env, L.Context( root = root, tags = tags ),
                                 echo = lambda s: print( dim( s ), flush = True ) ):
                    print( bad( f"  could not prepare {env.name}" ) )
                    rc = 1
                    continue
            print( dim( f"\n  -> {env.name}  {env.describe()}" ), flush = True )
            rc |= go_there( env, tags, verb, rest, root = root )
            dispatched += 1
            continue
        rc |= here( env, tags, verb, rest, known, root = root, out_root = out_root,
                    report = report, kinds = kinds, inside = inside )

    # The child of a dispatch has already said how it went, in full. Saying it
    # again here -- out of a report that ran nothing and knows nothing -- is an
    # "all good" under somebody else's failures, which is worse than silence.
    if verb == "list" or ( dispatched and dispatched == len( targets ) ):
        return rc
    if known.phase == "prepare":
        return rc or ( 1 if report.broken else 0 )
    return _epilogue( report, rc )


# ── one environment, from inside it ──────────────────────────────────────────

PLANS = ".errand/plans"


def plan_path( root, env_name ) -> Path:
    """Where the plan of this command in that environment is written: the same
    path on both sides of a dispatch, since both know the stamp and the name."""
    return Path( root ) / PLANS / f"{R.stamp()}-{R.slug( env_name or 'default' )}.json"


def read_plan( root, env_name ):
    import json
    try:
        return json.loads( plan_path( root, env_name ).read_text() )
    except ( OSError, ValueError ):
        return None


def planned( root, stamp ) -> list:
    """Every run the command of that stamp has said it will produce, in every
    place whose plan is here -- written here, or brought back from there."""
    import json
    out = [ ]
    for path in sorted( ( Path( root ) / PLANS ).glob( f"{stamp}-*.json" ) ):
        if path.name.endswith( ".submitted.json" ):
            continue
        try:
            out += json.loads( path.read_text() )[ "runs" ]
        except ( OSError, ValueError, KeyError ):
            pass
    return out


def make_plan( env, tags, entries, combos, *, root, out_root ) -> dict:
    """What this command is about to do here: the entries, what they ask of a
    machine, and the directories they will write. Written before anything
    runs, and read by whoever has to know before the fact -- the side that
    fetches back, `status`, the screen, and an allocation sized from it."""
    return {
        "env"    : env.name,
        "stamp"  : R.stamp(),
        "needs"  : aggregate_needs( entries ),
        "entries": [ { "name": e.name, "file": str( R._under( e.file, root ) ), "line": e.line,
                       "runner": e.runner.name if e.runner is not None else "errand" }
                     for e in entries ],
        "runs"   : plan_of( [ ( env, tags ) ], entries, combos, root = root, out_root = out_root ),
    }


def here( env, tags, verb, rest, known, *, root, out_root, report, kinds, inside ):
    """Resolve, build, collect and run, in this process: the environment is the
    one this process is in -- entered by a dispatch, or one that wraps nothing."""
    import json
    from . import __version__

    _put_src_on_path( root )

    if config.guessed and verb == "run" and inside is None:
        from . import detect
        print( dim( f"  {detect.announce( config.guessed )}   ( errand init writes it down )" ),
               file = sys.stderr )

    # What can only be listed once built is built now, in this place -- except
    # in the run phase of two, which finds the preparation's build in place.
    context = P.RunContext( root = root, out_dir = out_root, env = { },
                            build_dir = build_dir_for( root, env.name ) )
    context.build_dir.mkdir( parents = True, exist_ok = True )
    try:
        selected, modules, selectors = discovery.select(
            known.pattern, root, kinds = kinds, entry_tags = known.entry_tags,
            bulk_only = not known.pattern and not kinds, exclude = config.settings.exclude,
            runners = config.runners, context = context, build = not known.from_plan,
        )
    except ValueError as err:
        print( bad( str( err ) ) )
        return 1
    report.broken += [ b for b in discovery.broken if b not in report.broken ]

    # The parameters only exist once we know which entries matched: they are
    # read out of the target's arguments, and the rest is handed to it.
    declared = { }
    for e in selected:
        declared.update( e.params )
    args = known
    try:
        raw_values, raw = split_args( known.target_args, declared )
    except ValueError as err:
        print( bad( str( err ) ) )
        return 1

    if verb == "list":
        print_entries( selected )
        say_broken()
        return 1 if discovery.broken else 0

    try:
        combos = expand( { n: raw_values.get( n ) for n in declared }, declared, raw )
        how_many = job_count( args.jobs )
    except ValueError as err:
        print( bad( str( err ) ) )
        return 1

    if not selected:
        print( bad( f"nothing matched {known.pattern!r}" if known.pattern else "nothing to run" ) )
        if discovery.broken:
            # "nothing to run" when in fact nothing could be READ is the kind of
            # answer that sends somebody looking in the wrong place.
            say_broken()
            return 1
        _suggest( root )
        return 1

    plan = make_plan( env, tags, selected, combos, root = root, out_root = out_root )
    where = plan_path( root, env.name )
    if known.from_plan:
        # The run phase of two: what is here now must be what was prepared,
        # sized and announced. Otherwise the sources moved in between, or the
        # filesystem the two phases share is not shared.
        before = read_plan( root, env.name )
        if before is None or before[ "entries" ] != plan[ "entries" ] or before[ "runs" ] != plan[ "runs" ]:
            print( bad( f"  {env.name}: what is here is not what was prepared "
                        f"( {_short( where, root )} ) -- the sources changed between the two phases, "
                        f"or the root is not on a filesystem both of them see" ) )
            return 1
    else:
        where.parent.mkdir( parents = True, exist_ok = True )
        where.write_text( json.dumps( plan, indent = 1 ) )

    # Running here rather than in a child, either because nothing needed
    # wrapping or because the wrapping already happened and this IS the
    # child. Either way no command is about to be rewritten, so what the
    # layers meant to put in the environment has to be put there directly --
    # and `Vars` is the only kind that can act without a new process at all.
    phase = known.phase or "run"
    os.environ.update( L.compose( [ l for l in env.stack_for( phase, tags ) if isinstance( l, L.Vars ) ],
                                  L.Command( [ "python" ] ),
                                  L.Context( root = root, tags = tags ) ).env )

    if not known.from_plan:
        # Build once, here, before anything runs: a suite is built once and not
        # once per file, and under `-j` several children would otherwise write
        # the same binary at the same time.
        trouble = prepare_runners( selected, root = root, out_root = out_root, tags = tags,
                                   env_name = env.name )
        if trouble:
            for who, why in trouble:
                print( bad( f"  {who}: {why}" ) )
            return 1

    if len( combos ) > 1 and not known.from_plan:
        print( dim( f"  {describe_grid( combos )}" ), flush = True )

    if phase == "prepare":
        print( dim( f"  prepared {len( selected )} entr{'y' if len( selected ) == 1 else 'ies'} "
                    f"in {env.name}: {_short( where, root )}" ), flush = True )
        return 0

    if how_many > 1:
        run_in_processes( selected, combos, root = root, out_root = out_root, env = env,
                          tags = tags, how_many = how_many, report = report,
                          out_prefix = R.place( env.name ) )
        return 0

    for i, ( varied, values ) in enumerate( combos ):
        if varied:
            shown = ", ".join( f"{k.replace( '_', '-' )}={v}" for k, v in varied.items() )
            print( head( f"\n--- {i + 1}/{len( combos )}  {shown} ---" ), flush = True )
        run_entries( selected, modules, root = root, out_root = out_root,
                     overrides = values, env_name = env.name, tags = tags,
                     version = __version__, report = report,
                     queued = not args.no_queue, selectors = selectors )
    return 0


# ── one environment, from outside it ────────────────────────────────────────

def child_env_for( env, tags ) -> dict:
    """What crosses into the environment: which one it is, its resolved tags,
    and the stamp of this command -- NOT `--env`, since re-selecting over there
    would send an ssh environment straight back out to the machine it is on."""
    return { IN_ENV: env.name,
             TAGS: ",".join( f"{k}={v}" for k, v in sorted( tags.items() ) ),
             R.STAMP_ENV: R.stamp(),
             "PYTHONUNBUFFERED": "1" }


def go_there( env, tags, verb, rest, *, root ):
    """The command, in `env`: one pass, or a preparation and then a run sized
    from the plan it wrote. -> the return code."""
    if env.vm is not None:
        # The child would be errand itself, over there -- and errand is a unix
        # program. A command is what a virtual machine takes, for now.
        print( bad( f"  {env.name} is a virtual machine: entries do not run in one yet -- "
                    f"errand shell --env {env.name} -- <command>" ) )
        return 1

    def through( phase, extra, needs = None ):
        stack = env.stack_for( phase, tags )
        ctx = L.Context( root = root, tags = tags, needs = needs or { }, phase = phase )
        cmd = L.Command( [ "python", "-m", "errand", verb, *extra, *rest ], child_env_for( env, tags ) )
        ssh = L.ssh_of( stack )
        for message in L.warnings_for( stack, ssh.remote_root( ctx ) if ssh else root ):
            print( warn( f"  warning: {message}" ), flush = True )
        if ssh is None:
            wrapped = L.compose( stack, cmd, ctx )
            print( dim( f"  $ {' '.join( str( a ) for a in wrapped.argv )}" ), flush = True )
            return subprocess.run( wrapped.argv, env = { **os.environ, **wrapped.env },
                                   cwd = root ).returncode
        return ssh.run( stack[ 1 : ], cmd, ctx, echo = lambda s: print( dim( s ), flush = True ) )

    def fetch( paths ):
        ssh = L.ssh_of( env.stack_for( "run", tags ) )
        if ssh is not None and paths:
            there = ssh.remote_root( L.Context( root = root ) )
            print( dim( f"  rsync pull  <- {ssh.host}:{there} [{', '.join( paths )}]" ), flush = True )
            L.fetch( paths, ssh.host, there, root, ssh.options )

    def bring_back( ):
        fetch( [ PLANS ] )
        plan = read_plan( root, env.name )
        if plan is not None:
            fetch( sorted( { r[ "under" ] for r in plan[ "runs" ] } ) )
        return plan

    if verb == "list":
        # What would run there is what preparing there finds.
        return through( "prepare", [ ] )

    if env.single_pass( tags ):
        rc = through( "run", [ ] )
        bring_back()
        return rc

    rc = through( "prepare", [ "--phase", "prepare" ] )
    fetch( [ PLANS ] )
    plan = read_plan( root, env.name )
    if rc or plan is None:
        if plan is None and not rc:
            print( bad( f"  {env.name}: the preparation wrote no plan" ) )
        return rc or 1
    rc = through( "run", [ "--from-plan" ], needs = plan[ "needs" ] )
    bring_back()
    return rc


def _tag_values( known ) -> bool:
    """Whether an environment was asked for by one of its tags ( `--driver torch` )."""
    return any( v is not None for k, v in vars( known ).items() if k.startswith( "tag_" ) )


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
            print( dim( f"    {os.path.relpath( p )}" ) )


if __name__ == "__main__":
    sys.exit( main() )
