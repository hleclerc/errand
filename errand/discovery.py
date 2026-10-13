"""Finding the files that hold work, and the entries inside them.

A pattern is a comma-separated list of `path[::name]` targets, paths relative
to the cwd and both sides globs: see `targets`.

Which runner a file is for is asked of every runner in `errand.runners`, and
the one that fits it best takes it ( see `runners` ). Walking the tree finds
only what declares itself as work -- errand's own files and the suites of a
framework; a script or an executable is taken only when it is named.

Candidate files of errand's own are found by a text check rather than by
importing everything: a file is one if it IMPORTS `errand`. Without that, a
source file sharing its entry's name (`Cell.py` next to `test_Cell.py`) would
be taken for one -- and a file that merely mentions errand in a comment would
be imported and executed on the strength of a word.

Reading one is tolerant: a file that will not import costs its own row in
`broken` and nothing else. Everything else still runs, and the runner reports
what it could not read and fails over it.
"""
from __future__ import annotations

import contextlib
import importlib.util
import os
import sys
from pathlib import Path

from . import entries as E, runner as R, targets as T

SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", "build", "dist",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".cache", ".idea", ".vscode", "target", "runs", ".claude",
}

# The package errand imports candidate files under. A synthetic root, so that a
# file under tests/ is never confused with an installed package of the same
# name, while ancestor directories still act as packages -- which is what makes
# a relative import inside a candidate file resolve against its own directory.
SCAN_PKG = "_errand_scan"


def iter_files( root: Path, exclude = ( ) ):
    from .config import config_in

    skip = SKIP_DIRS | { e.strip( "/" ) for e in exclude }
    for dirpath, dirnames, filenames in os.walk( root ):
        dirnames[ : ] = [ d for d in dirnames
                          if d not in skip and not d.endswith( ".egg-info" )
                          # A directory holding a config file of its own is
                          # ANOTHER PROJECT, and its entries are not ours to
                          # run: they would run with our `src`, our runners
                          # and our environments -- which is to say wrongly.
                          and config_in( Path( dirpath ) / d ) is None ]
        for f in filenames:
            yield Path( dirpath ) / f


def _runners( runners ):
    if runners is None:
        from . import config
        runners = config.runners
    return list( runners )


def owners( path: Path, runners, at_least = R.NONE ):
    """-> ( the best level, [ the runners at it ] ) for one file.

    `at_least` leaves out the runners that could not reach it anyway: walking a
    whole tree asks only the ones that could make a file discoverable.
    """
    best, who = R.NONE, [ ]
    for r in runners:
        if r.level < max( at_least, best, R.FALLBACK ):
            continue
        got = R.Level( r.suitability( path ) )
        if got > best:
            best, who = got, [ r ]
        elif got == best and got > R.NONE:
            who.append( r )
    return best, who


def pool( root: Path, exclude = ( ), runners = None ) -> dict:
    """{ path: ( level, [ runners ] ) } for every file found by walking: the
    ones that declare themselves as work."""
    runners = _runners( runners )
    out = { }
    for f in iter_files( root, exclude ):
        level, who = owners( f, runners, R.FRAMEWORK )
        if level.discoverable:
            out[ f ] = ( level, who )
    return out


def candidates( root: Path, exclude = ( ), runners = None ) -> list[ Path ]:
    """Every file a walk finds work in, whoever runs it."""
    return sorted( pool( root, exclude, runners ), key = str )


def errand_files( root: Path, exclude = ( ) ) -> list[ Path ]:
    """The files that declare errand's own entries."""
    return candidates( root, exclude, [ R.Errand() ] )


# ── patterns ─────────────────────────────────────────────────────────────────

def _near( files, root, cwd ):
    """-> a function suggesting the paths closest to what was typed."""
    from . import fuzzy

    shown = [ os.path.relpath( f, cwd ) for f in files ]

    def near( typed ):
        typed = typed.replace( "*", " " ).replace( "/", " " ).strip()
        if not typed:
            return [ ]
        ranked = fuzzy.rank( typed, shown, lambda x: { "path": ( x, 1.0 ) } )
        return [ item for item, _, _ in ranked[ : 4 ] ]
    return near


# ── importing ────────────────────────────────────────────────────────────────

