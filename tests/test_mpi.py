"""`ranks = N`: an entry whose body runs in N processes, under the MPI launcher of the place."""
import os
import shutil
import tempfile
from pathlib import Path

from errand import skip, test

from _infra import run_errand, write_project


def _mpiexec():
    """An `mpiexec` to start the ranks with: on the PATH, or in a micromamba environment of this machine."""
    found = shutil.which( "mpiexec" )
    if found is None:
        envs = Path( os.environ.get( "MAMBA_ROOT_PREFIX", Path.home() / ".mamba" ) ) / "envs"
        found = next( ( str( p ) for p in sorted( envs.glob( "*/bin/mpiexec" ) ) ), None )
    if found is None:
        skip( "no mpiexec here", "micromamba install -c conda-forge mpich" )
    return found


RANKS = '''
import os
from errand import Param, skip, test
if test( "each rank", ranks = 2, scale = Param( 10 ) ):
    from errand import mpi
    import sys
    print( "rank", mpi.rank(), "of", mpi.size(), "scale", sys.argv[ 1: ], flush = True )
if test( "rank 1 fails", ranks = 2 ):
    from errand import mpi
    assert mpi.rank() != 1, "rank one is unhappy"
if test( "all skip", ranks = 2 ):
    skip( "not here" )
if test( "alone" ):
    from errand import mpi
    print( "alone, rank", mpi.rank(), flush = True )
'''


if test( "each rank runs the body, and the entry is what every rank made of it" ):
    mpiexec = _mpiexec()
    with tempfile.TemporaryDirectory() as tmp:
        config = f"import errand\nerrand.envs[ 'here' ] = errand.Env( [ errand.Mpi( {mpiexec!r} ) ] )\nerrand.default_env = 'here'\n"
        project = write_project( Path( tmp ) / "proj", config, { "test_ranks.py": RANKS } )

        code, output = run_errand( project, "run", "--no-queue", "test_ranks.py::each rank", "--scale", "3" )
        assert code == 0, output
        assert "[0] rank 0 of 2 scale ['--scale=3']" in output and "[1] rank 1 of 2" in output, output

        code, output = run_errand( project, "run", "--no-queue", "test_ranks.py::rank 1 fails" )
        assert code != 0 and "rank 1: AssertionError: rank one is unhappy" in output, output

        code, output = run_errand( project, "run", "--no-queue", "test_ranks.py::all skip" )
        assert code == 0 and "SKIP" in output and "not here" in output, output

        # `--ranks` on the command line: for an entry that does not say, and for a plain script
        code, output = run_errand( project, "run", "--no-queue", "--ranks", "3", "test_ranks.py::alone" )
        assert code == 0 and "[2] alone, rank 2" in output, output
        ( project / "script.py" ).write_text( "import os\nprint( 'script', os.environ.get( 'PMI_RANK' ) or os.environ.get( 'OMPI_COMM_WORLD_RANK' ) )\n" )
        code, output = run_errand( project, "run", "--no-queue", "--ranks", "2", "script.py" )
        assert code == 0 and "script 0" in output and "script 1" in output, output


if test( "a rank that says nothing fails the entry, and the results are rank 0's" ):
    import json
    from errand import mpi
    with tempfile.TemporaryDirectory() as tmp:
        leaf = Path( tmp )
        ( leaf / "rank-0.json" ).write_text( json.dumps( { "status": "PASS", "error": None, "results": { "t": 1 } } ) )
        status, error, _, results = mpi.gather( leaf, 2, 1 )
        assert status == "FAIL" and "rank 1 said nothing" in error and results == { "t": 1 }, ( status, error )
        ( leaf / "rank-1.json" ).write_text( json.dumps( { "status": "PASS", "error": None, "results": { } } ) )
        assert mpi.gather( leaf, 2, 0 )[ 0 ] == "PASS"


if test( "ranks are asked of the machine as cores" ):
    from errand import queue
    assert queue.normalize( { "ranks": 4 } ) == { "cpus": 4.0 }
    assert queue.normalize( { "ranks": 4, "cpus": 2, "gpus": 1 } ) == { "cpus": 8.0, "gpus": 4.0 }   # ( per rank )
    assert queue.normalize( { "ranks": 1 } ) == { }


if test( "the launcher is the environment's `Mpi`, else the mpiexec beside the interpreter" ):
    import errand
    from errand import mpi
    assert mpi.launcher( [ errand.Mpi( "/bin/echo", np = "--ntasks", flags = [ "--x" ] ) ], 4 ) == [ "/bin/echo", "--ntasks", "4", "--x" ]
    assert mpi.launcher( [ errand.Mpi( "no-such-launcher" ) ], 4 ) is None


