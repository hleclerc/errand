"""What every runner is: the `Runner` interface, how well it fits a file ( `Level` ), what it is
handed to run an entry ( `RunContext` ) and what it hands back ( `Outcome` ).
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from ..entries import Entry


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
# Where errand's C++ headers are ( `#include <errand/require.hpp>` ): `{errand_include}` in a build line.
INCLUDE = Path( __file__ ).resolve().parents[ 1 ] / "include"

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
    exit   : int | None = None                    # the tool's exit code, when it ended badly: its stderr is said


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
    # The environment's own names for its tools ( `Env( tools = { "python": "python3.12" } )` ).
    tools   : dict = field( default_factory = dict )
    # `-j N` on a single run whose runner takes it ( `Runner.jobs` ): the tool's own parallelism.
    jobs    : int = 1


# The usual names of a tool, in the order they are looked for when the environment gives none.
TOOLS = {
    "cmake": ( "cmake", "cmake3" ),
    "ctest": ( "ctest", "ctest3" ),
}


class Runner:
    """The parts every runner shares. Subclasses fill in `suitability`,
    `collect` and `run`."""

    name = "runner"

    # The highest level `suitability` can answer.
    level = NONE

    # An entry runner answers `x::y`; a file runner ( `python`, `executable` )
    # answers a bare `x`, and is never asked to claim anything.
    takes_entries = True

    # True when an entry IS a whole file: one run of the runner's tool ( ADR 0011 ). Every runner but
    # errand's own entries. A `::name` then belongs to the tool, not to the entry: the core must not
    # filter entries by it.
    whole_files = True
    # ...and the runner hands it on as the tool's own filter ( a pytest node id, a Catch2 test spec,
    # a `cargo test` filter ). Without it ( a script ), `file::x` is refused.
    takes_selector = False

    # Whether `run` hands `ctx.jobs` to its tool ( pytest-xdist's `-n`, `--test-threads` ): then `-j N`
    # on a single run is the tool's parallelism. Without it, `-j` only runs several runs at once.
    jobs = False

    # Where its tool writes, other than the run's output directory ( ADR 0006 zones ): path -> "back"
    # ( brought back after every command ) or "build" ( stays over there, never overwritten by a
    # push ). Given per instance: `Pytest( zones = { "/htmlcov": "back" } )`.
    zones: dict = { }

    # The environment's tools, for what a runner does before it has a `RunContext` ( listing a
    # crate's targets ): set where the environment is known, the same as `RunContext.tools`.
    place_tools: dict = { }

    # The project root, set when the project's configuration has been read:
    # what a runner's own relative paths ( `dirs`, `manifest` ) are relative to.
    root = None

    def suitability( self, path: Path ) -> Level:
        return NONE

    def collect( self, specs ) -> list:
        """One entry per file: a run of the runner's tool, which does the selecting itself."""
        return [ self.entry( name = Path( f ).name, file = Path( f ), key = str( f ) )
                 for f in self.files_of( specs ) ]

    def tool( self, name: str, ctx: RunContext | None = None ) -> list:
        """The argv that starts tool `name` in this place: the environment's own name for it when it
        gives one, else the interpreter errand runs on for `python`, else the first of its usual
        names found on the PATH ( `TOOLS` ), else the name itself, for the error to say."""
        given = ( ctx.tools if ctx is not None else self.place_tools ).get( name )
        if given:
            return shlex.split( given ) if isinstance( given, str ) else [ str( a ) for a in given ]
        if name == "python":
            return [ sys.executable ]
        for candidate in TOOLS.get( name, ( name, ) ):
            if shutil.which( candidate ):
                return [ candidate ]
        return [ name ]

    def fill_tools( self, line: str, ctx: RunContext ) -> str:
        """`{python}`, `{cmake}`… in a command line written by the user, for the tools the environment
        names, and `{errand_include}`, where `errand/require.hpp` is ( ADR 0014 ): nothing else in
        braces is touched ( `${CC}`, `{a,b}` )."""
        if "{errand_include}" in line:
            line = line.replace( "{errand_include}", shlex.quote( str( INCLUDE ) ) )
        for name in { "python", *ctx.tools }:
            if "{" + name + "}" in line:
                line = line.replace( "{" + name + "}", shlex.join( self.tool( name, ctx ) ) )
        return line

    def build_lines( self, entries, ctx: RunContext ) -> list:
        """What `prepare` will build, as lines a person reads: shown before it runs. None by default."""
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

    def entry( self, *, name, file, key = None, tags = ( ), line = 0, params = None ):
        """One entry of this runner's.

        `params` are ordinary errand parameters, so a suite that can be asked
        to run two ways -- a device, a precision -- is a MATRIX like any other:
        `--device cpu,cuda` is two runs, two directories, two rows.
        """
        made = Entry( name, list( tags ), dict( params or { } ), { },
                      file, line, f"{self.name}:{file}" )
        made.runner = self
        made.key = key if key is not None else name
        return made

    def shell( self, argv, ctx: RunContext, *, cwd = None, timeout = None, live_stderr = False ):
        """Run something and bring back its output, whatever it did. `live_stderr`: its stderr is also
        written to this process's as it comes -- into the run's `stderr.txt`, kept even if all ends
        badly -- and `shown` says so: what is printed afterwards is `shown_output( got )`."""
        extra = { "ERRAND_BUILD_DIR": str( ctx.build_dir ) } if ctx.build_dir else { }
        env = { "PYTHONFAULTHANDLER": "1", **os.environ, **extra, **ctx.env }
        argv = [ str( a ) for a in argv ]
        if not live_stderr:
            return subprocess.run( argv, cwd = str( cwd or ctx.root ), env = env, capture_output = True,
                                   text = True, timeout = timeout )
        import threading
        child = subprocess.Popen( argv, cwd = str( cwd or ctx.root ), env = env, stdout = subprocess.PIPE,
                                  stderr = subprocess.PIPE, text = True, errors = "replace" )
        err = [ ]

        def pump():
            for line in child.stderr:
                err.append( line )
                sys.stderr.write( line )
                sys.stderr.flush()

        t = threading.Thread( target = pump, daemon = True )
        t.start()
        try:
            out = child.stdout.read()
            child.wait( timeout = timeout )
        except subprocess.TimeoutExpired:
            child.kill()
            raise
        t.join()
        got = subprocess.CompletedProcess( argv, child.returncode, out, "".join( err ) )
        got.shown = True
        return got

    @staticmethod
    def shown_output( got ) -> str:
        """What of a `shell`'s output is still to print: its stderr was shown as it came, with `live_stderr`."""
        return got.stdout if getattr( got, "shown", False ) else got.stdout + got.stderr

    @staticmethod
    def exit_of( got ):
        """The exit code a failure is told by, None for a success."""
        return got.returncode or None


