"""Work that is not a Python call site.

A provider knows two things: what entries it has, and how to run one into a
given output directory. Everything downstream -- the output directory, the
result file, the summaries, the matrices over environments, the queue, the
remote repatriation -- applies unchanged, which is the whole point of adopting
an existing suite rather than rewriting it.

    files( )            the files it owns, for spec disambiguation
    collect( specs )    -> [ Entry ]
    run( entry, ctx )   -> Outcome

Three constraints shape every implementation:

* `collect()` ALSO RUNS LOCALLY, even when the work is about to go to another
  machine -- that is what makes the paths to fetch back predictable. So a
  provider may not enumerate its entries by compiling them. Either the
  granularity is one entry per file, with the `::name` part handed to the
  binary as its own filter, or it asks something that already knows
  ( `cargo metadata`, `pytest --collect-only` ) without building anything.
* Spec disambiguation is global: "a bare file name must resolve to exactly one
  file" is checked across every provider's `files()` at once.
* Output capture is the provider's business. The core only receives text.

The three that come with errand -- pytest, Catch2, cargo -- each keep everything that makes it itself -- its own collection rules, its own
assertions, its own idea of what a test is. What adopting it buys is everything
that happens around the run: an output directory, a result file, the summaries,
matrices over environments, the queue, remote repatriation.

The vocabulary is translated rather than replaced. A `@pytest.mark.slow` is an
entry tag, so `-e '!slow'` filters it with the same expression language `-t`
uses on environments; a Catch2 `[tag]` likewise; and a framework's own
benchmark numbers land in `result.yaml` beside everyone else's.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .entries import Entry, TRAITS


@dataclass
class Outcome:
    status : str                                  # PASS | FAIL | SKIP
    error  : str | None = None
    results: dict = field( default_factory = dict )
    output : str = ""


@dataclass
class RunContext:
    root    : Path
    out_dir : Path
    params  : dict = field( default_factory = dict )
    env     : dict = field( default_factory = dict )
    # The `::name` part of the spec that selected this entry, unconsumed: a
    # provider whose entries are whole files hands it to the binary as a filter.
    selector: str | None = None


class Provider:
    """The parts every provider shares. Subclasses fill in `files`/`collect`/`run`."""

    name = "provider"

    # True when an entry IS a whole file -- a compiled suite, whose cases
    # cannot be enumerated without building it. The `::name` of a spec then
    # belongs to the binary, not to the entry, so the core must not filter
    # entries by it: `test_math::multiplies` would match nothing, the entry
    # being called `test_math`.
    whole_files = False

    def files( self ) -> list:
        return [ ]

    def collect( self, specs ) -> list:
        return [ ]

    def run( self, entry, ctx: RunContext ) -> Outcome:
        raise NotImplementedError

    # -- helpers ------------------------------------------------------------

    def entry( self, *, name, file, key = None, tags = ( ), traits = None, line = 0 ):
        made = Entry( name, list( tags ), { }, dict( TRAITS, **( traits or { } ) ), { },
                      file, line, f"{self.name}:{file}" )
        made.provider = self
        made.key = key if key is not None else name
        return made

    def shell( self, argv, ctx: RunContext, *, cwd = None, timeout = None ):
        """Run something and bring back its output, whatever it did."""
        return subprocess.run( [ str( a ) for a in argv ], cwd = str( cwd or ctx.root ),
                               env = { **os.environ, **ctx.env }, capture_output = True,
                               text = True, timeout = timeout )

    def matching( self, specs, path: Path, names ):
        """The names of `path` that the specs asked for.

        `None` means the file was selected whole; a provider with per-name
        entries filters on the returned list.
        """
        out = [ ]
        for matched, name_glob in specs:
            if path not in matched:
                continue
            if name_glob is None:
                return list( names )
            out += [ n for n in names if fnmatch.fnmatchcase( n, name_glob ) ]
        return out


def selector_of( specs, path: Path ) -> str | None:
    """The `::name` that selected `path`, for a provider that runs whole files."""
    for matched, name_glob in specs:
        if path in matched and name_glob:
            return name_glob
    return None



# ── pytest ───────────────────────────────────────────────────────────────────

COLLECT_TO = "ERRAND_COLLECT_TO"


class Pytest( Provider ):
    """An existing pytest suite, one entry per test.

    Collection asks pytest itself rather than guessing: its rules are its own,
    and reimplementing them is how a runner starts quietly disagreeing with the
    tool it wraps. Nothing is built, so this is cheap enough to do on the side
    that predicts the paths.
    """

    name = "pytest"

    def __init__( self, dirs = ( "tests", ), root = None, args = ( ), python = None ):
        self.dirs   = list( dirs )
        self.root   = Path( root ) if root else Path( "." )
        self.args   = list( args )
        self.python = python or sys.executable
        self._items = None

    # -- collecting ---------------------------------------------------------

    def _where( self ):
        return [ str( self.root / d ) for d in self.dirs ]

    def items( self ):
        """[ { id, file, name, marks } ], as pytest itself sees them."""
        if self._items is not None:
            return self._items
        self._items = [ ]
        if not any( Path( w ).exists() for w in self._where() ):
            return self._items
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path( tmp ) / "items.json"
            env = { **os.environ, COLLECT_TO: str( listing ),
                    "PYTHONPATH": os.pathsep.join(
                        [ str( Path( __file__ ).resolve().parent.parent ),
                          *filter( None, [ os.environ.get( "PYTHONPATH" ) ] ) ] ) }
            got = subprocess.run(
                [ self.python, "-m", "pytest", "--collect-only", "-q",
                  "-p", "errand._pytest_plugin", *self.args, *self._where() ],
                capture_output = True, text = True, env = env, timeout = 300 )
            if listing.exists():
                self._items = json.loads( listing.read_text() )
            elif got.returncode not in ( 0, 5 ):
                # No listing and a real failure: say so rather than report an
                # empty suite, which looks like success.
                self._items = [ { "id": "<collection failed>", "file": self._where()[ 0 ],
                                  "name": "<collection failed>", "marks": [ ],
                                  "error": ( got.stdout + got.stderr )[ -2000 : ] } ]
        return self._items

    def files( self ):
        return sorted( { Path( i[ "file" ] ).resolve() for i in self.items() } )

    def collect( self, specs ):
        by_file = { }
        for item in self.items():
            by_file.setdefault( Path( item[ "file" ] ).resolve(), [ ] ).append( item )

        out = [ ]
        for path, items in by_file.items():
            wanted = self.matching( specs, path, [ i[ "name" ] for i in items ] )
            for item in items:
                if item[ "name" ] in wanted:
                    out.append( self.entry( name = item[ "name" ], file = path,
                                            key = item[ "id" ], tags = item.get( "marks" ) or [ ] ) )
        return out

    # -- running ------------------------------------------------------------

    def run( self, entry, ctx: RunContext ) -> Outcome:
        report = ctx.out_dir / "pytest.xml"
        got = self.shell( [ self.python, "-m", "pytest", entry.key, "-q",
                            f"--junitxml={report}", *self.args ], ctx )
        outcome = _from_junit( report )
        if outcome is None:
            return Outcome( status = "PASS" if got.returncode == 0 else "FAIL",
                            error = None if got.returncode == 0 else f"exit {got.returncode}",
                            output = got.stdout + got.stderr )
        outcome.output = got.stdout + got.stderr
        return outcome


def _from_junit( report: Path ):
    """pytest's own verdict, in its own words -- and the file stays behind."""
    if not report.exists():
        return None
    try:
        root = ET.parse( report ).getroot()
    except ET.ParseError:
        return None
    case = root.find( ".//testcase" )
    if case is None:
        return None
    results = { }
    if case.get( "time" ):
        results[ "seconds" ] = float( case.get( "time" ) )
    for kind, status in ( ( "failure", "FAIL" ), ( "error", "FAIL" ), ( "skipped", "SKIP" ) ):
        found = case.find( kind )
        if found is not None:
            return Outcome( status = status,
                            error = ( found.get( "message" ) or found.text or "" ).strip()[ : 500 ],
                            results = results )
    return Outcome( status = "PASS", results = results )