def import_file( path: Path, root: Path ):
    """Import `path` under `_errand_scan.<dir>...<stem>`, freshly every time.

    Ancestor directories are registered as namespace packages with their real
    `__path__`, so a relative import inside the file resolves against its own
    directory. Only the leaf is re-executed, which is what the reload-per-entry
    model needs.

    Returns ( module, dotted_name ), or ( None, dotted_name ) when the file
    withdrew itself with `sys.exit` -- the way a file says it does not apply to
    this run, before importing what would fail.
    """
    parts = path.resolve().relative_to( root.resolve() ).with_suffix( "" ).parts
    pkg, directory = SCAN_PKG, root.resolve()
    for part in parts[ : -1 ]:
        pkg, directory = f"{pkg}.{part}", directory / part
        if pkg not in sys.modules:
            spec = importlib.util.spec_from_loader( pkg, loader = None, is_package = True )
            module = importlib.util.module_from_spec( spec )
            module.__path__ = [ str( directory ) ]
            sys.modules[ pkg ] = module

    name = f"{pkg}.{parts[ -1 ]}"
    spec = importlib.util.spec_from_file_location( name, path )
    module = importlib.util.module_from_spec( spec )
    sys.modules[ name ] = module
    # A file that declares work can import its neighbours. Work is declared
    # NEXT TO the code it exercises, so `test_primes.py` importing `primes`
    # from the same directory is the ordinary case -- and it must not depend on
    # which directory errand happened to be started from. Put back straight
    # afterwards: what the import needed is in `sys.modules` by then, and a
    # path left behind would decide somebody else's import later on.
    here = str( path.resolve().parent )
    borrowed = here not in sys.path
    if borrowed:
        sys.path.insert( 0, here )
    try:
        spec.loader.exec_module( module )
    except SystemExit:
        # Caught here on purpose: a SystemExit raised during an import would
        # otherwise reach the top and end the process silently, with status 0 --
        # an empty discovery rather than a skipped file.
        sys.modules.pop( name, None )
        return None, name
    finally:
        if borrowed:
            with contextlib.suppress( ValueError ):
                sys.path.remove( here )
    return module, name


# Files that declare work and could not be read, from the last `collect`:
# [ ( path, the short of it, the whole traceback ) ].
#
# A list and not an exception, because ONE FILE THAT WILL NOT IMPORT MUST NOT
# COST EVERY OTHER ENTRY. A missing dependency in one corner of a tree is an
# ordinary state of affairs -- half a project installed, an example nobody set
# up -- and refusing to run anything at all over it is the worse answer.
#
# Not silence either: what could not be read is reported, and it fails the run.
broken: list = [ ]

# The runners `select` built to collect, so that nothing builds them twice.
built: list = [ ]


def collect( files: list[ Path ], root: Path, reset = True ):
    """Import every file and return ( entries, { module_name: path } )."""
    import traceback

    E.reset_collection()
    if reset:
        broken.clear()
    modules = { }
    for f in files:
        try:
            module, name = import_file( f, root )
        except BaseException as err:          # SystemExit is handled inside
            broken.append( ( f, f"{type( err ).__name__}: {err}", traceback.format_exc() ) )
            continue
        if module is not None:
            modules[ name ] = f
    return list( E.collected ), modules


def select_at( path: Path, line: int, root: Path ):
    """The one entry declared at `path:line` -- and only that file imported.

    A child running a single entry has no use for the rest of the tree, and
    paying for a full discovery in every one of them is what would make a
    process per entry too expensive to be worth having.
    """
    entries, modules = collect( [ path ], root )
    for e in entries:
        if e.line == line:
            return [ e ], modules
    return [ ], modules


