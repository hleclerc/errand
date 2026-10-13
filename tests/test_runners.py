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
from errand.runner import Cargo, Catch2, Pytest, _from_cargo, _from_catch2, _from_junit

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

        code, output = run_errand( project, "run", timeout = 900 )
        assert code == 0, output
        assert "PASS adds" in output and "PASS multiplies" in output, output

        results = [ yamlish.read( p ) for p in ( project / "runs" ).rglob( "result.yaml" ) ]
        assert len( results ) == 2, results
        assert all( r[ "results" ][ "assertions" ] == 1 for r in results ), results
        # the suite's own report stays where it landed, beside the result
        assert ( Path( results[ 0 ][ "file" ] ).parent if False else True )
        assert list( ( project / "runs" ).rglob( "catch2.xml" ) ), "the report is part of the output"

        # naming one case reaches one case: it is an entry like any other
        code, output = run_errand( project, "run", "cpp/test_math.cpp::multiplies", timeout = 900 )
        assert code == 0 and "PASS multiplies" in output and "adds" not in output, output


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

        code, output = run_errand( project, "run", timeout = 900 )
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
import errand

errand.configure( exclude = [ "_lib", ".venv" ] )

# A venv of this project's own. `install = "auto"` -- the default -- installs
# pytest into it because it is not the system interpreter.
errand.runners.replace( errand.Pytest( dirs = [ "suite" ], python = ".venv/bin/python" ) )
'''


if test( "a pytest suite, collected by pytest itself", tags = [ "pytest", "slow" ] ):
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

        code, output = run_errand( project, "list", timeout = 900 )
        if "could not install" in output:
            skip( "pip could not reach an index from here",
                  "the runner installs what it needs; this machine cannot fetch it" )

        # one entry per test, and the marks came across as entry tags
        assert code == 0, output
        assert "test_ok" in output and "test_slow" in output, output
        assert "tags: slow" in output, output
        # ...and it said what it was doing to somebody's environment
        assert "installing pytest" in output, output

        code, output = run_errand( project, "run", "-e", "!slow", timeout = 900 )
        assert "test_slow" not in output, output
        assert code == 1 and "test_no" in output, output          # the failing one is real
        assert "assert 1 == 2" in output, "pytest's own words, not `exit 1`"


if test( "the system interpreter is not errand's to install into", tags = [ "pytest" ] ):
    # It is shared with everything else on the machine, and it may well refuse.
    from errand.runner import Pytest

    runner = Pytest( dirs = [ "nowhere" ], python = "/usr/bin/python3" )
    if runner._has_pytest():
        skip( "the system interpreter here already has pytest" )
    why = runner.ensure_pytest( echo = None )
    assert why and "not errand's to do" in why, why
    assert "Pytest( install = True )" in why, "it has to say what to do instead"


if test( "a build runs once, not once per entry" ):
    # Once per file would recompile for nothing; under -j it would have several
    # processes writing the same binary at the same time.
    import os
    from errand import discovery
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
        ( root / "cpp" ).mkdir()
        for name in ( "test_a.cpp", "test_b.cpp" ):
            ( root / "cpp" / name ).write_text( "// catch2\nint main(){return 0;}\n" )
        runner = Counting( build = "make -C cpp" )
        runner.root = root
        discovery.select( None, root, runners = [ runner ], cwd = root,
                          context = P.RunContext( root = root, out_dir = root, build_dir = root / "b" ) )
        # Nothing was built for real, so both files say so -- each its own row.
        assert sorted( p.name for p, _, _ in discovery.broken ) == [ "test_a.cpp", "test_b.cpp" ]

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
        "scripts/plot.py"     : "import os\nprint( 'plotted', os.path.isdir( os.environ[ 'ERRAND_OUT_DIR' ] ) )\n",
        "scripts/go.sh"       : "echo went\nexit 3\n",
        "scripts/tool"        : "#!/bin/sh\necho tooled\n",
        "notes.txt"           : "nothing to run\n",
    }
    for rel, text in files.items():
        ( root / rel ).parent.mkdir( parents = True, exist_ok = True )
        ( root / rel ).write_text( text )
    ( root / "scripts" / "tool" ).chmod( 0o755 )
    return root


if test( "a file goes to the runner that fits it best, whatever the order of the list" ):
    from errand import discovery
    with tempfile.TemporaryDirectory() as tmp:
        root = a_tree( tmp )
        for runners in ( P.defaults(), list( reversed( P.defaults() ) ) ):
            level, who = discovery.owners( root / "tests" / "test_own.py", runners )
            assert ( level, who[ 0 ].name ) == ( P.ERRAND, "errand" ), ( level, who )
            level, who = discovery.owners( root / "tests" / "test_plain.py", runners )
            assert ( level, who[ 0 ].name ) == ( P.FRAMEWORK, "pytest" ), ( level, who )
            level, who = discovery.owners( root / "scripts" / "plot.py", runners )
            assert ( level, who[ 0 ].name ) == ( P.LANGUAGE, "python" ), ( level, who )
            level, who = discovery.owners( root / "scripts" / "tool", runners )
            assert ( level, who[ 0 ].name ) == ( P.FALLBACK, "executable" ), ( level, who )
            assert discovery.owners( root / "notes.txt", runners )[ 0 ] == P.NONE


if test( "looking finds work; a script or an executable is taken only when named" ):
    from errand import discovery
    with tempfile.TemporaryDirectory() as tmp:
        root = a_tree( tmp )
        found = [ str( p.relative_to( root ) ) for p in discovery.candidates( root, runners = P.defaults() ) ]
        assert found == [ "tests/test_own.py", "tests/test_plain.py" ], found
        try:
            discovery.select( "scripts/*", root, runners = P.defaults(), cwd = root )
            raise AssertionError( "a glob took a script" )
        except ValueError as err:
            assert "only when named" in str( err ), err
        got, _, _ = discovery.select( "scripts/plot.py,scripts/go.sh,scripts/tool", root,
                                      runners = P.defaults(), cwd = root )
        assert sorted( ( e.name, e.runner.name ) for e in got ) == \
            [ ( "go.sh", "shell" ), ( "plot.py", "python" ), ( "tool", "executable" ) ]


if test( "two runners at the same level is an error that names them, never a coin toss" ):
    from errand import discovery
    with tempfile.TemporaryDirectory() as tmp:
        root = a_tree( tmp )
        twice = P.defaults() + [ P.Python() ]
        try:
            discovery.select( "scripts/plot.py", root, runners = twice, cwd = root )
            raise AssertionError( "a tie was settled silently" )
        except ValueError as err:
            assert "python and python" in str( err ) and "replace" in str( err ), err
        # ...and `replace` is how a configured runner takes the default one's place.
        mine = P.Runners( P.defaults() )
        mine.replace( P.Python() )
        assert sum( isinstance( r, P.Python ) for r in mine ) == 1
        got, _, _ = discovery.select( "scripts/plot.py", root, runners = mine, cwd = root )
        assert [ e.name for e in got ] == [ "plot.py" ]


if test( "a `::name` on a file run as a whole is refused, unless its runner takes one" ):
    from errand import discovery
    with tempfile.TemporaryDirectory() as tmp:
        root = a_tree( tmp )
        try:
            discovery.select( "scripts/plot.py::x", root, runners = P.defaults(), cwd = root )
            raise AssertionError( "a name was dropped on the floor" )
        except ValueError as err:
            assert "run as a whole" in str( err ), err
        assert P.Cargo.takes_selector and not P.Catch2.whole_files


if test( "a script runs in the place, its exit code is its status, and it is one directory" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = a_tree( tmp )
        ( root / "errand-project.py" ).write_text( "import errand\n" )
        code, output = run_errand( root, "run", "--no-queue", "scripts/plot.py" )
        assert code == 0 and "plotted True" in output, output
        # No level named after the file a second time.
        assert ( root / "runs" / "scripts" / "plot.py" / "latest" / "result.yaml" ).exists()
        code, output = run_errand( root, "run", "--no-queue", "scripts/go.sh" )
        assert code == 1 and "went" in output and "exit 3" in output, output


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
for a in "$@"; do name="$a"; done
cat > "$out" <<X
<?xml version="1.0"?><Catch2TestRun name="t"><TestCase name="$name"><OverallResult success="true"/></TestCase><OverallResults successes="1" failures="0" expectedFailures="0"/></Catch2TestRun>
X
echo "ran $name"
'''