# ── Catch2 ───────────────────────────────────────────────────────────────────

class Catch2( Provider ):
    """A Catch2 suite: one entry per source file.

    Per file, not per test case, because the entries have to be known on THIS
    side of an ssh hop -- before anything is compiled -- for the paths to fetch
    back to be worked out in advance. A `::name` in the pattern is handed to the
    binary as its own filter, so naming one case still reaches one case.
    """

    name = "catch2"
    whole_files = True

    def __init__( self, dir = "tests", pattern = "test_*.cpp", build = None,
                  binary = None, args = ( ) ):
        self.dir     = Path( dir )
        self.pattern = pattern
        self.build   = build                     # e.g. "make -C tests"
        self.binary  = binary                    # e.g. "build/{stem}"; default: dir/stem
        self.args    = list( args )

    def files( self ):
        return sorted( p.resolve() for p in self.dir.glob( self.pattern ) )

    def collect( self, specs ):
        return [ self.entry( name = path.stem, file = path, key = str( path ),
                             tags = [ "catch2" ] )
                 for path in self.files()
                 if any( path in matched for matched, _ in specs ) ]

    def _binary_for( self, path: Path ) -> Path:
        if self.binary:
            return Path( str( self.binary ).format( stem = path.stem, dir = self.dir ) )
        return self.dir / path.stem

    def run( self, entry, ctx: RunContext ) -> Outcome:
        text = ""
        if self.build:
            built = self.shell( self.build.split(), ctx )
            text += built.stdout + built.stderr
            if built.returncode:
                return Outcome( status = "FAIL", error = "the build failed", output = text )

        binary = ctx.root / self._binary_for( Path( entry.key ) )
        if not binary.exists():
            return Outcome( status = "FAIL", output = text,
                            error = f"no binary at {binary}: give Catch2 a `build=` or a `binary=`" )

        report = ctx.out_dir / "catch2.xml"
        argv = [ binary, "--reporter", f"xml::out={report}", *self.args ]
        if ctx.selector:
            argv.append( ctx.selector )          # Catch2 takes a name or a [tag]
        got = self.shell( argv, ctx )
        text += got.stdout + got.stderr

        outcome = _from_catch2( report )
        if outcome is None:
            return Outcome( status = "PASS" if got.returncode == 0 else "FAIL",
                            error = None if got.returncode == 0 else f"exit {got.returncode}",
                            output = text )
        outcome.output = text
        return outcome


