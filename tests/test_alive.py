"""A Slurm allocation held warm ( `keep_alive` ): its shape, without a cluster.

The real thing -- an allocation reused between commands, ranks over two nodes from the first,
a layer built inside it, the allocation let go of on its own -- is exercised on a cluster named in
errand-envs.py, by hand ( `ERRAND_AGENT=hub errand run --env <warm env>` twice, then `squeue` ).
"""
from pathlib import Path
from types import SimpleNamespace

import errand
from errand import test


def where( ):
    return SimpleNamespace( root = Path( "/proj" ), ssh = errand.Ssh( host = "cluster", root = "/scratch/proj" ),
                            there = Path( "/scratch/proj" ), home = "/home/me", boot = "/home/me/_boot.py" )


if test( "a scheduler held warm is reached through an agent in its allocation, not by srun each time" ):
    from errand.cli.drive import Reach
    warm = errand.Env( [ errand.Ssh( host = "cluster" ), errand.Slurm( keep_alive = "30m" ) ] )
    cold = errand.Env( [ errand.Ssh( host = "cluster" ), errand.Slurm() ] )
    assert Reach( warm, { }, "run", where() ).kind == "alive"
    assert Reach( cold, { }, "run", where() ).kind == "command"
    assert Reach( warm, { }, "run", where(), batch = True ).kind == "command", "--batch lets go: nothing to keep"


if test( "the allocation is an sbatch whose batch step is an agent, reached by srun --overlap" ):
    from errand.cli.alive import Allocation
    env = errand.Env( [ errand.Ssh( host = "cluster" ),
                        errand.Slurm( nodes = 2, ntasks_per_node = 4, time = "1:00:00", keep_alive = "30m" ) ] )
    a = Allocation( env, { }, where() )
    assert a.keep == 1800
    assert "--ntasks" in a.flags and a.flags[ a.flags.index( "--ntasks" ) + 1 ] == "8", "ranks fit: nodes x per node"
    script = a.script()
    assert "sbatch --parsable" in script and "-m errand.agents serve" in script
    assert "srun -u --jobid=" in script and "--overlap" in script, "unbuffered: frames are not lines"
    assert a.dir.startswith( "/home/me/.cache/errand/alloc/" )


if test( "the environment agent is started inside it, through the layers after the scheduler" ):
    from errand.cli.alive import Allocation
    env = errand.Env( [ errand.Ssh( host = "cluster" ), errand.Slurm( keep_alive = "30m" ),
                        errand.Venv( python = "/tmp/node/bin/python" ) ] )
    target = Allocation( env, { }, where() ).env_target()
    line = target[ "argv" ][ -1 ]
    assert "/tmp/node/bin/python" in line and "errand.agents connect" in line, line
    assert '"$SLURM_JOB_ID"' in line, "its directory is the job's"


if test( "setup builds what comes after a scheduler held warm inside the allocation, and the rest where it was" ):
    from errand import setup
    venv = errand.Venv( python = "/tmp/node/bin/python", create = True )
    before = errand.Venv( python = "/login/bin/python" )
    env = errand.Env( [ before, errand.Slurm( keep_alive = "30m" ), venv ] )
    reached = [ ]

    class Fake:
        def __init__( self, *a, **k ):
            pass

        def inside( self ):
            reached.append( True )
            return "INSIDE"

    import errand.cli.alive as A
    kept, A.Allocation = A.Allocation, Fake
    try:
        inside = setup._inside( env, errand.layers.Context( root = Path( "/proj" ) ) )
        assert inside( before ) is None
        assert inside( venv ) == "INSIDE" and inside( venv ) == "INSIDE"
        assert reached == [ True ], "the allocation is reached once"
    finally:
        A.Allocation = kept
