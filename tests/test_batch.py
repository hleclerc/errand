"""Launching work and getting the shell back, then finding out how it went."""
import subprocess
import tempfile
import time
from pathlib import Path

from errand import test, yamlish
from errand import batch as B, layers as L

from _infra import run_errand, ssh_target, write_project


SLOW = '''
import time
from errand import bench, Param

if p := bench( "slow", exclusive = False, n = Param( 1 ) ):
    time.sleep( 1.5 * p.n )
    p.results[ "seconds" ] = 1.5 * p.n
'''


def wait_for( predicate, seconds = 120 ):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep( 0.5 )
    return False


# --- the shape of it, with no machine ---------------------------------------

if test( "a batch system is its own detachment" ):
    # srun waits for a node; sbatch returns as soon as the job is queued, so
    # there is nothing left to let go of.
    waiting = L.Slurm( partition = "gpu" ).wrap(
        L.Command( [ "python", "-m", "errand" ] ), L.Context( root = Path( "/" ) ) )
    assert waiting.argv[ 0 ] == "srun"

    letting_go = L.Slurm( partition = "gpu" ).wrap(
        L.Command( [ "python", "-m", "errand" ], { "A": "1" } ),
        L.Context( root = Path( "/" ), batch = True ) )
    assert letting_go.argv[ : 2 ] == [ "sbatch", "--parsable" ]
    assert "--wrap" in letting_go.argv
    wrapped = letting_go.argv[ letting_go.argv.index( "--wrap" ) + 1 ]
    assert "python -m errand" in wrapped
    assert "A=1" in wrapped, "the environment has to travel inside the wrapped command"


if test( "a job id is read out of whatever the batch system said" ):
    class Said:
        def __init__( self, out, code = 0 ):
            self.stdout, self.stderr, self.returncode = out, "", code

    assert B._from_submission( Said( "Submitted batch job 918273\n" ), "batch" ) == \
        { "kind": "batch", "handle": "918273" }
    assert B._from_submission( Said( "918274\n" ), "batch" )[ "handle" ] == "918274"   # --parsable
    failed = B._from_submission( Said( "sbatch: error: invalid partition\n", code = 1 ), "batch" )
    assert failed[ "kind" ] == "failed" and "invalid partition" in failed[ "error" ]


if test( "a handle with nobody behind it is not alive" ):
    assert B.alive( { "kind": "local", "handle": "" } ) is False
    assert B.alive( { "kind": "local", "handle": "999999999" } ) is False
    assert B.alive( { "kind": "local", "handle": str( __import__( "os" ).getpid() ) } ) is True


# --- here ------------------------------------------------------------------

if test( "the shell comes straight back, and the work carries on", tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "bench_slow.py": SLOW } )

        started = time.perf_counter()
        code, output = run_errand( project, "--batch", "-k", "bench", "--n=1,2" )
        handed_back = time.perf_counter() - started

        assert code == 0, output
        assert handed_back < 4.0, f"it waited ({handed_back:.1f}s): the point is that it does not"
        assert "submitted" in output and "2 run(s)" in output, output
        # ...and nothing has finished yet, which is why there is a status command
        assert not list( ( project / "runs" ).rglob( "result.yaml" ) )

        leaves = lambda: list( ( project / "runs" ).rglob( "result.yaml" ) )
        assert wait_for( lambda: len( leaves() ) == 2 ), "the detached run never finished"

        code, output = run_errand( project, "--status" )
        assert code == 0 and "2/2" in output, output
        assert "seconds=1.5" in output and "seconds=3" in output, output


if test( "the record holds only what the tree cannot say", tags = [ "slow" ] ):
    # The output tree IS the state. The record says which runs went together
    # and what handle each place was given -- nothing that could contradict it.
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "bench_slow.py": SLOW } )
        run_errand( project, "--batch", "-k", "bench" )
        assert wait_for( lambda: list( ( project / "runs" ).rglob( "result.yaml" ) ) )

        records = B.load_all( project )
        assert len( records ) == 1
        record = records[ 0 ]
        assert [ r[ "label" ] for r in record[ "runs" ] ] == [ "slow" ]
        assert record[ "places" ][ 0 ][ "kind" ] == "local"
        # where it ran is not in the record: it is read back out of the result
        assert record[ "runs" ][ 0 ][ "place" ] == "?"
        assert B.states( project, record )[ 0 ][ "place" ] != "?"

        # the state is read from the tree, so it survives the handle dying
        record[ "places" ][ 0 ][ "handle" ] = "999999999"
        rows = B.states( project, record )
        assert rows[ 0 ][ "state" ] == B.DONE and rows[ 0 ][ "status" ] == "PASS"

        # ...and a run whose result never appeared, with nobody left running,
        # is lost rather than pending for ever
        record[ "runs" ].append( { **record[ "runs" ][ 0 ], "under": "runs/never/here" } )
        assert B.states( project, record )[ 1 ][ "state" ] == B.LOST
        assert B.finished( B.states( project, record ) )


if test( "a submission can be dropped from the list", tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "bench_slow.py": SLOW } )
        run_errand( project, "--batch", "-k", "bench" )
        assert wait_for( lambda: list( ( project / "runs" ).rglob( "result.yaml" ) ) )

        ident = B.load_all( project )[ 0 ][ "id" ]
        code, _ = run_errand( project, "--forget", ident )
        assert code == 0 and B.load_all( project ) == [ ]
        # forgetting the record does not forget the results
        assert list( ( project / "runs" ).rglob( "result.yaml" ) )


# --- over there -------------------------------------------------------------

REMOTE = '''
from errand import configure, env, Ssh, Vars

configure( exclude = [ "_lib" ] )

env( "over-there",
     [ Ssh( host = {host!r}, root = {root!r}, options = {options!r} ),
       Vars( {{ "PYTHONPATH": "{root}/_lib" }} ) ],
     where = "remote" )
'''


if test( "a remote run is let go of, and collected later", tags = [ "ssh", "slow" ] ):
    host, options, root_of = ssh_target()
    remote_root = root_of()

    with tempfile.TemporaryDirectory() as tmp:
        project = write_project(
            Path( tmp ) / "proj",
            REMOTE.format( host = host, root = remote_root, options = options ),
            { "bench_slow.py": SLOW }, vendor = True )

        started = time.perf_counter()
        code, output = run_errand( project, "--batch", "-k", "bench", "--env", "over-there" )
        handed_back = time.perf_counter() - started
        assert code == 0, output
        assert handed_back < 60, f"it waited for the work ({handed_back:.1f}s)"
        assert B.load_all( project )[ 0 ][ "places" ][ 0 ][ "kind" ] == "ssh", output

        # Nothing is pushed back: it sits there until something collects it,
        # which is what asking does.
        def collected( ):
            run_errand( project, "--status" )
            return list( ( project / "runs" ).rglob( "result.yaml" ) )

        assert wait_for( collected, seconds = 180 ), "the results never came back"
        code, output = run_errand( project, "--status" )
        assert "1/1" in output, output

    subprocess.run( [ "ssh", *options, host, f"rm -rf {remote_root}" ] )