def _from_catch2( report: Path ):
    if not report.exists():
        return None
    try:
        root = ET.parse( report ).getroot()
    except ET.ParseError:
        return None

    results = { }
    # Catch2's own benchmarks were measured and then printed to a terminal and
    # forgotten; here they land in result.yaml with everyone else's.
    for mark in root.iter( "BenchmarkResults" ):
        mean = mark.find( "mean" )
        if mean is not None and mean.get( "value" ):
            results[ f"{mark.get( 'name' )}_ns" ] = float( mean.get( "value" ) )

    # `or` on an Element is a trap: one with no children is FALSY, so the
    # totals of a passing run -- a single self-closing tag -- would be thrown
    # away and read as zero assertions.
    totals = root.find( ".//OverallResults" )
    if totals is None:
        totals = root.find( ".//OverallResultsCases" )
    failed = int( totals.get( "failures", 0 ) ) if totals is not None else 0
    passed = int( totals.get( "successes", 0 ) ) if totals is not None else 0
    results[ "assertions" ] = passed + failed

    if failed:
        first = next( ( e for e in root.iter( "Expression" ) if e.get( "success" ) == "false" ),
                      None )
        detail = ""
        if first is not None:
            original = first.findtext( "Original", "" ).strip()
            expanded = first.findtext( "Expanded", "" ).strip()
            detail = f"{original} -- expanded: {expanded}"
        return Outcome( status = "FAIL", results = results,
                        error = f"{failed} assertion(s) failed. {detail}".strip() )
    return Outcome( status = "PASS", results = results )


