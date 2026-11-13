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
        assert not ( project / "errand-outputs" / "runs" ).exists(), "a pattern is the whole of where it goes"


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


if test( "errand's outputs are one visible directory, which can be moved, for a machine" ):
    import os
    from errand import config as C
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        out = root / "errand-outputs"
        assert ( C.runs( root ), C.state( root ), C.state_rel( root ), C.builds_rel( root ) ) == \
            ( out / "runs", out / "state", "errand-outputs/state", "errand-outputs/builds" )
        kept = os.environ.get( C.OUTPUTS_ENV )
        os.environ[ C.OUTPUTS_ENV ] = str( root / "elsewhere" )
        try:
            assert C.state( root ) == root / "elsewhere/state" and C.outputs_rel( root ) == "elsewhere"
            os.environ[ C.OUTPUTS_ENV ] = "/scratch/me"
            assert C.runs( root ) == Path( "/scratch/me/runs" )
            assert C.outputs_rel( root ) == "errand-outputs", "over there, the copy's own"
        finally:
            if kept is None:
                os.environ.pop( C.OUTPUTS_ENV, None )
            else:
                os.environ[ C.OUTPUTS_ENV ] = kept
        C.configure( state = ".x" )               # said, and left: no project breaks on it
        assert C.state( root ) == out / "state"


if test( "a .errand of before, and the visible runs/, move into errand-outputs once" ):
    from errand import config as C
    C.reset()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        for f in ( ".errand/runs/a.py/s1/result.yaml", ".errand/builds/x.yaml", ".errand/history",
                   ".errand/live/r.json", ".errand/vm/windows/img/ready", "runs/b.py/c/summary.yaml",
                   "runs/b.py/s2/result.yaml" ):
            ( root / f ).parent.mkdir( parents = True, exist_ok = True )
            ( root / f ).write_text( "x" )
        said = [ ]
        C.migrate( root, said.append )
        out = root / "errand-outputs"
        for f in ( "runs/a.py/s1/result.yaml", "runs/b.py/s2/result.yaml", "builds/records/x.yaml",
                   "builds/windows/img/ready", "state/history", "state/live/r.json" ):
            assert ( out / f ).exists(), f
        assert not ( root / ".errand" ).exists() and not ( root / "runs" ).exists() and len( said ) == 1
        C.migrate( root, said.append )
        assert len( said ) == 1, "once"
