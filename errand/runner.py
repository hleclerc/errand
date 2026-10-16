"""What runs a target: the runners.

What a target means is read from the command line alone, never guessed from the
project's layout:

* `x::y` -- globs allowed on both sides -- goes to an **entry runner**: errand's
  own entries, pytest, Catch2, cargo. Which one takes a file is asked of each
  ( `suitability` ), and the one that fits it best takes it; two at the same,
  highest level is an error naming them, never a coin toss. `-r NAME` picks one
  and asks nothing.
* anything else goes to a **file runner**: a `.py` to `python`, the
  interpreter of the place; anything else to `executable`, run as it is -- a
  file, or a command found on the place's own `PATH` ( `make`, `cmake`,
  `pytest` ).

An entry runner knows three things about a kind of file: whether it is the one
to run it, what entries the file holds, and how to run one:

    suitability( path ) -> how well this runner fits the file ( a `Level` )
    collect( specs )    -> [ Entry ], over the files this runner was given
    prepare( entries )  -> once, before any of them runs ( a build )
    run( entry, ctx )   -> Outcome

`errand.runners` is a dict, name -> runner, filled with the ones that come with
errand; a project adds its own instances under names of its own, which `-r`
then picks, or `replace`s a built-in one by a configured one of the same kind.

The runners for existing suites -- pytest, Catch2, cargo -- each keep everything
that makes it itself: its own collection rules, its own assertions, its own
idea of what a test is. Their vocabulary is translated rather than replaced: a
`@pytest.mark.slow` is an entry tag, so `-e '!slow'` filters it with the same
expression language `-t` uses on environments; a Catch2 `[tag]` likewise; and a
framework's own benchmark numbers land in `result.yaml` beside everyone else's.
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
from enum import IntEnum
from pathlib import Path

from .entries import Entry, TRAITS
from .targets import name_matches


class Level( IntEnum ):
    """How well an entry runner fits a file. The highest wins; a tie at the top is an error."""
    NONE      = 0    # not this runner's
    FALLBACK  = 1    # kept for runners of a project's own that rank themselves low
    LANGUAGE  = 2
    FRAMEWORK = 3    # a suite of a framework it adopts: pytest, Catch2, cargo
    ERRAND    = 4    # a file declaring errand's own entries


NONE, FALLBACK, LANGUAGE, FRAMEWORK, ERRAND = Level.NONE, Level.FALLBACK, Level.LANGUAGE, \
                                              Level.FRAMEWORK, Level.ERRAND

# A file declares errand's own work when it IMPORTS errand, not when it merely
# says the word. A comment explaining that a suite is collected by errand, a
# docstring, a string in somebody's fixture -- all of those mention it, and none
# of them should be imported and executed on the strength of that.
MARKER = re.compile( r"^[ \t]*(from[ \t]+errand(\.[\w.]+)?[ \t]+import|import[ \t]+errand\b)",
                     re.MULTILINE )


def _read( path: Path, limit = 1 << 20 ) -> str:
    try:
        with open( path, errors = "ignore" ) as f:
            return f.read( limit )
    except OSError:
        return ""


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
    # The `::name` part of the target that selected this entry, unconsumed: a
    # runner whose entries are whole files hands it to the file as a filter.
    selector: str | None = None
    # This environment's own build directory ( `build/<env>/` ): `{build_dir}`
    # in a runner's build command and binary path, `ERRAND_BUILD_DIR` for them.
    build_dir: Path | None = None
    # What was written after the target: its own arguments, the declared
    # parameters among them as they were resolved for this run.
    args    : list = field( default_factory = list )
    # What a plain command runs under: a memory ceiling, a lower priority.
    wrap    : list = field( default_factory = list )


class Runner:
    """The parts every runner shares. Subclasses fill in `suitability`,
    `collect` and `run`."""

    name = "runner"

    # The highest level `suitability` can answer.
    level = NONE

    # An entry runner answers `x::y`; a file runner ( `python`, `executable` )
    # answers a bare `x`, and is never asked to claim anything.
    takes_entries = True

    # True when an entry IS a whole file -- a script, or a compiled suite whose
    # cases cannot be enumerated before it is built. A `::name` then belongs to
    # the file, not to the entry: the core must not filter entries by it.
    whole_files = False
    # ...and the runner hands it on as the file's own filter ( Catch2 takes a
    # case name, `cargo test` a test name ). Without it, `file::x` is refused.
    takes_selector = False

    # The project root, set when the project's configuration has been read:
    # what a runner's own relative paths ( `dirs`, `manifest` ) are relative to.
    root = None

    # True when what a file holds can only be listed once it is built: then
    # `prepare` runs BEFORE `collect`, during the preparation, in the place --
    # and `collect` finds the build where `context.build_dir` says.
    builds_to_collect = False
    # What the preparation is being done with: the root, this environment's
    # build directory. Set by discovery before `prepare` and `collect`.
    context = None

    def suitability( self, path: Path ) -> Level:
        return NONE

    def collect( self, specs ) -> list:
        return [ ]

    def prepare( self, entries, ctx: RunContext ):
        """Once, before any of `entries` runs. -> None, or why it cannot.

        Building belongs here and not in `run`: a suite is built once, not once
        per file, and `-j` would otherwise have several processes writing the
        same binary at the same time.
        """
        return None

    def run( self, entry, ctx: RunContext ) -> Outcome:
        raise NotImplementedError

    def __repr__( self ):
        return f"<{type( self ).__name__} runner>"

    # -- helpers ------------------------------------------------------------

    def _under_root( self, rel ) -> Path:
        rel = Path( rel )
        return rel if rel.is_absolute() else Path( self.root or "." ) / rel

    def _inside( self, path: Path, dirs ) -> bool:
        """Whether `path` is under one of `dirs` -- every path, when there are none."""
        if dirs is None:
            return True
        real = os.path.realpath( path )
        return any( ( real + os.sep ).startswith( os.path.realpath( self._under_root( d ) ) + os.sep )
                    for d in dirs )

    def files_of( self, specs ):
        return list( dict.fromkeys( f for matched, _ in specs for f in matched ) )

    def entry( self, *, name, file, key = None, tags = ( ), traits = None, line = 0,
               params = None ):
        """One entry of this runner's.

        `params` are ordinary errand parameters, so a suite that can be asked
        to run two ways -- a device, a precision -- is a MATRIX like any other:
        `--device cpu,cuda` is two runs, two directories, two rows.
        """
        made = Entry( name, list( tags ), dict( params or { } ),
                      dict( TRAITS, **( traits or { } ) ), { },
                      file, line, f"{self.name}:{file}" )
        made.runner = self
        made.key = key if key is not None else name
        return made

    def shell( self, argv, ctx: RunContext, *, cwd = None, timeout = None ):
        """Run something and bring back its output, whatever it did."""
        extra = { "ERRAND_BUILD_DIR": str( ctx.build_dir ) } if ctx.build_dir else { }
        return subprocess.run( [ str( a ) for a in argv ], cwd = str( cwd or ctx.root ),
                               env = { **os.environ, **extra, **ctx.env }, capture_output = True,
                               text = True, timeout = timeout )

    def matching( self, specs, path: Path, names ):
        """The names of `path` that the specs asked for."""
        out = [ ]
        for matched, name_glob in specs:
            if path not in matched:
                continue
            if name_glob is None:
                return list( names )
            out += [ n for n in names if name_matches( name_glob, n ) ]
        return out


def selector_of( specs, path: Path ) -> str | None:
    """The `::name` that selected `path`, for a runner that runs whole files --
    none for `::*`, which asks for everything and filters nothing."""
    for matched, name_glob in specs:
        if path in matched and name_glob and name_glob != "*":
            return name_glob
    return None


# ── errand's own entries ─────────────────────────────────────────────────────

class Errand( Runner ):
    """Files that declare entries with errand's own guard ( `if test( … ):` ).

    Collected and run by the core itself -- by importing the file, then
    re-importing it once per entry -- so this runner only says which files are
    its own. It is in the list like the others so that it can be seen, ranked,
    and taken out.
    """

    name = "errand"
    level = ERRAND
    in_process = True

    # The project's own files mention errand by nature, and re-executing one as
    # if it declared work would register everything it declares a second time.
    NOT_WORK = "errand-*.py"

    def suitability( self, path ):
        if path.suffix != ".py" or fnmatch.fnmatchcase( path.name, self.NOT_WORK ):
            return NONE
        here = Path( __file__ ).resolve().parent       # errand's own sources import errand
        if here in Path( os.path.realpath( path ) ).parents:
            return NONE
        return ERRAND if MARKER.search( _read( path ) ) else NONE


# ── pytest ───────────────────────────────────────────────────────────────────

COLLECT_TO = "ERRAND_COLLECT_TO"


class Pytest( Runner ):
    """An existing pytest suite, one entry per test.

    Which files are pytest's is pytest's convention -- `test_*.py` and
    `*_test.py`, under `dirs` when they are given -- and what is in them is
    asked of pytest itself rather than guessed: its rules are its own, and
    reimplementing them is how a runner starts quietly disagreeing with the
    tool it wraps. Nothing is built, so collecting is cheap.
    """

    name = "pytest"
    level = FRAMEWORK

    def __init__( self, dirs = None, patterns = ( "test_*.py", "*_test.py" ), args = ( ),
                  python = None, install = "auto", spec = "pytest" ):
        self.dirs     = None if dirs is None else list( dirs )
        self.patterns = list( patterns )
        self.args     = list( args )
        self.python   = python or sys.executable
        self.install  = install          # "auto" | True | False
        self.spec     = spec
        self._items   = { }

    def suitability( self, path ):
        if path.suffix != ".py" or not any( fnmatch.fnmatchcase( path.name, p ) for p in self.patterns ):
            return NONE
        return FRAMEWORK if self._inside( path, self.dirs ) else NONE

    # -- having a pytest at all ---------------------------------------------

    def _has_pytest( self ):
        return subprocess.run( [ self.python, "-c", "import pytest" ],
                               capture_output = True ).returncode == 0

    def _own_environment( self ):
        """Is the target interpreter something other than the system's?

        Installing into a micromamba environment, a venv or a container is what
        errand does for every other requirement. Installing into the system
        python is not errand's to do -- it is shared with everything else on
        the machine, and it may well refuse.
        """
        got = subprocess.run(
            [ self.python, "-c", "import sys; print( sys.prefix != sys.base_prefix )" ],
            capture_output = True, text = True )
        if got.stdout.strip() == "True":
            return True
        return bool( os.environ.get( "CONDA_PREFIX" ) or os.environ.get( "VIRTUAL_ENV" ) )

    def ensure_pytest( self, echo = "say" ):
        """-> None when there is a pytest to ask, else why there is not."""
        if self._has_pytest():
            return None
        wanted = self.install is True or ( self.install == "auto" and self._own_environment() )
        if not wanted:
            return ( f"{self.python} has no pytest, and it is the system interpreter: "
                     f"installing into it is not errand's to do.\n"
                     f"  install it yourself, point the runner at another interpreter "
                     f"( Pytest( python = ... ) ), or say Pytest( install = True )" )
        # Never silent: installing something into somebody's environment is
        # an act, and it is said out loud even when nobody asked to watch.
        note = f"  installing {self.spec} into {self.python}"
        print( note, file = sys.stderr ) if echo == "say" else ( echo and echo( note ) )
        got = subprocess.run( [ self.python, "-m", "pip", "install", self.spec ],
                              capture_output = True, text = True )
        if got.returncode or not self._has_pytest():
            return f"could not install {self.spec}:\n{( got.stdout + got.stderr )[ -2000 : ]}"
        return None

    def prepare( self, entries, ctx: RunContext ):
        return self.ensure_pytest( )

    # -- collecting ---------------------------------------------------------

    def items( self, files ):
        """[ { id, file, name, marks } ] of `files`, as pytest itself sees them."""
        key = tuple( sorted( str( f ) for f in files ) )
        if key in self._items:
            return self._items[ key ]
        self._items[ key ] = found = [ ]
        if not files:
            return found
        why = self.ensure_pytest( )
        if why is not None:
            # An empty suite looks exactly like a suite that passed, so the
            # reason is said out loud even though nobody asked for a status.
            print( f"  pytest: {why}", file = sys.stderr )
            return found
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path( tmp ) / "items.json"
            env = { **os.environ, COLLECT_TO: str( listing ),
                    "PYTHONPATH": os.pathsep.join(
                        [ str( Path( __file__ ).resolve().parent.parent ),
                          *filter( None, [ os.environ.get( "PYTHONPATH" ) ] ) ] ) }
            got = subprocess.run(
                [ self.python, "-m", "pytest", "--collect-only", "-q",
                  "-p", "errand._pytest_plugin", *self.args, *key ],
                capture_output = True, text = True, env = env, timeout = 300,
                cwd = str( self.root or "." ) )
            if listing.exists():
                found += json.loads( listing.read_text() )
            elif got.returncode not in ( 0, 5 ):
                # No listing and a real failure: say so rather than report an
                # empty suite, which looks like success.
                found.append( { "id": "<collection failed>", "file": key[ 0 ],
                                "name": "<collection failed>", "marks": [ ],
                                "error": ( got.stdout + got.stderr )[ -2000 : ] } )
        return found

    def collect( self, specs ):
        by_file = { }
        for item in self.items( self.files_of( specs ) ):
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
                            f"--junitxml={report}", *self.args, *ctx.args ], ctx )
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

class Catch2( Runner ):
    """A Catch2 suite: one entry per test case.

    Built during the preparation, in the place it will run, and then asked for
    its own cases -- the binary knows them, and nothing else does. A file whose
    build fails, or whose binary cannot list itself, costs its own row.
    """

    name = "catch2"
    level = FRAMEWORK
    builds_to_collect = True

    SOURCES = ( ".cpp", ".cc", ".cxx", ".c++" )

    def __init__( self, dir = None, pattern = "test_*.cpp", build = None,
                  binary = None, args = ( ) ):
        self.dir     = None if dir is None else Path( dir )
        self.pattern = pattern
        self.build   = build                     # e.g. "make -C tests"
        self.binary  = binary                    # e.g. "{build_dir}/{stem}"; default: beside the source
        self.args    = list( args )
        self.broken  = [ ]                       # [ ( path, why ) ] from the last collect

    def suitability( self, path ):
        if path.suffix not in self.SOURCES or not fnmatch.fnmatchcase( path.name, self.pattern ):
            return NONE
        if not self._inside( path, None if self.dir is None else [ self.dir ] ):
            return NONE
        return FRAMEWORK if "catch" in _read( path ).lower() else NONE

    def collect( self, specs ):
        ctx = self.context
        build_dir = ctx.build_dir if ctx is not None else None
        root = Path( ctx.root ) if ctx is not None else Path( self.root or "." )
        self.broken = [ ]
        out = [ ]
        for path in self.files_of( specs ):
            binary = root / self._binary_for( path, build_dir )
            if not binary.exists():
                self.broken.append( ( path, f"no binary at {binary}: tell Catch2 how to build it "
                                            f"( build = \"make -C cpp\" ) or where it lands "
                                            f"( binary = \"{{build_dir}}/{{stem}}\" )" ) )
                continue
            cases, why = _catch2_cases( binary )
            if why:
                self.broken.append( ( path, why ) )
                continue
            wanted = self.matching( specs, path, [ name for name, _ in cases ] )
            for name, tags in cases:
                if name in wanted:
                    out.append( self.entry( name = name, file = path,
                                            key = json.dumps( { "source": str( path ), "name": name } ),
                                            tags = [ "catch2", *tags ] ) )
        return out

    def _binary_for( self, path: Path, build_dir = None ) -> Path:
        if self.binary:
            return Path( str( self.binary ).format( stem = path.stem, dir = self.dir or path.parent,
                                                    build_dir = build_dir or "build" ) )
        return path.with_suffix( "" )

    def prepare( self, entries, ctx: RunContext ):
        if not self.build:
            return None
        import shlex
        # `{build_dir}` and nothing else is filled in: a build line is full of
        # braces that are somebody else's ( `${CC}`, `{a,b}` ).
        line = self.build.replace( "{build_dir}", str( ctx.build_dir or "build" ) )
        built = self.shell( shlex.split( line ), ctx )
        if built.returncode:
            return f"the build failed:\n{( built.stdout + built.stderr )[ -3000 : ]}"
        return None

    def run( self, entry, ctx: RunContext ) -> Outcome:
        text = ""
        key = json.loads( entry.key )
        binary = ctx.root / self._binary_for( Path( key[ "source" ] ), ctx.build_dir )
        if not binary.exists():
            return Outcome( status = "FAIL", output = text,
                            error = f"no binary at {binary}: tell Catch2 how to build it "
                                    f"( build = \"make -C cpp\" ) or where it lands "
                                    f"( binary = \"build/{{stem}}\" )" )

        report = ctx.out_dir / "catch2.xml"
        argv = [ binary, "--reporter", f"xml::out={report}", *self.args, *ctx.args,
                 _catch2_spec( key[ "name" ] ) ]
        got = self.shell( argv, ctx )
        text += got.stdout + got.stderr

        outcome = _from_catch2( report )
        if outcome is None:
            return Outcome( status = "PASS" if got.returncode == 0 else "FAIL",
                            error = None if got.returncode == 0 else f"exit {got.returncode}",
                            output = text )
        outcome.output = text
        return outcome


def _catch2_cases( binary: Path ):
    """-> ( [ ( name, [ tags ] ) ], None ), or ( [ ], why ): what the binary says it holds."""
    try:
        got = subprocess.run( [ str( binary ), "--list-tests", "--reporter", "xml" ],
                              capture_output = True, text = True, timeout = 120 )
    except OSError as err:
        return [ ], f"{binary} could not be started: {err}"
    try:
        listing = ET.fromstring( got.stdout )
        return [ ( case.findtext( "Name", "" ).strip(),
                   re.findall( r"\[([^\]]+)\]", case.findtext( "Tags", "" ) ) )
                 for case in listing.iter( "TestCase" ) ], None
    except ET.ParseError:
        pass
    # Catch2 v2 has no xml listing: one name per line.
    got = subprocess.run( [ str( binary ), "--list-test-names-only" ],
                          capture_output = True, text = True, timeout = 120 )
    if got.returncode < 0 or ( got.returncode and not got.stdout.strip() ):
        return [ ], f"{binary} would not list its cases:\n{( got.stdout + got.stderr )[ -1000 : ]}"
    return [ ( line.strip(), [ ] ) for line in got.stdout.splitlines() if line.strip() ], None


def _catch2_spec( name: str ) -> str:
    """One case, by its exact name: the characters Catch2's test specs give a
    meaning to are escaped, so a case called `a, b` or `x[2]` is that case."""
    return "".join( "\\" + c if c in ',[]*~"\\' else c for c in name )


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

class Cargo( Runner ):
    """A Rust crate: one entry per test target.

    `cargo metadata` knows the targets without compiling any of them, which is
    what makes collecting cheap. A
    target's file is its source root ( `src/lib.rs`, `tests/foo.rs` ), and the
    crate is the nearest `Cargo.toml` above it. Naming a single test still
    works: the `::name` part becomes the filter `cargo test` takes after `--`.
    """

    name = "cargo"
    level = FRAMEWORK
    whole_files = True
    takes_selector = True

    def __init__( self, manifest = None, args = ( ), release = False ):
        self.manifest = None if manifest is None else Path( manifest )
        self.args     = list( args )
        self.release  = release
        self._targets = { }

    def _manifest_of( self, path: Path ):
        if self.manifest is not None:
            return self._under_root( self.manifest ).resolve()
        top = Path( os.path.realpath( self.root or "/" ) )
        here = Path( os.path.realpath( path ) ).parent
        while True:
            if ( here / "Cargo.toml" ).is_file():
                return here / "Cargo.toml"
            if here == top or here.parent == here:
                return None
            here = here.parent

    def targets( self, manifest: Path ):
        if manifest in self._targets:
            return self._targets[ manifest ]
        self._targets[ manifest ] = found = { }
        if shutil.which( "cargo" ) is None or not manifest.is_file():
            return found
        got = subprocess.run( [ "cargo", "metadata", "--no-deps", "--format-version", "1",
                                "--manifest-path", str( manifest ) ],
                              capture_output = True, text = True, timeout = 300 )
        if got.returncode:
            return found
        for package in json.loads( got.stdout ).get( "packages", [ ] ):
            for target in package.get( "targets", [ ] ):
                if target.get( "test" ):
                    found[ os.path.realpath( target[ "src_path" ] ) ] = {
                        "name": target[ "name" ], "src": target[ "src_path" ],
                        "kind": ( target.get( "kind" ) or [ "lib" ] )[ 0 ],
                        "manifest": str( manifest ) }
        return found

    def suitability( self, path ):
        if path.suffix != ".rs":
            return NONE
        manifest = self._manifest_of( path )
        if manifest is None:
            return NONE
        return FRAMEWORK if os.path.realpath( path ) in self.targets( manifest ) else NONE

    def collect( self, specs ):
        out = [ ]
        for path in self.files_of( specs ):
            manifest = self._manifest_of( path )
            target = self.targets( manifest ).get( os.path.realpath( path ) ) if manifest else None
            if target is not None:
                out.append( self.entry( name = target[ "name" ], file = path,
                                        key = json.dumps( target ),
                                        tags = [ "cargo", target[ "kind" ] ] ) )
        return out

    def run( self, entry, ctx: RunContext ) -> Outcome:
        target = json.loads( entry.key )
        which = { "lib": [ "--lib" ], "bin": [ "--bin", target[ "name" ] ] }.get(
            target[ "kind" ], [ "--test", target[ "name" ] ] )
        argv = [ "cargo", "test", "--manifest-path", target[ "manifest" ], *which,
                 *( [ "--release" ] if self.release else [ ] ), *self.args ]
        if ctx.selector or ctx.args:
            argv += [ "--", *( [ ctx.selector ] if ctx.selector else [ ] ), *ctx.args ]
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


# ── a file, run as it is ────────────────────────────────────────────────────
#
# A bare target -- no `::` -- is one run of one thing: a script, an executable, a
# command. Its output is the run's, streamed as it comes, and its exit code the
# status. `ERRAND_OUT_DIR` is set only when an output directory was asked for
# ( `-o` ): nobody is handed a directory they did not want.

INTERPRETERS = ( "python", "python3" )

# What a run of a plain command may write numbers to, and what it gets as
# `ERRAND_OUT_DIR` when one was asked for: set by the core in `RunContext.env`.
OUT_DIR = "ERRAND_OUT_DIR"


class _WholeFile( Runner ):
    whole_files   = True
    takes_entries = False

    def command( self, key: str ) -> list:
        raise NotImplementedError

    def collect( self, specs ):
        return [ self.entry( name = Path( key ).name, file = Path( key ), key = str( key ) )
                 for key in self.files_of( specs ) ]

    def run( self, entry, ctx: RunContext ) -> Outcome:
        argv = [ *ctx.wrap, *( str( a ) for a in self.command( entry.key ) ), *ctx.args ]
        # A directory only when one was asked for, which `ctx.env` says.
        env = { **{ k: v for k, v in os.environ.items() if k != OUT_DIR },
                **( { "ERRAND_BUILD_DIR": str( ctx.build_dir ) } if ctx.build_dir else { } ),
                **ctx.env }
        try:
            child = subprocess.Popen( argv, cwd = str( ctx.root ), env = env, text = True,
                                      stdout = subprocess.PIPE, stderr = subprocess.STDOUT,
                                      errors = "replace" )
        except OSError as err:
            return Outcome( status = "FAIL", error = f"{argv[ 0 ]}: {err.strerror or err}" )
        # Line by line, as it comes: a build or a long computation that says
        # nothing until it is over is one nobody can follow -- here, in
        # `output.txt`, or on the screen.
        for line in child.stdout:
            sys.stdout.write( line )
            sys.stdout.flush()
        code = child.wait()
        if code == SKIP_CODE:
            return Outcome( status = "SKIP", error = "exit 77" )
        return Outcome( status = "PASS" if code == 0 else "FAIL",
                        error = None if code == 0 else f"exit {code}" )


# The exit code that means "this does not apply here", as automake and ctest have it.
SKIP_CODE = 77


class Python( _WholeFile ):
    """A `.py`, run by the interpreter of the place it runs in."""

    name = "python"

    def command( self, key ):
        return [ sys.executable, key ]


class Executable( _WholeFile ):
    """Anything else, run as it is: a file of the project ( `./bench`, a script
    with a shebang ), or a command of the place ( `make`, `cmake`, `pytest` ).
    A first word that names an interpreter is the interpreter of the place."""

    name = "executable"

    def command( self, key ):
        if key in INTERPRETERS:
            return [ sys.executable ]
        path = Path( key )
        if path.parent != Path( "." ) or self._under_root( path ).is_file():
            return [ str( self._under_root( path ).resolve() ) ]
        return [ key ]


class Runners( dict ):
    """`errand.runners`: name -> runner.

    `errand.runners[ "bench" ] = errand.Pytest( … )` adds an instance `-r bench`
    picks; `replace` puts a configured runner in place of the built-in one of
    its kind, rather than beside it, where the two would tie over every file."""

    def __setitem__( self, name, runner ):
        if not isinstance( runner, Runner ):
            raise TypeError( f"runners[ {name!r} ] must be a runner, not {type( runner ).__name__}" )
        runner.name = name
        super().__setitem__( name, runner )

    def update( self, other = ( ), **kw ):
        for k, v in dict( other, **kw ).items():
            self[ k ] = v

    def replace( self, runner ):
        """-> runner, under the name of the kind it replaces."""
        kind = type( runner )
        names = [ n for n, r in self.items() if type( r ) is kind ]
        for n in names:
            del self[ n ]
        self[ names[ 0 ] if names else type( runner ).name ] = runner
        return runner

    def entry_runners( self ):
        return [ r for r in self.values() if r.takes_entries ]


def defaults( ) -> dict:
    """The runners that come with errand, by name."""
    return { r.name: r for r in ( Errand(), Pytest(), Catch2(), Cargo(), Python(), Executable() ) }
