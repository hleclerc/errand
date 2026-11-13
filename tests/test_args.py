"""What is written after the target belongs to the target."""
import tempfile
from pathlib import Path

from errand import test, cli

from _infra import run_errand, write_project


def parser( ):
    return cli.build_parser( [ "fp" ] )


if test( "errand's options, the target, then the target's own arguments" ):
    before, target, after = cli.split_target( parser(), [ "--env", "gpu", "-j4", "--fp", "64", "t.py",
                                                          "--n=3", "--env", "x" ] )
    assert before == [ "--env", "gpu", "-j4", "--fp", "64" ] and target == "t.py"
    # After the target, nothing is errand's -- `--env` included.
    assert after == [ "--n=3", "--env", "x" ]
    assert cli.split_target( parser(), [ "-k", "bench" ] ) == ( [ "-k", "bench" ], None, [ ] )


if test( "a parameter before the target is a mistake worth hearing about" ):
    try:
        cli.split_target( parser(), [ "--n=3", "t.py" ] )
        raise AssertionError( "a parameter was taken as errand's" )
    except ValueError as err:
        assert "goes after it" in str( err ) and "`.`" in str( err ), err


if test( "declared parameters are read anywhere among them; the rest passes through" ):
    values, raw = cli.split_args( [ "--size", "4", "--n", "5", "-v", "--method=cg", "--", "--n", "9" ],
                                  { "n": None, "method": None } )
    assert values == { "n": "5", "method": "cg" }
    assert raw == [ "--size", "4", "-v", "--", "--n", "9" ], "after `--`, everything is the target's"


if test( "a grid is asked for with --grid=SEP; without it a value is one value" ):
    assert cli.alternatives( "a,b" ) == [ "a,b" ], "no --grid, no grid"
    assert cli.alternatives( "a+b", "+" ) == [ "a", "b" ]
    assert cli.alternatives( "a++b", "+" ) == [ "a", "", "b" ]
    assert cli.alternatives( "1,2+3,4", "+" ) == [ "1,2", "3,4" ]

    from errand import Param
    # Without --grid, a comma is part of the value.
    combos = cli.expand( { "shape": "1,2" }, { "shape": Param( "x" ) } )
    assert len( combos ) == 1 and combos[ 0 ][ 1 ][ "shape" ] == "1,2"
    # ... and a number that holds one says how to ask for a grid.
    try:
        cli.expand( { "n": "1,2" }, { "n": Param( 1 ) } )
        raise AssertionError( "1,2 was read as an int" )
    except ValueError as err:
        assert "--grid=," in str( err ), err

    # A command's words are never rewritten: `-Wl,-rpath` is one argument.
    combos = cli.expand( { }, { }, [ "--size", "1+2", "-Wl,-rpath", "--mode=a,b" ], sep = "+" )
    assert len( combos ) == 1
    assert combos[ 0 ][ 1 ][ cli.ARGS ] == [ "--size", "1+2", "-Wl,-rpath", "--mode=a,b" ]

    # A declared parameter is an axis.
    combos = cli.expand( { "n": "1+2" }, { "n": Param( 1 ) }, [ "--tol", "1e-3,1e-6" ], sep = "+" )
    assert len( combos ) == 2 and combos[ 0 ][ 0 ] == { "n": 1 }
    assert combos[ 0 ][ 1 ][ cli.ARGS ] == [ "--tol", "1e-3,1e-6" ]
    assert "2 runs" in cli.describe_grid( combos )


if test( "environments and tags are several only under --grid too" ):
    from errand.cli.grid import split_values
    assert split_values( None ) == [ None ]
    assert split_values( "gpu" ) == [ "gpu" ]
    assert split_values( "gpu,cluster", "," ) == [ "gpu", "cluster" ]
    assert split_values( "gpu+cluster", "+" ) == [ "gpu", "cluster" ]
    assert split_values( [ "gpu+a", "b" ], "+" ) == [ "gpu", "a", "b" ], "setup's words, each split"
    try:
        split_values( "gpu,cluster", what = "--env" )
        raise AssertionError( "a comma without --grid was taken as a name" )
    except ValueError as err:
        assert "--env" in str( err ) and "--grid=," in str( err ), err