# ── cargo ────────────────────────────────────────────────────────────────────

class Cargo( Provider ):
    """A Rust crate: one entry per test target.

    `cargo metadata` knows the targets without compiling any of them, which is
    what makes this cheap enough to run on the side that predicts the paths.
    Naming a single test still works: the `::name` part becomes the filter
    `cargo test` takes after `--`.
    """

    name = "cargo"

    def __init__( self, manifest = "Cargo.toml", args = ( ), release = False ):
        self.manifest = Path( manifest )
        self.args     = list( args )
        self.release  = release
        self._targets = None

    def targets( self ):
        if self._targets is not None:
            return self._targets
        self._targets = [ ]
        if not self.manifest.exists() or shutil.which( "cargo" ) is None:
            return self._targets
        got = subprocess.run( [ "cargo", "metadata", "--no-deps", "--format-version", "1",
                                "--manifest-path", str( self.manifest ) ],
                              capture_output = True, text = True, timeout = 300 )
        if got.returncode:
            return self._targets
        for package in json.loads( got.stdout ).get( "packages", [ ] ):
            for target in package.get( "targets", [ ] ):
                if target.get( "test" ):
                    self._targets.append( { "name": target[ "name" ],
                                            "src": target[ "src_path" ],
                                            "kind": ( target.get( "kind" ) or [ "lib" ] )[ 0 ] } )
        return self._targets

    def files( self ):
        return sorted( { Path( t[ "src" ] ).resolve() for t in self.targets() } )

    def collect( self, specs ):
        out = [ ]
        for target in self.targets():
            path = Path( target[ "src" ] ).resolve()
            if any( path in matched for matched, _ in specs ):
                out.append( self.entry( name = target[ "name" ], file = path,
                                        key = json.dumps( target ),
                                        tags = [ "cargo", target[ "kind" ] ] ) )
        return out

    def run( self, entry, ctx: RunContext ) -> Outcome:
        target = json.loads( entry.key )
        which = { "lib": [ "--lib" ], "bin": [ "--bin", target[ "name" ] ] }.get(
            target[ "kind" ], [ "--test", target[ "name" ] ] )
        argv = [ "cargo", "test", "--manifest-path", str( self.manifest ), *which,
                 *( [ "--release" ] if self.release else [ ] ), *self.args ]
        if ctx.selector:
            argv += [ "--", ctx.selector ]
        got = self.shell( argv, ctx )
        text = got.stdout + got.stderr

        ( ctx.out_dir / "cargo.txt" ).write_text( text )
        counts = _from_cargo( text )
        if counts is None:
            return Outcome( status = "PASS" if got.returncode == 0 else "FAIL",
                            error = None if got.returncode == 0 else f"exit {got.returncode}",
                            output = text )
        status = "FAIL" if counts[ "failed" ] else (
            "SKIP" if counts[ "passed" ] == 0 and counts[ "ignored" ] else "PASS" )
        return Outcome( status = status, results = counts, output = text,
                        error = f"{counts[ 'failed' ]} test(s) failed" if counts[ "failed" ] else None )


def _from_cargo( text: str ):
    """`test result: ok. 3 passed; 0 failed; 1 ignored; …`, summed over targets."""
    found = re.findall(
        r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", text )
    if not found:
        return None
    return { "passed" : sum( int( a ) for a, _, _ in found ),
             "failed" : sum( int( b ) for _, b, _ in found ),
             "ignored": sum( int( c ) for _, _, c in found ) }
