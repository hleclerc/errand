"""Suites that already exist, adopted without being rewritten.

Each runner is checked twice: what it makes of a report, with no toolchain
at all, and then against the real thing when this machine has it. A toolchain
that is absent is a skip that says so, never a pass.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from errand import test, skip, yamlish
from errand import runner as P
from errand.runner import Cargo, Catch2, Pytest
from errand.runner.cargo import _from_cargo
from errand.runner.catch2 import _from_catch2
from errand.runner import junit_outcome as _from_junit

from _infra import run_errand, write_project


def need_tool( *names ):
    missing = [ n for n in names if shutil.which( n ) is None ]
    if missing:
        skip( f"no {', '.join( missing )} on this machine",
              "the runner is exercised for its report reading either way; "
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

        # A file is one run: its cases are counted, and the failed ones named.
        report.write_text( JUNIT_PASS.replace( "</testsuite>", JUNIT_FAIL.split( 'tests="1">' )[ 1 ].split( "</testsuite>" )[ 0 ]
                                               + JUNIT_SKIP.split( 'tests="1">' )[ 1 ].split( "</testsuite>" )[ 0 ] + "</testsuite>" ) )
        got = _from_junit( report )
        assert got.status == "FAIL" and got.results[ "passed" ] == 1 and got.results[ "failed" ] == 1 \
               and got.results[ "skipped" ] == 1, got
        assert got.error.startswith( "1 failed: test_no -- assert 1 == 2" ), got.error


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
import errand

errand.configure( exclude = [ "_lib" ] )
errand.runners.replace( errand.Catch2( dir = "cpp", build = "{build}" ) )
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

        code, output = run_errand( project, "run", "-o", "**::*", timeout = 900 )
        assert code == 0 and "PASS test_math.cpp" in output, output

        results = [ yamlish.read( p ) for p in ( project / "errand-outputs" / "runs" ).rglob( "result.yaml" ) ]
        assert len( results ) == 1, "one run for the binary"
        assert results[ 0 ][ "results" ][ "passed" ] == 2 and results[ 0 ][ "results" ][ "assertions" ] == 2, results
        assert list( ( project / "errand-outputs" / "runs" ).rglob( "catch2.xml" ) ), "the report is part of the output"

        # naming one case hands Catch2 the spec
        code, output = run_errand( project, "run", "-o", "cpp/test_math.cpp::multiplies", timeout = 900 )
        assert code == 0, output


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
import errand

errand.configure( exclude = [ "_lib" ] )
errand.runners.replace( errand.Cargo( ) )
'''


if test( "a cargo crate, built and run", tags = [ "rust", "slow" ] ):
    need_tool( "cargo" )

    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", CARGO_PROJECT,
                                 { "Cargo.toml": CARGO_TOML, "src/lib.rs": CARGO_LIB } )

        code, output = run_errand( project, "run", "-o", "**::*", timeout = 900 )
        assert code == 0, output
        assert "PASS demo" in output, output
        # compiled during the preparation, before anything ran, into the environment's own directory
        assert output.index( "build ( cargo ): cargo test --no-run" ) < output.index( "PASS demo" ), output
        assert ( project / "build" / "default" / "target" ).is_dir() and not ( project / "target" ).exists()

        results = [ yamlish.read( p ) for p in ( project / "errand-outputs" / "runs" ).rglob( "result.yaml" ) ]
        assert len( results ) == 1, results
        assert results[ 0 ][ "results" ] == { "passed": 2, "failed": 0, "ignored": 1 }, results[ 0 ]
        assert list( ( project / "errand-outputs" / "runs" ).rglob( "cargo.txt" ) )


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
import errand

errand.configure( exclude = [ "_lib", ".venv" ] )

# A venv of this project's own. `install = "auto"` -- the default -- installs
# pytest into it because it is not the system interpreter.
errand.runners.replace( errand.Pytest( dirs = [ "suite" ], python = ".venv/bin/python" ) )
'''


if test( "a pytest file is one run of pytest, which does the selecting", tags = [ "pytest", "slow" ] ):
    # A venv of its own, deliberately WITHOUT pytest: installing what a
    # runner needs into an environment that is errand's to install into is
    # part of what a runner does.
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", PYTEST_PROJECT,
                                 { "suite/test_things.py": PYTEST_SUITE } )
        venv = project / ".venv"
        made = subprocess.run( [ sys.executable, "-m", "venv", str( venv ) ],
                               capture_output = True, text = True )
        if made.returncode:
            skip( "no venv could be made here", made.stderr.strip()[ : 300 ] )
        assert subprocess.run( [ venv / "bin" / "python", "-c", "import pytest" ],
                               capture_output = True ).returncode != 0

        code, output = run_errand( project, "run", "--no-queue", "**::*", "-m", "not slow", timeout = 900 )
        if "could not install" in output:
            skip( "pip could not reach an index from here",
                  "the runner installs what it needs; this machine cannot fetch it" )
        # it said what it was doing to somebody's environment
        assert "installing pytest" in output, output
        # one run for the file, its marks filtered by pytest itself, the failing one named
        assert code == 1 and "test_things.py" in output, output
        assert "1 failed: test_no" in output and "assert 1 == 2" in output, "pytest's own words, not `exit 1`"

        code, output = run_errand( project, "run", "--no-queue", "suite/test_things.py::test_ok" )
        assert code == 0, output
        code, output = run_errand( project, "run", "--no-queue", "suite/test_things.py::test_[os]*" )
        assert code == 0, output                                  # a pattern, matched on what pytest collects
        code, output = run_errand( project, "run", "--no-queue", "suite/test_things.py::test_nope*" )
        assert code == 1 and "matches no test" in output and "test_ok" in output, output
        code, output = run_errand( project, "run", "--no-queue", "-e", "!slow", "**::*" )
        assert code == 1 and "-m \"not slow\"" in output, "-e is errand's entries' filter"


if test( "the system interpreter is not errand's to install into", tags = [ "pytest" ] ):
    # It is shared with everything else on the machine, and it may well refuse.
    from errand.runner import Pytest

    runner = Pytest( dirs = [ "nowhere" ], python = "/usr/bin/python3" )
    if runner._has_pytest():
        skip( "the system interpreter here already has pytest" )
    why = runner.ensure_pytest( echo = None )
    assert why and "not errand's to do" in why, why
    assert "Pytest( install = True )" in why, "it has to say what to do instead"


if test( "a build runs once, not once per file" ):
    # Once per file would recompile for nothing; under -j it would have several
    # processes writing the same binary at the same time.
    import os
    from errand.cli.listing import prepare_runners
    from errand.runner import Catch2

    class Counting( Catch2 ):
        runs = 0

        def shell( self, argv, ctx, **kw ):
            Counting.runs += 1
            class Nothing:
                returncode, stdout, stderr = 0, "", ""
            return Nothing()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path( os.path.realpath( tmp ) )
        runner = Counting( build = "make -C cpp" )
        runner.root = root
        entries = runner.collect( [ ( [ root / "cpp" / "test_a.cpp", root / "cpp" / "test_b.cpp" ], None ) ] )
        assert [ e.name for e in entries ] == [ "test_a.cpp", "test_b.cpp" ], "a source is one run"
        assert prepare_runners( entries, root = root, out_root = root, tags = { }, env_name = "x" ) == [ ]

    assert Counting.runs == 1, f"the build ran {Counting.runs} times for 2 files"


if test( "mentioning errand is not declaring work" ):
    # A comment saying a suite is collected by errand, a docstring, a string in
    # a fixture -- all of those mention it, and none should be imported and
    # executed on the strength of that.
    from errand import discovery

    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        ( root / "talks_about.py" ).write_text( "# errand collects this through a runner\n" )
        ( root / "real.py" ).write_text( "from errand import test\nif test( 'x' ): pass\n" )
        ( root / "also_real.py" ).write_text( "import errand\n" )

        found = sorted( p.name for p in discovery.candidates( root ) )
        assert found == [ "also_real.py", "real.py" ], found


if test( "a runner's entry can have parameters, like anything else" ):
    from errand import Param

    class Two( P.Runner ):
        name = "two"

        def collect( self, specs ):
            return [ self.entry( name = "suite", file = Path( "suite.cpp" ),
                                 params = { "device": Param( "cpu",
                                                             choices = [ "cpu", "cuda" ] ) } ) ]

        def run( self, entry, ctx ):
            return P.Outcome( status = "PASS", results = { "on": ctx.params[ "device" ] } )

    made = Two().collect( [ ] )[ 0 ]
    assert list( made.params ) == [ "device" ]
    # What the core resolves is what the runner is handed -- so a matrix over
    # a runner's parameter is the same matrix as over anyone else's.
    got = made.runner.run( made, P.RunContext( root = Path( "." ), out_dir = Path( "." ),
                                                 params = { "device": "cuda" } ) )
    assert got.results == { "on": "cuda" }


# --- which runner takes a file ----------------------------------------------

def a_tree( tmp ):
    import os
    root = Path( os.path.realpath( tmp ) )
    files = {
        "tests/test_own.py"   : "from errand import test\nif test( 'own' ):\n    pass\n",
        "tests/test_plain.py" : "def test_x( ):\n    assert True\n",
        "scripts/plot.py"     : "import os\nd = os.environ.get( 'ERRAND_OUT_DIR' )\nprint( 'plotted', bool( d ) and os.path.isdir( d ) )\n",
        "scripts/go.sh"       : "#!/bin/sh\necho went\nexit 3\n",
        "scripts/tool"        : "#!/bin/sh\necho tooled\n",
        "notes.txt"           : "nothing to run\n",
    }
    for rel, text in files.items():
        ( root / rel ).parent.mkdir( parents = True, exist_ok = True )
        ( root / rel ).write_text( text )
    ( root / "scripts" / "tool" ).chmod( 0o755 )
    ( root / "scripts" / "go.sh" ).chmod( 0o755 )
    return root


if test( "an entry target goes to the entry runner that fits it best, whatever the order" ):
    from errand import discovery
    with tempfile.TemporaryDirectory() as tmp:
        root = a_tree( tmp )
        defaults = list( P.defaults().values() )
        for runners in ( defaults, list( reversed( defaults ) ) ):
            level, who = discovery.owners( root / "tests" / "test_own.py", runners )
            assert ( level, who[ 0 ].name ) == ( P.ERRAND, "errand" ), ( level, who )
            level, who = discovery.owners( root / "tests" / "test_plain.py", runners )
            assert ( level, who[ 0 ].name ) == ( P.FRAMEWORK, "pytest" ), ( level, who )
            # A script is no entry runner's: it is run as it is, when named.
            assert discovery.owners( root / "scripts" / "plot.py", runners )[ 0 ] == P.NONE
            assert discovery.owners( root / "notes.txt", runners )[ 0 ] == P.NONE


if test( "a bare target is a file or a command, read from the command line alone" ):
    from errand import discovery
    with tempfile.TemporaryDirectory() as tmp:
        root = a_tree( tmp )
        found = [ str( p.relative_to( root ) ) for p in discovery.candidates( root, runners = P.defaults() ) ]
        assert found == [ "tests/test_own.py", "tests/test_plain.py" ], found
        # A glob with no `::` runs every file it matches that can be run, each its own run.
        got, _, _ = discovery.select( "scripts/*", root, runners = P.defaults(), cwd = root )
        assert sorted( ( e.name, e.runner.name ) for e in got ) == \
            [ ( "go.sh", "executable" ), ( "plot.py", "python" ), ( "tool", "executable" ) ]
        # A word that is no file is a command of the place.
        got, _, _ = discovery.select( "scripts/plot.py,echo", root, runners = P.defaults(), cwd = root )
        assert sorted( ( e.name, e.runner.name ) for e in got ) == [ ( "echo", "executable" ), ( "plot.py", "python" ) ]
        for target, said in ( ( "notes.txt", "notes.txt::*" ), ( "tests", "tests/**::*" ),
                              ( "nope.py", "no such file" ), ( "no-such-command-here", "no such command" ) ):
            try:
                discovery.select( target, root, runners = P.defaults(), cwd = root )
                raise AssertionError( f"{target} designated something" )
            except ValueError as err:
                assert said in str( err ), err


if test( "two entry runners at the same level is an error that names them; `-r` picks one" ):
    from errand import discovery
    with tempfile.TemporaryDirectory() as tmp:
        root = a_tree( tmp )
        mine = P.Runners( P.defaults() )
        mine[ "again" ] = P.Errand()
        try:
            discovery.select( "tests/test_own.py::*", root, runners = mine, cwd = root )
            raise AssertionError( "a tie was settled silently" )
        except ValueError as err:
            assert "errand and again" in str( err ) and "-r NAME" in str( err ), err
        got, _, _ = discovery.select( "tests/test_own.py::*", root, runners = mine, cwd = root,
                                      force = "again" )
        assert [ e.name for e in got ] == [ "own" ]
        try:
            discovery.select( "tests/test_own.py::*", root, runners = mine, cwd = root, force = "agian" )
            raise AssertionError( "an unknown runner was accepted" )
        except ValueError as err:
            assert "again" in str( err ), err
        # ...and `replace` is how a configured runner takes the default one's place.
        mine.replace( P.Python() )
        assert sum( isinstance( r, P.Python ) for r in mine.values() ) == 1 and "python" in mine


if test( "a `::name` on a file run as a whole is refused, unless its runner takes one" ):
    from errand import discovery
    with tempfile.TemporaryDirectory() as tmp:
        root = a_tree( tmp )
        try:
            discovery.select( "scripts/plot.py::x", root, runners = P.defaults(), cwd = root )
            raise AssertionError( "a script was taken for a file of entries" )
        except ValueError as err:
            assert "no entry runner takes it" in str( err ), err
        try:
            discovery.select( "scripts/plot.py::x", root, runners = P.defaults(), cwd = root, force = "python" )
            raise AssertionError( "a name was dropped on the floor" )
        except ValueError as err:
            assert "run as a whole" in str( err ), err
        assert P.Cargo.takes_selector and P.Catch2.takes_selector and P.Pytest.takes_selector


if test( "a script runs in the place, its exit code is its status, and it is one directory" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = a_tree( tmp )
        ( root / "errand-project.py" ).write_text( "import errand\n" )
        code, output = run_errand( root, "run", "-o", "--no-queue", "scripts/plot.py" )
        assert code == 0 and "plotted True" in output, output
        # No level named after the file a second time.
        assert ( root / "errand-outputs" / "runs" / "scripts" / "plot.py" / "latest" / "result.yaml" ).exists()
        code, output = run_errand( root, "run", "-o", "--no-queue", "scripts/go.sh" )
        assert code == 1 and "went" in output and "exit 3" in output, output
        # With no directory asked for, none is handed over, and none is made in the project.
        code, output = run_errand( root, "run", "--no-queue", "scripts/plot.py" )
        assert code == 0 and "plotted False" in output, output
        assert list( ( root / "errand-outputs" / "runs" / "scripts" / "plot.py" ).glob( "*/result.yaml" ) )


if test( "a build goes to the environment's own directory, and is told where" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        where = root / "build" / "gpu"
        where.mkdir( parents = True )
        runner = Catch2( build = "sh -c 'touch {build_dir}/made && echo $ERRAND_BUILD_DIR > {build_dir}/told'",
                         binary = "{build_dir}/{stem}" )
        ctx = P.RunContext( root = root, out_dir = root, build_dir = where )
        assert runner.prepare( [ ], ctx ) is None
        assert ( where / "made" ).exists()
        assert ( where / "told" ).read_text().strip() == str( where )
        assert runner._binary_for( root / "cpp" / "test_a.cpp", where ) == where / "test_a"


FAKE_CATCH2 = r'''#!/bin/sh
# What a Catch2 binary says when it is asked, and nothing else.
case "$*" in
  *--list-tests*)
    cat <<'X'
<?xml version="1.0" encoding="UTF-8"?>
<MatchingTests>
  <TestCase><Name>adds</Name><Tags>[math]</Tags></TestCase>
  <TestCase><Name>multiplies</Name><Tags>[math][slow]</Tags></TestCase>
</MatchingTests>
X
    exit 0;;
esac
for a in "$@"; do case "$a" in xml::out=*) out="${a#xml::out=}";; esac; done
name=all
for a in "$@"; do case "$a" in --reporter|xml::out=*) ;; *) name="$a";; esac; done
cat > "$out" <<X
<?xml version="1.0"?><Catch2TestRun name="t"><TestCase name="adds"><OverallResult success="true"/></TestCase><TestCase name="multiplies"><OverallResult success="true"/></TestCase><OverallResults successes="2" failures="0" expectedFailures="0"/></Catch2TestRun>
X
echo "ran $name"
'''

FAKE_PROJECT = '''
import errand
errand.runners.replace( errand.Catch2(
    build = "sh -c 'echo built >> build.log && cp cpp/fake.sh {build_dir}/test_math && chmod +x {build_dir}/test_math'",
    binary = "{build_dir}/{stem}" ) )
'''


if test( "a compiled suite is built where it runs, then run once, its spec handed to it" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", FAKE_PROJECT,
                                 { "cpp/test_math.cpp": "#include <catch2/catch_test_macros.hpp>\n",
                                   "cpp/fake.sh": FAKE_CATCH2 } )

        code, output = run_errand( project, "list", "**::*" )
        assert code == 0 and "test_math.cpp" in output, output
        assert not ( project / "build.log" ).exists(), "listing builds nothing"

        code, output = run_errand( project, "run", "-o", "--no-queue", "**::*" )
        assert code == 0 and "ran all" in output, output
        # One run for the source, one directory...
        assert ( project / "errand-outputs" / "runs" / "cpp" / "test_math.cpp" / "latest" / "catch2.xml" ).exists()
        # ...and built once for the run.
        assert ( project / "build.log" ).read_text().count( "built" ) == 1

        code, output = run_errand( project, "run", "--no-queue", "cpp/test_math.cpp::mult*" )
        assert code == 0 and "ran mult*" in output, output
        code, output = run_errand( project, "run", "--no-queue", "cpp/test_math.cpp::~[slow]" )
        assert code == 0 and "ran ~[slow]" in output, output


if test( "a build that fails stops the run, and says why" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj",
                                 "import errand\nerrand.runners.replace( errand.Catch2( build = \"false\" ) )\n",
                                 { "cpp/test_math.cpp": "#include <catch2/catch_test_macros.hpp>\n" } )
        code, output = run_errand( project, "run", "--no-queue", "**::*" )
        assert code == 1 and "catch2: the build failed" in output, output
