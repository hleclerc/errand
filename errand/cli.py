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

from . import config, discovery, entries as E, layers as L, local, queue, results as R, setup

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
def capture( ):
    """Mirror stdout/stderr into a buffer while still printing live, so the run
    keeps its console feed and output.txt gets written anyway."""
    buf = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = Tee( old_out, buf ), Tee( old_err, buf )
    try:
        yield buf
    finally:
        sys.stdout, sys.stderr = old_out, old_err


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
                 container, version, report, queued = True ):
    E.set_tags( tags )
    where = R.place( container )
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
                          echo = lambda m: print( dim( m ), flush = True ) ):
            started = time.perf_counter()
            with capture() as buf:
                try:
                    discovery.import_file( modules[ e.module ], root )
                except local.Skipped as s:
                    status, error, hint = "SKIP", s.reason, s.hint
                except BaseException as exc:             # SystemExit included
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
    p.add_argument( "-j", "--jobs", default = None, help = "how many at once" )
    p.add_argument( "--no-queue", action = "store_true",
                    help = "do not wait for the machine to be free" )
    p.add_argument( "--queue", action = "store_true", help = "what the host is busy with, and stop" )
    p.add_argument( "-h", "--help", action = "store_true", help = "show what matched, and its parameters" )
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

    if known.envs:
        return print_envs( root )

    if known.queue:
        return print_queue()

    kinds = set()
    for k in known.kind:
        if k not in KINDS:
            print( bad( f"unknown kind {k!r}; expected one of {', '.join( sorted( KINDS ) )}" ) )
            return 2
        kinds.add( KINDS[ k ] )

    sys.path.insert( 0, str( root ) )
    for extra in ( config.settings.src or [ "src" ] ):
        if ( root / extra ).is_dir():
            sys.path.insert( 0, str( root / extra ) )

    try:
        selected, modules = discovery.select(
            known.pattern, root, kinds = kinds, entry_tags = known.entry_tags,
            bulk_only = not known.pattern and not kinds, exclude = config.settings.exclude,
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
        return 0

    try:
        combos = expand( { n: getattr( args, n, None ) for n in declared }, declared )
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
        _suggest( root )
        return 1

    report = Report()
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

        for i, ( varied, values ) in enumerate( combos ):
            if varied:
                shown = ", ".join( f"{k.replace( '_', '-' )}={v}" for k, v in varied.items() )
                print( head( f"\n--- {i + 1}/{len( combos )}  {shown} ---" ), flush = True )
            run_entries( selected, modules, root = root, out_root = out_root,
                         overrides = values, env_name = env.name, tags = tags,
                         container = env.container, version = __version__, report = report,
                         queued = not args.no_queue )

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