def selector_of( specs, path: Path ) -> str | None:
    """The `::name` that selected `path`, for a runner that runs whole files --
    none for `::*`, which asks for everything and filters nothing."""
    for matched, name_glob in specs:
        if path in matched and name_glob and name_glob != "*":
            return name_glob
    return None


def junit_outcome( report: Path ):
    """A JUnit XML report, as pytest, ctest, cargo-nextest and many others write it: counts by status,
    the failed cases by name, the first failure's message. None when there is no report to read."""
    if not report.exists():
        return None
    try:
        root = ET.parse( report ).getroot()
    except ET.ParseError:
        return None
    cases = list( root.iter( "testcase" ) )
    if not cases:
        return None
    counts, failed, first, seconds = { "passed": 0, "failed": 0, "skipped": 0 }, [ ], None, 0.0
    for case in cases:
        seconds += float( case.get( "time" ) or 0 )
        bad = case.find( "failure" ) if case.find( "failure" ) is not None else case.find( "error" )
        if bad is not None:
            counts[ "failed" ] += 1
            failed.append( case.get( "name", "?" ) )
            if first is None:
                first = ( bad.get( "message" ) or bad.text or "" ).strip()[ : 500 ]
        elif case.find( "skipped" ) is not None:
            counts[ "skipped" ] += 1
        else:
            counts[ "passed" ] += 1
    results = { **counts, "seconds": round( seconds, 3 ) }
    if failed:
        shown = ", ".join( failed[ : 10 ] ) + ( f" and {len( failed ) - 10} more" if len( failed ) > 10 else "" )
        return Outcome( status = "FAIL", results = results,
                        error = f"{len( failed )} failed: {shown}" + ( f" -- {first}" if first else "" ) )
    if counts[ "skipped" ] and not counts[ "passed" ]:
        skipped = next( c for c in cases if c.find( "skipped" ) is not None ).find( "skipped" )
        return Outcome( status = "SKIP", results = results,
                        error = ( skipped.get( "message" ) or skipped.text or "skipped" ).strip()[ : 500 ] )
    return Outcome( status = "PASS", results = results )
