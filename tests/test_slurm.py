"""Submitting to a batch system, and letting it decide.

Nothing here names a partition. A cluster already knows which of its
partitions is the default, and that answer stays correct when the cluster is
rearranged, which a name copied out of somebody else's script does not. Name
one in `errand-envs.py` only to override:

    slurm_host      = "login.hpc"     # or reuse ssh_host, if that machine has slurm
    slurm_partition = "gpu"           # optional
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from errand import test, have, need, skip
from errand import layers as L, yamlish

from _infra import LOCALHOST_OPTIONS, run_errand, write_project


# --- what it asks for, with no machine -------------------------------------

def flags( layer, **needs ):
    return layer.flags( L.Context( root = Path( "/" ), needs = needs ) )


if test( "nothing stated is nothing passed", tags = [ "slurm" ] ):
    # An empty errand.Slurm() submits a bare `srun`: the cluster's own defaults, which
    # is what somebody who did not say otherwise meant.
    assert flags( L.Slurm() ) == [ ]
    assert "--partition" not in flags( L.Slurm( gpus = 1 ) )
    assert "--nodes" not in flags( L.Slurm( partition = "gpu" ) )


if test( "a stated partition is used, a missing one is left to slurm", tags = [ "slurm" ] ):
    assert flags( L.Slurm( partition = "gpu" ) )[ : 2 ] == [ "--partition", "gpu" ]
    assert L.Slurm().describe() == "slurm:default partition"
    assert L.Slurm( partition = "gpu" ).describe() == "slurm:gpu"


# --- a real submission ------------------------------------------------------

PROJECT = '''
import errand

errand.configure( exclude = [ "_lib" ] )

errand.envs[ "batch" ] = errand.Env(
     [ errand.Ssh( host = {host!r}, root = {root!r}, options = {options!r} ),
       errand.Slurm( {partition}time = "00:05:00" ),
       errand.Vars( {{ "PYTHONPATH": "{root}/_lib" }} ) ],
     where = "batch" )
'''

WORK = '''
import os, socket
from errand import entry, Param

if p := entry( "allocated", keep = True, bulk = False, n = Param( 1 ) ):
    p.results[ "n" ]   = p.n
    p.results[ "node" ] = socket.gethostname()
    # Set by slurm itself in the environment of the job it starts: proof that
    # this ran inside an allocation rather than on the login node.
    p.results[ "job" ] = os.environ.get( "SLURM_JOB_ID" )
'''


def slurm_target( ):
    """A machine with slurm on it: named, else the ssh host, else localhost."""
    for key in ( "slurm_host", "ssh_host" ):
        if have( key ):
            host = need( key )
            options = need( "ssh_options" ) if have( "ssh_options" ) else [ ]
            if _has_slurm( host, options ):
                return host, options
    if _has_slurm( "localhost", LOCALHOST_OPTIONS ):
        return "localhost", list( LOCALHOST_OPTIONS )
    skip( "no machine with slurm on it",
          "name one in errand-envs.py:\n"
          "    slurm_host = 'login.hpc'\n"
          "  ( ssh_host is tried first, so nothing to add if that machine has slurm )" )


def shared_root( host, options, name ):
    """Somewhere the COMPUTE NODES can see too.

    `/tmp` is node-local on essentially every cluster: a job would land on a
    machine that has never heard of the directory we pushed to. The home
    directory is the one place a batch system can be relied on to share.
    """
    if have( "slurm_root" ):
        return f"{need( 'slurm_root' ).rstrip( '/' )}/{name}"
    got = subprocess.run( [ "ssh", *options, host, "echo $HOME" ],
                          capture_output = True, text = True, timeout = 30 )
    assert got.returncode == 0 and got.stdout.strip(), got.stderr
    return f"{got.stdout.strip()}/.errand-test/{name}"


def _has_slurm( host, options ):
    if shutil.which( "ssh" ) is None:
        return False
    try:
        return subprocess.run( [ "ssh", *options, host, "command -v sinfo" ],
                               stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL,
                               timeout = 30 ).returncode == 0
    except ( OSError, subprocess.SubprocessError ):
        return False


if test( "the cluster's default partition is a real one", tags = [ "slurm" ] ):
    host, options = slurm_target()
    got = subprocess.run( [ "ssh", *options, host, "sinfo -h -o '%P %a'" ],
                          capture_output = True, text = True, timeout = 60 )
    assert got.returncode == 0, got.stderr
    # slurm marks the default with a star; there is always exactly one.
    defaults = [ l.split()[ 0 ] for l in got.stdout.splitlines() if l.strip().startswith( ( "*", ) )
                 or "*" in l.split()[ 0 ] ]
    assert len( defaults ) == 1, f"expected one default partition, got {defaults!r}\n{got.stdout}"
    print( f"  {host}: default partition {defaults[ 0 ]}" )


if test( "a run goes through the queue and comes back", tags = [ "slurm", "slow" ] ):
    host, options = slurm_target()
    partition = f"partition = {need( 'slurm_partition' )!r}, " if have( "slurm_partition" ) else ""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp ) / "proj"
        remote_root = shared_root( host, options, Path( tmp ).name )
        project = write_project(
            root,
            PROJECT.format( host = host, root = remote_root, options = options,
                            partition = partition ),
            { "bench_alloc.py": WORK }, vendor = True )

        try:
            code, output = run_errand( project, "bench_alloc", "--env", "batch" )
        except subprocess.TimeoutExpired:
            skip( "the queue did not give us a node in time",
                  "a busy cluster and a broken setup look the same from here; "
                  "nothing to fix unless it never clears" )
        assert code == 0, output

        leaves = sorted( ( project / "runs" ).rglob( "result.yaml" ) )
        assert len( leaves ) == 1, f"{[ str( p ) for p in leaves ]}\n{output}"
        got = yamlish.read( leaves[ 0 ] )
        assert got[ "status" ] == "PASS", got
        assert got[ "results" ][ "job" ], \
            f"no SLURM_JOB_ID: this ran on the login node, not in an allocation\n{got}"
        print( f"  job {got[ 'results' ][ 'job' ]} on {got[ 'results' ][ 'node' ]}" )

    subprocess.run( [ "ssh", *options, host, f"rm -rf {remote_root}" ] )


if test( "inside an allocation errand does not queue on top", tags = [ "slurm", "slow" ] ):
    host, options = slurm_target()
    # The job's own environment is what says so, so ask slurm for a shell and
    # look. A second queue on top of the cluster's would only wait for itself.
    got = subprocess.run( [ "ssh", *options, host,
                            "srun --time=00:02:00 printenv SLURM_JOB_ID" ],
                          capture_output = True, text = True, timeout = 300 )
    if got.returncode != 0:
        skip( f"srun did not give us a node: {got.stderr.strip()[ : 200 ]}" )
    assert got.stdout.strip().isdigit(), got.stdout

    from errand import queue as Q
    import os
    os.environ[ "SLURM_JOB_ID" ] = got.stdout.strip()
    try:
        assert Q.someone_else_is_scheduling() == "slurm"
    finally:
        del os.environ[ "SLURM_JOB_ID" ]


if test( "--batch submits and comes straight back", tags = [ "slurm", "slow" ] ):
    import time

    from errand import batch as B

    host, options = slurm_target()
    partition = f"partition = {need( 'slurm_partition' )!r}, " if have( "slurm_partition" ) else ""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp ) / "proj"
        remote_root = shared_root( host, options, Path( tmp ).name )
        project = write_project(
            root,
            PROJECT.format( host = host, root = remote_root, options = options,
                            partition = partition ),
            { "bench_alloc.py": WORK }, vendor = True )

        started = time.perf_counter()
        code, output = run_errand( project, "--batch", "bench_alloc", "--env", "batch" )
        handed_back = time.perf_counter() - started
        assert code == 0, output
        # sbatch IS the detachment: it returns as soon as the job is queued,
        # which is why nothing here has to be let go of separately.
        assert handed_back < 90, f"it waited for a node ({handed_back:.1f}s)"

        place = B.load_all( project )[ 0 ][ "places" ][ 0 ]
        assert place[ "kind" ] == "batch", place
        assert place[ "handle" ].isdigit(), place

        def collected( ):
            run_errand( project, "--status" )
            return list( ( project / "runs" ).rglob( "result.yaml" ) )

        deadline = time.time() + 300
        while time.time() < deadline and not collected():
            time.sleep( 3 )

        got = [ yamlish.read( p ) for p in ( project / "runs" ).rglob( "result.yaml" ) ]
        if not got:
            skip( "the queue did not run the job in time",
                  f"job {place[ 'handle' ]} was accepted; a busy cluster looks like this too" )
        assert got[ 0 ][ "status" ] == "PASS", got
        assert got[ 0 ][ "results" ][ "job" ], "it ran outside the allocation"
        print( f"  job {place[ 'handle' ]} -> {got[ 0 ][ 'results' ][ 'node' ]}" )

    subprocess.run( [ "ssh", *options, host, f"rm -rf {remote_root}" ] )