if test( "--grid is errand's: it goes before the target" ):
    before, target, after = cli.split_target( parser(), [ "--grid=+", "t.py", "--n=1+2" ] )
    assert before == [ "--grid=+" ] and target == "t.py" and after == [ "--n=1+2" ]
    known, _ = parser().parse_known_args( before )
    assert known.grid == "+"


WORK = '''
import sys
from errand import test, Param
if p := test( "hello", n = Param( 1 ) ):
    print( "n is", p.n, "argv", sys.argv[ 1 : ] )
'''


if test( "a file of errand's gets them as its sys.argv, and a script as its own", tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", {
            "test_p.py"      : WORK,
            "scripts/show.py": "import sys\nprint( 'script got', sys.argv[ 1 : ] )\n" } )

        code, output = run_errand( project, "run", "--no-queue", "--grid=+", "test_p.py::*", "--n=2+3", "--verbose" )
        assert code == 0, output
        assert "n is 2 argv ['--n=2', '--verbose']" in output, output
        assert "n is 3 argv ['--n=3', '--verbose']" in output, output

        code, output = run_errand( project, "run", "-o", "--no-queue", "scripts/show.py", "--size", "4096",
                                   "--env", "gpu" )
        assert code == 0 and "script got ['--size', '4096', '--env', 'gpu']" in output, output

        # Two sets of arguments are two runs, and two directories.
        leaves = sorted( p.name for p in ( project / "errand-outputs" / "runs" / "scripts" / "show.py" ).iterdir() )
        assert any( "args=--size_4096_--env_gpu" in name for name in leaves ), leaves

        # Under -j, each child gets them too.
        code, output = run_errand( project, "run", "--no-queue", "-j", "2", "--grid=,", "test_p.py::*", "--n=4,5", "-x" )
        assert code == 0 and "argv ['--n=4', '-x']" in output and "argv ['--n=5', '-x']" in output, output

        # A comma among the script's own arguments is the script's: passed as it was written.
        code, output = run_errand( project, "run", "--no-queue", "scripts/show.py", "--size", "1,2" )
        assert code == 0 and "script got ['--size', '1,2']" in output, output

        # `**::*` is every entry here.
        code, output = run_errand( project, "run", "--no-queue", "**::*", "--n=7" )
        assert code == 0 and "n is 7" in output, output


if test( "several files are several targets ( a glob the shell expanded )" ):
    with tempfile.TemporaryDirectory() as d:
        a, b, c = ( Path( d ) / n for n in ( "test_a.py", "test_b.py", "data.txt" ) )
        for f in ( a, b, c ):
            f.write_text( "" )
        before, target, after = cli.split_target( parser(), [ "--env", "gpu", str( a ), str( b ), str( c ), "--n=3" ] )
        assert before == [ "--env", "gpu" ] and target == f"{ a },{ b }" and after == [ str( c ), "--n=3" ]
        # after a `--`, a file is an argument
        assert cli.split_target( parser(), [ str( a ), "--", str( b ) ] )[ 1 : ] == ( str( a ), [ "--", str( b ) ] )
        # a pattern keeps its commas, and what follows it is its arguments
        assert cli.split_target( parser(), [ "x.py,y.py", str( b ) ] )[ 1 : ] == ( "x.py,y.py", [ str( b ) ] )
        # a comma in a file name is only a comma
        comma = Path( d ) / "test_c,d.py"
        comma.write_text( "" )
        assert cli.split_target( parser(), [ str( a ), str( comma ) ] )[ 1 ] == f"{ a },{ str( comma ).replace( ',', chr( 92 ) + ',' ) }"


if test( "several entry patterns are several targets" ):
    with tempfile.TemporaryDirectory() as d:
        a, b = ( Path( d ) / n for n in ( "test_a.py", "test_b.py" ) )
        for f in ( a, b ):
            f.write_text( "" )
        before, target, after = cli.split_target( parser(), [ "--env", "gpu", f"{ a }::x*", f"{ b }::y", "**/t.py::*", "--n=3" ] )
        assert before == [ "--env", "gpu" ] and target == f"{ a }::x*,{ b }::y,**/t.py::*" and after == [ "--n=3" ], ( target, after )
        # an argument that holds `::` without naming a file stays an argument
        assert cli.split_target( parser(), [ f"{ a }::x", "a::b" ] )[ 1 : ] == ( f"{ a }::x", [ "a::b" ] )