if test( "inside a Slurm job, srun starts the ranks over the whole allocation, not in errand's own step" ):
    from errand import mpi
    kept = dict( os.environ )
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path( tmp ) / "srun"
        fake.write_text( "#!/bin/sh\n" )
        fake.chmod( 0o755 )
        os.environ.update( SLURM_JOB_ID = "12", SLURM_JOB_NUM_NODES = "2", SLURM_CPUS_PER_TASK = "2",
                           SLURM_NTASKS_PER_NODE = "4", SLURM_STEP_ID = "0", SLURM_PROCID = "0", SLURM_CPU_BIND = "x",
                           PATH = tmp + os.pathsep + os.environ[ "PATH" ] )
        try:
            import errand
            assert f"--mpi=pmix" in mpi.launcher( [ errand.Slurm( mpi = "pmix" ) ], 8 ), "the environment's word wins"
            start = mpi.launcher( [ ], 8 )
            core = start[ start.index( str( fake ) ): ]
            assert core[ 1:3 ] == [ "--overlap", f"--mpi={mpi.plugin()}" ], core
            assert core[ 3: ] == [ "--nodes", "2", "--ntasks-per-node", "4", "--cpus-per-task", "2", "--ntasks", "8" ], core
            unset = set( start[ 2 : start.index( str( fake ) ) : 2 ] )
            assert { "SLURM_STEP_ID", "SLURM_PROCID", "SLURM_CPU_BIND", "SLURM_CPUS_PER_TASK" } <= unset, unset
            assert not unset & { "SLURM_JOB_ID", "SLURM_JOB_NUM_NODES" }, unset
            assert not mpi.inside(), "errand under srun has SLURM_PROCID, and is not a rank for all that"
        finally:
            os.environ.clear()
            os.environ.update( kept )


if test( "inside another batch system, mpiexec starts the ranks here, not through it" ):
    from errand import mpi
    mpiexec = _mpiexec()
    kept = dict( os.environ )
    os.environ.update( PBS_JOBID = "7", PMI_RANK = "0", PATH = os.path.dirname( mpiexec ) + os.pathsep + os.environ[ "PATH" ] )
    os.environ.pop( "SLURM_JOB_ID", None )
    try:
        start = mpi.launcher( [ ], 2 )
        assert start[ 0 ] == "env" and start[ -2: ] == [ "-n", "2" ] and { "PBS_JOBID", "PMI_RANK" } <= set( start[ 2 : -3 : 2 ] ), start
    finally:
        os.environ.clear()
        os.environ.update( kept )


if test( "an allocation is sized from the ranks, the entry's or the command line's" ):
    from errand.cli import aggregate_needs
    from errand.entries import Entry
    entry = lambda **res: Entry( "e", [ ], { }, res, "f.py", 1, "m" )
    assert aggregate_needs( [ entry( ranks = 4 ) ] ) == { "ranks": 4.0 }
    assert aggregate_needs( [ entry() ], { "ranks": 6, "cpus": 2 } ) == { "ranks": 6.0, "cpus": 2.0 }   # ( per rank )


if test( "Slurm asks for one task per rank, and errand runs once in the allocation" ):
    from errand import layers as L
    ctx = lambda **needs: L.Context( root = Path( "/" ), needs = needs )
    slurm = L.Slurm( nodes = 2, ntasks_per_node = 4, time = "10" )
    flags = slurm.flags( ctx( ranks = 8, cpus = 2, gpus = 1, ram = 4096 ) )
    for pair in ( [ "--nodes", "2" ], [ "--ntasks", "8" ], [ "--ntasks-per-node", "4" ], [ "--cpus-per-task", "2" ],
                  [ "--gpus-per-task", "1" ], [ "--mem-per-cpu", "2048M" ] ):
        assert any( flags[ i : i + 2 ] == pair for i in range( len( flags ) ) ), ( pair, flags )
    assert "--ntasks-per-node" not in slurm.flags( ctx() ), "one process: nothing to spread"
    assert slurm.flags( L.Context( root = Path( "/" ), needs = { "ranks": 8 }, phase = "prepare" ) )[ :4 ] == [ "--nodes", "1", "--ntasks", "1" ]
    for bad in ( [ "--ntasks=4" ], [ "-n", "4" ], [ "-n4" ], [ "--ntasks-per-node", "2" ] ):
        try:
            L.Slurm( extra = bad )
            raise AssertionError( f"{bad} was accepted" )
        except ValueError as err:
            assert "ranks" in str( err ), err


# ── ranks started outside a container ───────────────────────────────────────

BOXED = '''
import errand
from dataclasses import dataclass
from errand.layers import Command, Container

@dataclass
class Box( Container ):
    """A container that is not one: it says it was entered."""
    def wrap( self, cmd, ctx ):
        return Command( [ "env", "IN_BOX=1", *cmd.argv ], cmd.env )
    def describe( self ):
        return "box"

errand.envs[ "boxed" ] = errand.Env( [ errand.Mpi( {launcher!r} ), Box() ] )
errand.envs[ "inner" ] = errand.Env( [ Box(), errand.Mpi( {launcher!r} ) ] )
'''

# `launcher -n N cmd…`: N copies of cmd, each told its rank, and which agent started the launcher.
FAKE_MPI = '''#!/bin/sh
n=$2; shift 2; i=0
pids=; rc=0
while [ $i -lt $n ]; do PMI_RANK=$i PMI_SIZE=$n LAUNCHED_BY="$ERRAND_AGENT_DIR" "$@" & pids="$pids $!"; i=$(( i + 1 )); done
for p in $pids; do wait $p || rc=$?; done
exit $rc
'''