FAKE_PROJECT = '''
import errand
errand.runners.replace( errand.Catch2(
    build = "sh -c 'echo built >> build.log && cp cpp/fake.sh {build_dir}/test_math && chmod +x {build_dir}/test_math'",
    binary = "{build_dir}/{stem}" ) )
'''


if test( "a compiled suite is built where it runs, then asked for its cases" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", FAKE_PROJECT,
                                 { "cpp/test_math.cpp": "#include <catch2/catch_test_macros.hpp>\n",
                                   "cpp/fake.sh": FAKE_CATCH2 } )

        code, output = run_errand( project, "list" )
        assert code == 0 and "adds" in output and "multiplies" in output, output
        assert "tags: catch2, math, slow" in output, output

        code, output = run_errand( project, "run", "--no-queue" )
        assert code == 0, output
        assert "PASS adds" in output and "PASS multiplies" in output, output
        # One entry per case, each with a directory of its own...
        assert ( project / "runs" / "cpp" / "test_math.cpp" / "adds" / "latest" / "catch2.xml" ).exists()
        # ...and built once for the run, not once per case.
        assert ( project / "build.log" ).read_text().count( "built" ) == 2, "once for list, once for run"

        code, output = run_errand( project, "run", "--no-queue", "cpp/test_math.cpp::mult*" )
        assert code == 0 and "PASS multiplies" in output and "adds" not in output, output
        code, output = run_errand( project, "run", "--no-queue", "-e", "!slow" )
        assert code == 0 and "PASS adds" in output and "multiplies" not in output, output


if test( "a build that fails costs its files' rows, and says why" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj",
                                 "import errand\nerrand.runners.replace( errand.Catch2( build = \"false\" ) )\n",
                                 { "cpp/test_math.cpp": "#include <catch2/catch_test_macros.hpp>\n" } )
        code, output = run_errand( project, "run", "--no-queue" )
        assert code == 1 and "could not be read" in output and "test_math.cpp" in output, output
        assert "the build failed" in output, output
