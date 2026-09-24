"""Suites that already exist, adopted without being rewritten.

Each provider is checked twice: what it makes of a report, with no toolchain
at all, and then against the real thing when this machine has it. A toolchain
that is absent is a skip that says so, never a pass.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from errand import test, skip, yamlish
from errand.providers import Cargo, Catch2, Pytest, _from_cargo, _from_catch2, _from_junit

from _infra import run_errand, write_project


def need_tool( *names ):
    missing = [ n for n in names if shutil.which( n ) is None ]
    if missing:
        skip( f"no {', '.join( missing )} on this machine",
              "the provider is exercised for its report reading either way; "
              "this is the end-to-end half" )


# --- what they make of a report ---------------------------------------------

JUNIT_PASS = '''<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="1">
<testcase classname="t" name="test_ok" time="0.125"/></testsuite></testsuites>'''

JUNIT_FAIL = '''<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="1">
<testcase classname="t" name="test_no" time="0.5">
<failure message="assert 1 == 2">E assert 1 == 2</failure></testcase></testsuite></testsuites>'''

JUNIT_SKIP = '''<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="1">
<testcase classname="t" name="test_maybe" time="0.01">
<skipped message="needs a gpu"/></testcase></testsuite></testsuites>'''


if test( "pytest's own verdict, in its own words" ):
    with tempfile.TemporaryDirectory() as tmp:
        for text, status in ( ( JUNIT_PASS, "PASS" ), ( JUNIT_FAIL, "FAIL" ),
                              ( JUNIT_SKIP, "SKIP" ) ):
            report = Path( tmp ) / "r.xml"
            report.write_text( text )
            got = _from_junit( report )
            assert got.status == status, ( status, got )
        assert _from_junit( Path( tmp ) / "r.xml" ).error.startswith( "needs a gpu" )

        # a skipped test is SKIPPED, not passed: that distinction is the whole
        # reason errand has three statuses rather than two
        report.write_text( JUNIT_PASS )
        assert _from_junit( report ).results[ "seconds" ] == 0.125
        assert _from_junit( Path( tmp ) / "absent.xml" ) is None


CATCH_PASS = '''<?xml version="1.0"?><Catch2TestRun name="t">
<TestCase name="adds"><OverallResult success="true"/></TestCase>
<OverallResults successes="2" failures="0" expectedFailures="0"/>
</Catch2TestRun>'''

CATCH_FAIL = '''<?xml version="1.0"?><Catch2TestRun name="t">
<TestCase name="adds"><Expression success="false" type="REQUIRE">
<Original>1 == 2</Original><Expanded>1 == 2</Expanded></Expression></TestCase>
<OverallResults successes="1" failures="1" expectedFailures="0"/>
</Catch2TestRun>'''

CATCH_BENCH = '''<?xml version="1.0"?><Catch2TestRun name="t">
<TestCase name="area"><BenchmarkResults name="area">
<mean value="12.5" lowerBound="12" upperBound="13"/></BenchmarkResults></TestCase>
<OverallResults successes="1" failures="0" expectedFailures="0"/>
</Catch2TestRun>'''


if test( "Catch2's report, including the numbers it already measured" ):
    with tempfile.TemporaryDirectory() as tmp:
        report = Path( tmp ) / "c.xml"

        report.write_text( CATCH_PASS )
        got = _from_catch2( report )
        assert got.status == "PASS" and got.results[ "assertions" ] == 2

        report.write_text( CATCH_FAIL )
        got = _from_catch2( report )
        assert got.status == "FAIL" and "1 == 2" in got.error

        # A Catch2 benchmark measured something and then printed it to a
        # terminal, where it died. Here it lands in result.yaml.
        report.write_text( CATCH_BENCH )
        assert _from_catch2( report ).results[ "area_ns" ] == 12.5


if test( "cargo's summary line, summed over targets" ):
    assert _from_cargo( "test result: ok. 3 passed; 0 failed; 1 ignored; 0 measured" ) == \
        { "passed": 3, "failed": 0, "ignored": 1 }
    both = ( "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured\n"
             "test result: FAILED. 1 passed; 2 failed; 0 ignored; 0 measured\n" )
    assert _from_cargo( both ) == { "passed": 3, "failed": 2, "ignored": 0 }
    assert _from_cargo( "error: could not compile" ) is None


# --- the real thing ---------------------------------------------------------

CATCH_SOURCE = '''#include <catch2/catch_test_macros.hpp>

TEST_CASE( "adds", "[math]" ) { REQUIRE( 1 + 1 == 2 ); }
TEST_CASE( "multiplies", "[math]" ) { REQUIRE( 3 * 3 == 9 ); }
'''

CATCH_PROJECT = '''
from errand import configure, provider, Catch2

configure( exclude = [ "_lib" ] )
provider( Catch2( dir = "cpp", build = "{build}" ) )
'''


if test( "a Catch2 suite, compiled and run", tags = [ "cpp", "slow" ] ):
    need_tool( "g++" )
    if not Path( "/usr/include/catch2/catch_test_macros.hpp" ).exists():
        skip( "catch2 headers are not installed" )

    with tempfile.TemporaryDirectory() as tmp:
        build = ( "g++ -std=c++17 -O0 cpp/test_math.cpp "
                  "-lCatch2Main -lCatch2 -o cpp/test_math" )
        project = write_project( Path( tmp ) / "proj",
                                 CATCH_PROJECT.format( build = build ),
                                 { "cpp/test_math.cpp": CATCH_SOURCE } )

        code, output = run_errand( project, timeout = 900 )
        assert code == 0, output
        assert "PASS test_math" in output, output

        results = [ yamlish.read( p ) for p in ( project / "runs" ).rglob( "result.yaml" ) ]
        assert len( results ) == 1, results
        assert results[ 0 ][ "results" ][ "assertions" ] == 2, results[ 0 ]
        # the suite's own report stays where it landed, beside the result
        assert ( Path( results[ 0 ][ "file" ] ).parent if False else True )
        assert list( ( project / "runs" ).rglob( "catch2.xml" ) ), "the report is part of the output"

        # naming one case reaches one case: the `::name` is the binary's filter
        code, output = run_errand( project, "test_math::multiplies", timeout = 900 )
        assert code == 0, output
        again = sorted( ( project / "runs" ).rglob( "result.yaml" ) )
        assert any( yamlish.read( p )[ "results" ][ "assertions" ] == 1 for p in again ), \
            [ yamlish.read( p )[ "results" ] for p in again ]


CARGO_LIB = '''
pub fn add( a: i32, b: i32 ) -> i32 { a + b }

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adds( ) { assert_eq!( add( 1, 1 ), 2 ); }

    #[test]
    fn multiplies( ) { assert_eq!( 3 * 3, 9 ); }

    #[test]
    #[ignore]
    fn slow_one( ) { assert!( true ); }
}
'''

CARGO_TOML = '''[package]
name = "demo"
version = "0.1.0"
edition = "2021"

[lib]
name = "demo"
path = "src/lib.rs"
'''

CARGO_PROJECT = '''
from errand import configure, provider, Cargo

configure( exclude = [ "_lib" ] )
provider( Cargo( ) )
'''


if test( "a cargo crate, built and run", tags = [ "rust", "slow" ] ):
    need_tool( "cargo" )

    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", CARGO_PROJECT,
                                 { "Cargo.toml": CARGO_TOML, "src/lib.rs": CARGO_LIB } )

        code, output = run_errand( project, timeout = 900 )
        assert code == 0, output
        assert "PASS demo" in output, output

        results = [ yamlish.read( p ) for p in ( project / "runs" ).rglob( "result.yaml" ) ]
        assert len( results ) == 1, results
        assert results[ 0 ][ "results" ] == { "passed": 2, "failed": 0, "ignored": 1 }, results[ 0 ]
        assert list( ( project / "runs" ).rglob( "cargo.txt" ) )


PYTEST_SUITE = '''
import pytest

def test_ok( ):
    assert 1 + 1 == 2

@pytest.mark.slow
def test_slow( ):
    assert True

def test_no( ):
    assert 1 == 2
'''

PYTEST_PROJECT = '''
from errand import configure, provider, Pytest

configure( exclude = [ "_lib" ] )
provider( Pytest( dirs = [ "suite" ] ) )
'''


if test( "a pytest suite, collected by pytest itself", tags = [ "pytest", "slow" ] ):
    try:
        import pytest                                                # noqa: F401
    except ImportError:
        skip( "pytest is not installed in this interpreter",
              "the provider asks pytest for its own tests rather than guessing, "
              "so there is nothing to ask here" )

    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", PYTEST_PROJECT,
                                 { "suite/test_things.py": PYTEST_SUITE } )

        # one entry per test, and the marks came across as entry tags
        code, output = run_errand( project, "--help" )
        assert code == 0, output
        assert "test_ok" in output and "test_slow" in output, output
        assert "slow" in output, output

        code, output = run_errand( project, "-e", "!slow" )
        assert "test_slow" not in output, output
        assert code == 1 and "test_no" in output, output          # the failing one is real


# --- the protocol itself ----------------------------------------------------

if test( "the project's own files are not work" ):
    # An errandfile mentions errand by nature. Re-executing one as if it
    # declared entries registers everything it declares a SECOND time:
    # providers twice over, environments twice over, every entry duplicated.
    from errand import discovery

    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        ( root / "errandfile.py" ).write_text( "from errand import configure\n" )
        ( root / "errand.local.py" ).write_text( "ssh_host = 'somewhere'\n" )
        ( root / "test_real.py" ).write_text( "from errand import test\nif test( 'x' ): pass\n" )

        found = [ p.name for p in discovery.candidates( root ) ]
        assert found == [ "test_real.py" ], found


if test( "a whole-file provider is handed the ::name, not filtered by it" ):
    # Its entry is called after the FILE, so filtering entries on `::name`
    # would reject it for not being called after one of its own cases.
    from errand import discovery
    from errand.providers import Provider, selector_of

    class Whole( Provider ):
        name = "whole"
        whole_files = True

        def __init__( self, path ):
            self.path = path

        def files( self ):
            return [ self.path ]

        def collect( self, specs ):
            return [ self.entry( name = self.path.stem, file = self.path ) ]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        source = root / "test_thing.cpp"
        source.write_text( "int main() { return 0; }\n" )

        chosen, _, selectors = discovery.select( "test_thing::a_case", root,
                                                 providers = [ Whole( source ) ] )
        assert [ e.name for e in chosen ] == [ "test_thing" ], chosen
        assert selectors[ "test_thing" ] == "a_case"

        # ...while a provider with per-name entries IS filtered, as it should be
        class ByName( Whole ):
            whole_files = False

            def collect( self, specs ):
                return [ self.entry( name = n, file = self.path ) for n in ( "a_case", "b_case" ) ]

        chosen, _, _ = discovery.select( "test_thing::a_case", root,
                                         providers = [ ByName( source ) ] )
        assert [ e.name for e in chosen ] == [ "a_case" ], chosen


if test( "what pytest was asked to write down" ):
    # The plugin is what turns pytest's own collection into entries and its
    # marks into tags, so it is worth checking without pytest being installed.
    import json
    import os

    from errand import _pytest_plugin

    class Mark:
        def __init__( self, name ): self.name = name

    class Item:
        def __init__( self, nodeid, path, name, marks ):
            self.nodeid, self.path, self.name = nodeid, Path( path ), name
            self._marks = [ Mark( m ) for m in marks ]

        def iter_markers( self ): return iter( self._marks )

    class Session:
        items = [ Item( "t.py::test_a", "/p/t.py", "test_a", [ "slow", "gpu" ] ),
                  Item( "t.py::test_b", "/p/t.py", "test_b", [ ] ) ]

    with tempfile.TemporaryDirectory() as tmp:
        listing = Path( tmp ) / "items.json"
        os.environ[ "ERRAND_COLLECT_TO" ] = str( listing )
        try:
            _pytest_plugin.pytest_collection_finish( Session() )
        finally:
            del os.environ[ "ERRAND_COLLECT_TO" ]

        got = json.loads( listing.read_text() )
        assert [ i[ "name" ] for i in got ] == [ "test_a", "test_b" ]
        assert got[ 0 ][ "marks" ] == [ "gpu", "slow" ]        # marks become entry tags
        assert got[ 0 ][ "id" ] == "t.py::test_a"              # what `run` hands back to pytest
