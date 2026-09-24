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

from . import discovery, entries as E, results as R

BOLD, DIM, GREEN, RED, CYAN, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[36m", "\033[0m" )

if not sys.stdout.isatty() or os.environ.get( "NO_COLOR" ):
    BOLD = DIM = GREEN = RED = CYAN = RESET = ""


def dim( s ):  return f"{DIM}{s}{RESET}"
def head( s ): return f"{BOLD}{CYAN}{s}{RESET}"
def bad( s ):  return f"{RED}{s}{RESET}"
def good( s ): return f"{GREEN}{s}{RESET}"


KINDS = { "test": "test", "bench": "bench", "experiment": "experiment", "exp": "experiment" }


def find_root( start: Path | None = None ) -> Path:
    """The project root: the nearest ancestor holding an errand.py, else here.

    Deliberately not the git root. Walking up to one means that running from a
    subdirectory of a large repository silently widens the search to the whole
    of it -- and with no errand.py there is nothing that says where the project
    begins, so "here and below" is the answer least likely to surprise.
    `--root` says otherwise.
    """
    here = ( start or Path.cwd() ).resolve()
    for directory in [ here, *here.parents ]:
        if ( directory / "errand.py" ).is_file():
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


# ── parameter matrices ───────────────────────────────────────────────────────

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


# ── running ──────────────────────────────────────────────────────────────────

def run_entries( entries, modules, *, root, out_root, overrides, env_name, tags, version ):
    failures = [ ]
    E.set_tags( tags )
    print( head( f"\n{'=' * 10} {len( entries )} entr{'y' if len( entries ) == 1 else 'ies'} "
                 f"{'=' * 10}" ), flush = True )
    where = R.place()

    for e in entries:
        try:
            resolved = E.resolve_params( e.params, overrides )
        except ValueError as err:
            print( bad( f"  {e.name}: {err}" ) )
            failures.append( e )
            continue

        leaf, entry_root = R.dirs_for( out_root, e, resolved, where )
        R.clear( leaf )
        R.point_latest_at( leaf )

        site = f"{e.file.name}:{e.line}"
        if resolved:
            shown = ", ".join( f"{k}={v!r}" for k, v in resolved.items() )
            print( dim( f"  {e.name} ({site}) -- {shown}" ), flush = True )

        E.begin_run( e, resolved, leaf )
        started, status, error = time.perf_counter(), "PASS", None
        with capture() as buf:
            try:
                discovery.import_file( modules[ e.module ], root )
            except BaseException as exc:                 # SystemExit included
                status, error = "FAIL", f"{type( exc ).__name__}: {exc}"
                traceback.print_exc()
        duration = time.perf_counter() - started
        E.end_run()

        if status == "PASS":
            print( f"{GREEN}PASS{RESET} {e.name} {dim( f'({site})' )}", flush = True )
            if e.traits[ "stable_path" ]:
                # What it produced IS the point, so name the files and the path
                # to open, rather than leave it to be reconstructed.
                written = sorted( f.name for f in leaf.iterdir()
                                  if f.name not in ( R.RESULT, R.OUTPUT ) )
                shown = leaf.parent / R.LATEST
                print( dim( f"  {_short( shown, root )}/" ) )
                for name in written:
                    print( dim( f"    {name}" ) )
        else:
            print( f"{RED}FAIL{RESET} {e.name} {dim( f'({site})' )} - {error}", flush = True )
            failures.append( e )

        R.write_result(
            leaf, entry = e, root = root, env_name = env_name, where = where, tags = tags,
            status = status, error = error, duration_s = duration, ram = R.ram_mb(),
            params = resolved, results = dict( E.results ), output_text = buf.getvalue(),
            version = version,
        )
        R.refresh( entry_root )

    return failures


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

def build_parser( ):
    p = argparse.ArgumentParser( prog = "errand", add_help = False, description =
        "Run work here, in a container or on another machine, and bring back what it produced." )
    p.add_argument( "pattern", nargs = "?", help = "file[::name] spec(s), comma-separated, globbable" )
    p.add_argument( "-k", "--kind", action = "append", default = [ ],
                    help = "test, bench, experiment (repeatable)" )
    p.add_argument( "-e", "--entry-tags", default = None, help = "filter entries by tag expression" )
    p.add_argument( "-t", "--env-tags", default = None, help = "choose environments by tag expression" )
    p.add_argument( "--env", default = None, help = "environment, by name" )
    p.add_argument( "--envs", action = "store_true", help = "list environments and stop" )
    p.add_argument( "--out", default = None, help = "output tree (default: runs)" )
    p.add_argument( "--root", default = None, help = "project root (default: found from the cwd)" )
    p.add_argument( "-j", "--jobs", default = None, help = "how many at once" )
    p.add_argument( "-h", "--help", action = "store_true", help = "show what matched, and its parameters" )
    return p


def main( argv = None ):
    from . import __version__

    parser = build_parser()
    known, _ = parser.parse_known_args( argv )

    root = Path( known.root ).resolve() if known.root else find_root()
    out_root = Path( known.out ) if known.out else root / "runs"
    if not out_root.is_absolute():
        out_root = root / out_root

    kinds = set( )
    for k in known.kind:
        if k not in KINDS:
            print( bad( f"unknown kind {k!r}; expected one of {', '.join( sorted( KINDS ) )}" ) )
            return 2
        kinds.add( KINDS[ k ] )

    if known.envs:
        print( head( "\nEnvironments" ) )
        print( dim( "  (none declared -- running in this interpreter)" ) )
        return 0

    sys.path.insert( 0, str( root ) )
    for extra in ( "src", ):
        if ( root / extra ).is_dir():
            sys.path.insert( 0, str( root / extra ) )

    try:
        selected, modules = discovery.select(
            known.pattern, root, kinds = kinds, entry_tags = known.entry_tags,
            bulk_only = not known.pattern and not kinds,
        )
    except ValueError as err:
        print( bad( str( err ) ) )
        return 1

    # Second pass: the parameters only exist once we know which entries matched.
    declared = { }
    for e in selected:
        declared.update( e.params )
    for name, p in declared.items():
        flag = f"--{name.replace( '_', '-' )}"
        # type=str, not p.ptype: argparse would coerce too early for a matrix
        # like `--n=1000,5000` to still be visible as one string.
        parser.add_argument( flag, dest = name, type = str, default = None, help = p.help )
    args = parser.parse_args( argv )

    if args.help:
        print_entries( selected )
        return 0

    if not selected:
        print( bad( f"nothing matched {args.pattern!r}" if args.pattern else "nothing to run" ) )
        _suggest( root )
        return 1

    try:
        combos = expand( { n: getattr( args, n, None ) for n in declared }, declared )
    except ValueError as err:
        print( bad( str( err ) ) )
        return 1

    failures = [ ]
    for i, ( varied, values ) in enumerate( combos ):
        if varied:
            shown = ", ".join( f"{k.replace( '_', '-' )}={v}" for k, v in varied.items() )
            print( head( f"\n--- {i + 1}/{len( combos )}  {shown} ---" ), flush = True )
        failures += run_entries(
            selected, modules, root = root, out_root = out_root, overrides = values,
            env_name = args.env or "default", tags = { }, version = __version__,
        )

    print( "\n" + "=" * 46 )
    if failures:
        for e in failures:
            print( f"  {bad( 'FAILED' )} {e.name}  ({e.file}:{e.line})" )
        return 1
    print( good( "  all good" ) )
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
