"""A Catch2 binary: built during preparation, its cases listed by the binary, one entry per case.
"""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .base import _read, FRAMEWORK, NONE, Outcome, RunContext, Runner


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