def _agent( d: Path, env = None ):
    """An agent serving in `d`, started as errand starts one ( detached ), with `env` in its environment."""
    import subprocess
    import sys
    here = str( Path( __file__ ).resolve().parent.parent )
    subprocess.run( [ sys.executable, "-c", f"from pathlib import Path; from errand.agents import daemon; daemon.start( Path( {str( d )!r} ), 20 )" ],
                    env = { **os.environ, "PYTHONPATH": here, **( env or { } ) }, check = True )
    from errand.agents import endpoint
    import time
    deadline = time.monotonic() + 10
    while endpoint.reach( d ) is None:
        assert time.monotonic() < deadline, ( d / "log" ).read_text() if ( d / "log" ).exists() else "no agent"
        time.sleep( 0.05 )


def _conn( d: Path ):
    import socket
    from errand.agents import client as C, endpoint
    sock = endpoint.reach( d )
    return C.Connection( sock.recv, sock.sendall, lambda: sock.shutdown( socket.SHUT_RDWR ) )


if test( "an agent tells what it starts which agent started it" ):
    from errand.agents import client as C
    with tempfile.TemporaryDirectory( dir = "/tmp" ) as tmp:
        d = Path( tmp ) / "a"
        _agent( d, { "ERRAND_AGENT_DIR": "/somewhere/outer" } )
        got = C.shell( _conn( d ), 'echo "$ERRAND_OUTER_AGENT_DIR $ERRAND_AGENT_DIR"', capture = True )
        assert got.stdout.split() == [ "/somewhere/outer", str( d ) ], got.stdout


if test( "a launcher named before the container starts the ranks outside it, each entering it" ):
    import json
    import subprocess
    import sys
    import errand
    from errand import local, mpi
    with tempfile.TemporaryDirectory( dir = "/tmp" ) as tmp:
        tmp = Path( tmp )
        fake = tmp / "fakempi"
        fake.write_text( FAKE_MPI )
        fake.chmod( 0o755 )
        project = write_project( tmp / "proj", BOXED.format( launcher = str( fake ) ), { } )

        # which launcher: outside for `Mpi` before the container, the container's own after it
        from errand import config
        config.load( project, warn = lambda m: None )
        boxed, inner = ( config.envs[ k ].stack_for( "run" ) for k in ( "boxed", "inner" ) )
        assert mpi.outside( boxed, 2 ) == [ str( fake ), "-n", "2" ]
        assert mpi.outside( inner, 2 ) is None
        assert mpi.outside( [ errand.Mpi( "x" ) ], 2 ) is None                 # no container: as always
        assert mpi.after_outer( boxed ) == [ boxed[ 1 ] ]

        # no agent out there: skipped, saying why
        kept = os.environ.pop( mpi.OUTER, None )
        try:
            mpi.launcher( boxed, 2, { "env": "boxed", "tags": { } } )
            assert False, "no agent outside, and the ranks would have started"
        except local.Skipped as s:
            assert "outside the container" in s.reason, s.reason

        d = tmp / "outer"
        _agent( d )
        os.environ[ mpi.OUTER ] = str( d )
        try:
            start = mpi.launcher( boxed, 2, { "env": "boxed", "tags": { } } )
        finally:
            os.environ.pop( mpi.OUTER )
            if kept is not None:
                os.environ[ mpi.OUTER ] = kept
        assert start[ 1 : 4 ] == [ "-m", "errand.mpi", "through" ], start
        assert json.loads( start[ 4 ] )[ "start" ] == [ str( fake ), "-n", "2" ]

        here = str( Path( __file__ ).resolve().parent.parent )
        rank = "import os; print( 'rank', os.environ[ 'PMI_RANK' ], os.environ.get( 'IN_BOX' ), os.environ.get( 'ERRAND_SAID' ), os.environ.get( 'NOT_SAID' ), os.environ.get( 'LAUNCHED_BY' ) )"
        got = subprocess.run( [ *start, sys.executable, "-c", rank ], cwd = project, capture_output = True, text = True,
                              env = { **os.environ, "PYTHONPATH": here, "ERRAND_SAID": "yes", "NOT_SAID": "no" }, timeout = 60 )
        assert got.returncode == 0, got.stdout + got.stderr
        lines = sorted( l for l in got.stdout.splitlines() if l.startswith( "rank" ) )
        # in the box, errand's variables said, the container's own not, the launcher started by the agent out there
        assert lines == [ f"rank {r} 1 yes None {d}" for r in ( 0, 1 ) ], got.stdout + got.stderr
        assert "outside the container" in got.stdout, got.stdout

        # the exit code comes back
        got = subprocess.run( [ *start, sys.executable, "-c", "import sys; sys.exit( 3 )" ], cwd = project,
                              capture_output = True, text = True, env = { **os.environ, "PYTHONPATH": here }, timeout = 60 )
        assert got.returncode == 3, got.stdout + got.stderr
