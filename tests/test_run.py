"""`errand run`: one verb launches everything, and a directory is made only when asked for."""
import tempfile
from pathlib import Path

from errand import test

from _infra import run_errand, write_project


WORK = '''
from errand import test
if test( "hello" ):
    print( "said hello" )
if test( "aside", bulk = False ):
    print( "said aside" )
'''


if test( "a bare `errand run` runs what the project says, and says so when it says nothing" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "tests/test_a.py": WORK } )
        code, output = run_errand( project, "run", "--no-queue" )
        assert code == 2 and "errand.default_run" in output, output

        ( project / "errand-project.py" ).write_text(
            "import errand\nerrand.default_run = [ 'tests/**::*' ]\n" )
        code, output = run_errand( project / "tests", "run", "--no-queue" )
        assert code == 0 and "said hello" in output, output
        assert "said aside" not in output, "what is not bulk waits to be named"


if test( "`--out` takes a pattern, and the run lands where it says" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", {
            "show.py": "import os\nprint( 'out is', os.environ[ 'ERRAND_OUT_DIR' ] )\n" } )
        code, output = run_errand( project, "run", "--no-queue", "--out", "results/{env}/{when}", "show.py" )
        assert code == 0, output
        made = [ p for p in ( project / "results" / "default" ).iterdir() if p.is_dir() and not p.is_symlink() ]
        assert len( made ) == 1 and ( made[ 0 ] / "result.yaml" ).exists(), made
        assert ( project / "results" / "default" / "latest" ).resolve() == made[ 0 ].resolve()
        assert f"results/default/{made[ 0 ].name}" in output, output
        assert not ( project / "runs" ).exists(), "a pattern is the whole of where it goes"


if test( "`errand shell` is a shell: a command goes through `errand run`" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { } )
        code, output = run_errand( project, "shell", "--", "echo", "hi" )
        assert code == 2 and "errand run" in output, output


if test( "a comma cannot be part of an environment's name, nor of a tag's value" ):
    import errand
    from errand import config as C
    for bad in ( lambda: C.envs.__setitem__( "a,b", errand.Env( [ ] ) ),
                 lambda: errand.Env( [ ], fp = "32,64" ) ):
        try:
            bad()
            raise AssertionError( "a comma was accepted" )
        except ValueError as err:
            assert "comma" in str( err ), err


if test( "the state directory can be moved, for a machine" ):
    import os
    from errand import config as C
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        assert C.state( root ) == root / ".errand" and C.state_rel( root ) == ".errand"
        kept = os.environ.get( C.STATE_ENV )
        os.environ[ C.STATE_ENV ] = str( root / "elsewhere" )
        try:
            assert C.state( root ) == root / "elsewhere" and C.state_rel( root ) == "elsewhere"
            os.environ[ C.STATE_ENV ] = "/scratch/me"
            assert C.state_rel( root ) == "/scratch/me", "outside the root, it is named in full"
        finally:
            if kept is None:
                os.environ.pop( C.STATE_ENV, None )
            else:
                os.environ[ C.STATE_ENV ] = kept
