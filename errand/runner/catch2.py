"""A Catch2 binary: built during the preparation, run once per source, the `::name` handed to it as a
test spec.
"""
from __future__ import annotations

import fnmatch
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..streams import ended
from .base import _read, FRAMEWORK, NONE, Outcome, RunContext, Runner


class Catch2( Runner ):
    """A Catch2 suite: a source is one run of its binary.

    Built during the preparation, in the place it will run. What the binary
    holds is its own business: `x.cpp::add*`, `x.cpp::[math]~[slow]` are
    Catch2 test specs, handed to it as they are written.
    """

    name = "catch2"
    level = FRAMEWORK
    whole_files = True
    takes_selector = True

    SOURCES = ( ".cpp", ".cc", ".cxx", ".c++" )

    def __init__( self, dir = None, pattern = "test_*.cpp", build = None,
                  binary = None, args = ( ), zones = None ):
        self.dir     = None if dir is None else Path( dir )
        self.pattern = pattern
        self.build   = build                     # e.g. "make -C tests", or several, in order
        self.binary  = binary                    # e.g. "{build_dir}/{stem}"; default: beside the source
        self.args    = list( args )
        self.zones   = dict( zones or { } )

    def suitability( self, path ):
        if path.suffix not in self.SOURCES or not fnmatch.fnmatchcase( path.name, self.pattern ):
            return NONE
        if not self._inside( path, None if self.dir is None else [ self.dir ] ):
            return NONE
        return FRAMEWORK if "catch" in _read( path ).lower() else NONE

    def _binary_for( self, path: Path, build_dir = None ) -> Path:
        if self.binary:
            return Path( str( self.binary ).format( stem = path.stem, dir = self.dir or path.parent,
                                                    build_dir = build_dir or "build" ) )
        return path.with_suffix( "" )

    def build_lines( self, entries, ctx: RunContext ) -> list:
        """The build, as it will run: `{build_dir}` filled in, and nothing else -- a build line is
        full of braces that are somebody else's ( `${CC}`, `{a,b}` )."""
        lines = [ self.build ] if isinstance( self.build, str ) else list( self.build or ( ) )
        return [ self.fill_tools( l.replace( "{build_dir}", str( ctx.build_dir or "build" ) ), ctx ) for l in lines ]

    def prepare( self, entries, ctx: RunContext ):
        import shlex
        for line in self.build_lines( entries, ctx ):
            built = self.shell( shlex.split( line ), ctx )
            if built.returncode:
                return f"the build failed ( {line} ):\n{( built.stdout + built.stderr )[ -3000 : ]}"
        return None

    def run( self, entry, ctx: RunContext ) -> Outcome:
        binary = ctx.root / self._binary_for( Path( entry.key ), ctx.build_dir )
        if not binary.exists():
            return Outcome( status = "FAIL",
                            error = f"no binary at {binary}: tell Catch2 how to build it "
                                    f"( build = \"make -C cpp\" ) or where it lands "
                                    f"( binary = \"{{build_dir}}/{{stem}}\" )" )
        report = ctx.out_dir / "catch2.xml"
        argv = [ binary, "--reporter", f"xml::out={report}", *self.args,
                 *( [ ctx.selector ] if ctx.selector else [ ] ), *ctx.args ]
        got = self.shell( argv, ctx, live_stderr = True )
        text = self.shown_output( got )
        outcome = _from_catch2( report )
        if outcome is None:
            return Outcome( status = "PASS" if got.returncode == 0 else "FAIL",
                            error = None if got.returncode == 0 else ended( got.returncode ),
                            output = text, exit = self.exit_of( got ) )
        outcome.output = text
        if got.returncode < 0:          # a crash the report does not say
            outcome.status, outcome.error, outcome.exit = "FAIL", ended( got.returncode ), got.returncode
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
    cases = list( root.iter( "TestCase" ) )
    failed_cases = [ c.get( "name", "?" ) for c in cases
                     if ( c.find( "OverallResult" ) is not None and c.find( "OverallResult" ).get( "success" ) == "false" ) ]
    results[ "passed" ] = len( cases ) - len( failed_cases )
    results[ "failed" ] = len( failed_cases )

    totals = root.find( ".//OverallResults" )
    if totals is None:
        totals = root.find( ".//OverallResultsCases" )
    failed = int( totals.get( "failures", 0 ) ) if totals is not None else 0
    passed = int( totals.get( "successes", 0 ) ) if totals is not None else 0
    results[ "assertions" ] = passed + failed

    if failed or failed_cases:
        first = next( ( e for e in root.iter( "Expression" ) if e.get( "success" ) == "false" ),
                      None )
        detail = ""
        if first is not None:
            original = first.findtext( "Original", "" ).strip()
            expanded = first.findtext( "Expanded", "" ).strip()
            detail = f"{original} -- expanded: {expanded}"
        which = f" in {', '.join( failed_cases[ : 10 ] )}" if failed_cases else ""
        return Outcome( status = "FAIL", results = results,
                        error = f"{failed} assertion(s) failed{which}. {detail}".strip() )
    return Outcome( status = "PASS", results = results )
