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
                            there = Path( "/scratch/proj" ), cache = "/home/me/.cache/errand", boot = "/home/me/_boot.py" )


if test( "a scheduler held warm is reached through an agent in its allocation, not by srun each time" ):
    from errand.cli.drive import Reach
    warm = errand.Env( [ errand.Ssh( host = "cluster" ), errand.Slurm( keep_alive = "30m" ) ] )
    cold = errand.Env( [ errand.Ssh( host = "cluster" ), errand.Slurm( keep_alive = 0 ) ] )
    short = errand.Env( [ errand.Ssh( host = "cluster" ), errand.Slurm() ] )
    assert Reach( warm, { }, "run", where() ).kind == "alive"
    assert Reach( cold, { }, "run", where() ).kind == "command"
    assert Reach( short, { }, "run", where() ).kind == "alive" and Reach( short, { }, "prepare", where() ).kind == "alive"
    from errand.cli import alive
    assert alive.seconds( short.stack[ 1 ] ) == 60 and alive.seconds( warm.stack[ 1 ] ) == 1800
    assert Reach( warm, { }, "run", where(), batch = True ).kind == "command", "--batch lets go: nothing to keep"


if test( "the preparation and the run find the same allocation, and so does another environment through it" ):
    from errand.cli.alive import Allocation
    slurm = errand.Slurm( cpus = 10, time = "0:10:00", extra = [ "--gres=gpu:1" ] )
    a = errand.Env( [ errand.Ssh( host = "cluster" ), slurm, errand.Venv( python = "/a/bin/python" ) ] )
    a.name = "a"
    b = errand.Env( [ errand.Ssh( host = "cluster" ), slurm, errand.Venv( python = "/b/bin/python" ) ] )
    b.name = "b"
    prepare, run = Allocation( a, { }, where(), "prepare" ), Allocation( a, { }, where(), "run" )
    assert prepare.name == run.name and "--gres=gpu:1" in prepare.flags, "sized from the declaration in both phases"
    other = Allocation( b, { }, where() )
    assert other.name == run.name, "A -> B -> C and A -> B -> D share A -> B"
    assert other.env_target()[ "id" ] != run.env_target()[ "id" ], "each with an environment agent of its own"


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


if test( "a command runs in the allocation kept warm only if it fits in it: never an srun beyond it" ):
    from errand.cli.alive import Allocation, fits, _left
    env = errand.Env( [ errand.Ssh( host = "cluster" ),
                        errand.Slurm( nodes = 2, ntasks_per_node = 2, cpus = 4, gpus = 1, time = "0:30:00",
                                      keep_alive = "10m" ) ] )
    a = Allocation( env, { }, where() )
    assert fits( a, { "ranks": 4, "cpus": 4, "gpus": 1 } ) == ( True, None )
    assert not fits( a, { "ranks": 8 } )[ 0 ], "more ranks than tasks"
    assert not fits( a, { "cpus": 8 } )[ 0 ] and not fits( a, { "gpus": 2 } )[ 0 ], "more per task than allocated"
    assert not fits( a, { "exclusive": True } )[ 0 ], "the machine to itself, in a shared allocation"
    assert not fits( a, { }, time = "1:00:00" )[ 0 ], "longer than the job it would be"

    class Squeue:                                   # the job is running, with 9 minutes left
        def shell( self, line, **kw ):
            return SimpleNamespace( stdout = "RUNNING 9:00\n", returncode = 0 )

    assert fits( a, { }, time = "0:05:00", host = Squeue() )[ 0 ]
    assert not fits( a, { }, time = "0:10:00", host = Squeue() )[ 0 ], "longer than what the job has left"
    assert _left( "1-02:03:04" ) == 93784 and _left( "05:00" ) == 300 and _left( "UNLIMITED" ) is None
