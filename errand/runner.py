"""What runs a file: the runners.

A runner knows three things about a kind of file: whether it is the one to run
it, what entries the file holds, and how to run one into a given output
directory. Everything downstream -- the output directory, the result file, the
summaries, the matrices over environments, the queue, the remote
repatriation -- applies unchanged, whoever ran it.

    suitability( path ) -> how well this runner fits the file ( a `Level` )
    collect( specs )    -> [ Entry ], over the files this runner was given
    prepare( entries )  -> once, before any of them runs ( a build )
    run( entry, ctx )   -> Outcome

`errand.runners` is the list that applies, filled with the ones that come with
errand; a project edits it with plain list operations, or `replace`s a built-in
runner by a configured one of the same kind.

**A file goes to the runner that fits it best**, and the order of the list
never decides: a file that imports errand is errand's even when it is called
`test_*.py`, a pytest file is pytest's before it is a python script, a python
script is python's before it is an executable. Two runners at the same,
highest level is an error that names them, never a coin toss.

**Only what declares itself as work is found by looking.** `ERRAND` and
`FRAMEWORK` files are picked up by a glob, a directory or a bare `errand run`;
`LANGUAGE` and `FALLBACK` ones only when named, path in full -- otherwise
`errand run '**/*.py'` would execute every module of a library as a script.

**Whether a file is one entry or several is the runner's to say**, since only it
knows whether its ecosystem can enumerate without running: pytest and cargo
can, a script cannot, and a compiled suite cannot before it is built. A runner
whose entries are whole files either hands a `::name` to the file as its own
filter ( `takes_selector` ), or refuses one.

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
    """How well a runner fits a file. The highest wins; a tie at the top is an error."""
    NONE      = 0    # not this runner's
    FALLBACK  = 1    # something that can be run at all: an executable
    LANGUAGE  = 2    # a language it knows how to run: a python or a shell script
    FRAMEWORK = 3    # a suite of a framework it adopts: pytest, Catch2, cargo
    ERRAND    = 4    # a file declaring errand's own entries

    @property
    def discoverable( self ):
        """Found by a glob, a directory or a bare run, not only when named."""
        return self >= Level.FRAMEWORK


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


class Runner:
    """The parts every runner shares. Subclasses fill in `suitability`,
    `collect` and `run`."""

    name = "runner"

    # The highest level `suitability` can answer. Discovery walks the whole
    # tree asking only the runners that could make a file discoverable.
    level = NONE

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
    """The `::name` that selected `path`, for a runner that runs whole files."""
    for matched, name_glob in specs:
        if path in matched and name_glob:
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


# ── a file, run as it is ─────────────────────────────────────────────────────
#
# Scripts and executables are one entry each, the whole file, and are run only
# when named: nothing about them says they are work rather than a module, a
# tool or a library. Their output is the run's, the exit code its status, and
# `ERRAND_OUT_DIR` the directory anything else they write should go to.

class _WholeFile( Runner ):
    whole_files = True

    def command( self, path: Path ) -> list:
        raise NotImplementedError

    def collect( self, specs ):
        return [ self.entry( name = path.name, file = path, key = str( path ) )
                 for path in self.files_of( specs ) ]

    def run( self, entry, ctx: RunContext ) -> Outcome:
        got = self.shell( [ *self.command( Path( entry.key ) ), *ctx.args ],
                          RunContext( root = ctx.root, out_dir = ctx.out_dir, params = ctx.params,
                                      env = { **ctx.env, "ERRAND_OUT_DIR": str( ctx.out_dir ) } ) )
        return Outcome( status = "PASS" if got.returncode == 0 else "FAIL",
                        error = None if got.returncode == 0 else f"exit {got.returncode}",
                        output = got.stdout + got.stderr )


class Python( _WholeFile ):
    """A python script, run by the interpreter of the place it runs in."""

    name = "python"
    level = LANGUAGE

    def suitability( self, path ):
        return LANGUAGE if path.suffix == ".py" and path.is_file() else NONE

    def command( self, path ):
        return [ sys.executable, path ]


class Shell( _WholeFile ):
    """A shell script: `sh` for a `.sh`, `bash` for a `.bash`."""

    name = "shell"
    level = LANGUAGE

    def suitability( self, path ):
        return LANGUAGE if path.suffix in ( ".sh", ".bash" ) and path.is_file() else NONE

    def command( self, path ):
        return [ "bash" if path.suffix == ".bash" else "sh", path ]


class Executable( _WholeFile ):
    """Anything that can be executed, run as it is."""

    name = "executable"
    level = FALLBACK

    def suitability( self, path ):
        return FALLBACK if path.is_file() and os.access( path, os.X_OK ) else NONE

    def command( self, path ):
        return [ path.resolve() ]


class Runners( list ):
    """`errand.runners`: a list, plus `replace` for the commonest edit."""

    def replace( self, runner ):
        """Put `runner` in place of the runners of its kind -- a configured
        `Catch2( dir = …, build = … )` instead of the default one -- rather than
        beside them, where the two would tie over every file. -> runner."""
        kind = type( runner )
        self[ : ] = [ r for r in self if type( r ) is not kind ] + [ runner ]
        return runner


def defaults( ) -> list:
    """The runners that come with errand, in no order that matters."""
    return [ Errand(), Pytest(), Catch2(), Cargo(), Python(), Shell(), Executable() ]
