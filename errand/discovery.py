"""Finding the files that declare work, and the entries inside them.

A pattern is a comma-separated list of `file[::name]` specs, both sides
globbable with `*`. The file part matches the full stem and is looked for
anywhere under the root, with no directory or project distinction; with no
`*` it must resolve to exactly one file.

Candidate files are found by a text check rather than by importing everything:
a file is a candidate if it mentions `errand`. Without that, a source file
sharing its entry's name (`Cell.py` next to `test_Cell.py`) would be a false
ambiguity for what should be an unambiguous lookup.
"""
from __future__ import annotations

import fnmatch
import importlib.util
import sys
from pathlib import Path

from . import entries as E

SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", "build", "dist",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".cache", ".idea", ".vscode", "target", "runs", ".claude",
}

MARKER = "errand"

# The project's own files: they mention errand by nature, and re-executing one
# as if it declared work would register everything it declares a SECOND time --
# providers twice over, environments twice over, every entry duplicated.
NOT_WORK = ( "errandfile.py", "errand.py", "errand.local.py" )

# The package errand imports candidate files under. A synthetic root, so that a
# file under tests/ is never confused with an installed package of the same
# name, while ancestor directories still act as packages -- which is what makes
# a relative import inside a candidate file resolve against its own directory.
SCAN_PKG = "_errand_scan"


def iter_py_files( root: Path, exclude = ( ) ):
    import os
    skip = SKIP_DIRS | { e.strip( "/" ) for e in exclude }
    for dirpath, dirnames, filenames in os.walk( root ):
        dirnames[ : ] = [ d for d in dirnames
                          if d not in skip and not d.endswith( ".egg-info" ) ]
        for f in filenames:
            if f.endswith( ".py" ):
                yield Path( dirpath ) / f


def candidates( root: Path, exclude = ( ) ) -> list[ Path ]:
    here = Path( __file__ ).resolve().parent      # errand's own sources mention the marker
    out = [ ]
    for p in iter_py_files( root, exclude ):
        if here in p.resolve().parents or p.name in NOT_WORK:
            continue
        try:
            if MARKER in p.read_text( errors = "ignore" ):
                out.append( p )
        except OSError:
            pass
    return sorted( out )


# ── patterns ─────────────────────────────────────────────────────────────────

def parse_pattern( pattern: str | None, files: list[ Path ], root: Path ):
    """-> [ ( matched_files, name_glob | None ), ... ], one per comma-separated spec."""
    specs = [ s.strip() for s in pattern.split( "," ) ] if pattern else [ "" ]
    return [ _one_spec( s, files, root ) for s in specs ]


def _declares_entries( path: Path ) -> bool:
    try:
        return MARKER in path.read_text( errors = "ignore" )
    except OSError:
        return False


def _one_spec( spec, files, root ):
    file_part, sep, name_glob = spec.partition( "::" )
    file_part = file_part.strip()
    name_glob = name_glob.strip() if sep else None
    name_glob = name_glob or None

    if not file_part:
        return list( files ), name_glob

    if "*" in file_part or "?" in file_part:
        return [ p for p in files if fnmatch.fnmatchcase( p.stem, file_part ) ], name_glob

    matched = [ p for p in files if p.stem == file_part ]
    if len( matched ) > 1:
        shown = ", ".join( str( p.relative_to( root ) ) for p in matched )
        raise ValueError( f"'{file_part}' matches several files ({shown}) -- "
                          f"use a glob, e.g. '{file_part}*', to take them all" )
    # Zero is not an error here: the file part may belong to another provider.
    return matched, name_glob


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
    parts = path.resolve().relative_to( root ).with_suffix( "" ).parts
    pkg, directory = SCAN_PKG, root
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
    try:
        spec.loader.exec_module( module )
    except SystemExit:
        # Caught here on purpose: a SystemExit raised during an import would
        # otherwise reach the top and end the process silently, with status 0 --
        # an empty discovery rather than a skipped file.
        sys.modules.pop( name, None )
        return None, name
    return module, name


def collect( files: list[ Path ], root: Path ):
    """Import every file and return ( entries, { module_name: path } )."""
    E.reset_collection()
    modules = { }
    for f in files:
        module, name = import_file( f, root )
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
            providers = ( ) ):
    """Everything the command line asked for: ( entries, modules )."""
    from .expr import matches

    # One pool of files, so that "a bare name must resolve to exactly one" is
    # checked across every provider at once rather than inside each.
    files = candidates( root, exclude )
    for p in providers:
        files += [ f for f in p.files() if f not in files ]
    files = sorted( set( files ), key = str )

    specs = parse_pattern( pattern, files, root )
    wanted = sorted( { f for matched, _ in specs for f in matched }, key = str )

    mine = [ f for f in wanted if f.suffix == ".py" and _declares_entries( f ) ]
    all_entries, modules = collect( mine, root )
    for p in providers:
        all_entries += p.collect( specs )

    # The `::name` that chose a whole-file entry is not consumed here: a
    # provider that runs files hands it to the binary as its own filter.
    from .providers import selector_of
    selectors = { }

    out = [ ]
    for e in all_entries:
        for matched, name_glob in specs:
            if e.file not in matched:
                continue
            # A provider whose entries are whole files consumes the `::name`
            # itself; filtering on it here would reject the entry for not
            # being called after one of its own cases.
            consumed = e.provider is not None and e.provider.whole_files
            if name_glob is not None and not consumed and \
               not fnmatch.fnmatchcase( e.name, name_glob ):
                continue
            if kinds and e.kind not in kinds:
                continue
            if bulk_only and not e.traits[ "bulk" ]:
                continue
            if entry_tags and not matches( entry_tags, e.tags ):
                continue
            out.append( e )
            if e.provider is not None:
                selectors[ e.name ] = selector_of( specs, e.file )
            break
    return out, modules, selectors