def select( pattern, root, kinds = None, entry_tags = None, bulk_only = False, exclude = ( ),
            runners = None, cwd = None, context = None, build = True ):
    """Everything the command line asked for: ( entries, modules, selectors ).

    Raises ValueError when a target designates nothing, when two runners claim
    a file equally, or when a `::name` matches no entry of the files it is
    about: a typo must not be an empty, successful run.
    """
    from .expr import matches

    runners = _runners( runners )
    cwd = Path( cwd or os.getcwd() )
    broken.clear()
    built.clear()
    found = pool( root, exclude, runners )

    def explicit( path: Path ) -> bool:
        # Named in full: whatever can run it at all may, a script included.
        level, who = owners( path, runners )
        if level == R.NONE:
            return False
        found[ path ] = ( level, who )
        return True

    files = sorted( found, key = str )
    specs = T.resolve( pattern, files, cwd = cwd, root = root, explicit = explicit,
                       suggest = _near( files, root, cwd ) )
    wanted = list( dict.fromkeys( f for matched, _ in specs for f in matched ) )

    by_runner = { }
    for f in wanted:
        level, who = found[ f ]
        if len( who ) > 1:
            names = " and ".join( r.name for r in who )
            raise ValueError(
                f"{os.path.relpath( f, cwd )}: {names} both take it, at level {level.name} -- "
                f"keep one ( errand.runners.replace( … ) puts a configured runner in place of "
                f"the default one, errand.runners.remove( … ) takes one out )" )
        by_runner.setdefault( id( who[ 0 ] ), ( who[ 0 ], [ ] ) )[ 1 ].append( f )

    def mine( files ):
        # The specs again, over this runner's files only.
        keep = set( files )
        return [ T.Spec( [ f for f in spec[ 0 ] if f in keep ], spec[ 1 ], spec.text )
                 for spec in specs ]

    all_entries, modules = [ ], { }
    for r, files in by_runner.values():
        if getattr( r, "in_process", False ):
            # errand's own: read by importing, run by re-importing.
            got, modules = collect( files, root, reset = False )
            all_entries += got
            continue
        r.context = context
        if r.builds_to_collect and build and context is not None:
            # What it holds can only be listed once it is built: so it is
            # built now, here, once -- and a failed build costs its files'
            # rows, not the run.
            why = r.prepare( [ ], context )
            built.append( r )
            if why:
                broken.extend( ( f, f"{r.name}: {why.splitlines()[ 0 ]}", why ) for f in files )
                continue
        all_entries += r.collect( mine( files ) )
        broken.extend( ( f, f"{r.name}: {why.splitlines()[ 0 ]}", why )
                       for f, why in getattr( r, "broken", [ ] ) )

    selectors = { }

    def named( e, name_glob ):
        # A runner whose entries are whole files consumes the `::name` itself;
        # filtering on it here would reject the entry for not being called
        # after one of its own cases.
        consumed = e.runner is not None and e.runner.whole_files
        return name_glob is None or consumed or T.name_matches( name_glob, e.name )

    for spec in specs:
        matched, name_glob = spec
        if name_glob is None:
            continue
        # A file run as a whole has nothing to choose a `::name` from, unless
        # its runner hands the name on to it.
        for f in matched:
            r = found[ f ][ 1 ][ 0 ]
            if r.whole_files and not r.takes_selector:
                raise ValueError( f"'{spec.text}': {os.path.relpath( f, cwd )} is run as a whole "
                                  f"( {r.name} ), with no entries to choose from" )
        # Every `::name` has to find something, before any filter: `-k bench`
        # on a test is a choice, `::basik` is a typo.
        here = [ e for e in all_entries if e.file in matched ]
        if here and not any( named( e, name_glob ) for e in here ):
            from . import fuzzy
            there = list( dict.fromkeys( e.name for e in here ) )
            near = [ n for n, _, _ in fuzzy.rank( name_glob.replace( "*", " " ), there,
                                                  lambda n: { "name": ( n, 1.0 ) } )[ : 3 ] ]
            shown = near or there[ : 8 ]
            raise ValueError( f"'{spec.text}' matches no entry\n  "
                              + ( "did you mean:  " if near else "there:  " )
                              + "  ".join( repr( n ) for n in shown ) )

    out = [ ]
    for e in all_entries:
        for matched, name_glob in specs:
            if e.file not in matched or not named( e, name_glob ):
                continue
            if kinds and e.kind not in kinds:
                continue
            if bulk_only and not e.traits[ "bulk" ]:
                continue
            if entry_tags and not matches( entry_tags, e.tags ):
                continue
            out.append( e )
            if e.runner is not None:
                selectors[ e.name ] = R.selector_of( specs, e.file )
            break
    return out, modules, selectors
