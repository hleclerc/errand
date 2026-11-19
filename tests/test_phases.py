"""Preparing, then running: the preparation's own layers, one pass or two, and the plan between them."""
import json
import tempfile
from pathlib import Path

import errand
from errand import test, batch as B, layers as L

from _infra import run_errand, write_project


def names( stack ):
    return [ l.describe() for l in stack ]


if test( "the preparation goes through `prepare` when it is given, through the run's layers otherwise" ):
    ssh, image = errand.Ssh( "login" ), errand.Apptainer( image = "c.sif" )
    env = errand.Env( [ ssh, errand.Slurm( partition = "gpu", gpus = 1 ), image ],
                      prepare = [ ssh, errand.Slurm( cpus = 16 ), image ] )
    prepare, run = env.stack_for( "prepare" ), env.stack_for( "run" )
    assert prepare[ 1 ].cpus == 16 and run[ 1 ].partition == "gpu"
    assert names( prepare )[ 0 ] == names( run )[ 0 ] == "ssh:login"
    assert prepare[ 2 ] is run[ 2 ], "the container is the same layer in both"
    assert not env.single_pass()
    assert "prepared: ssh:login" in env.describe(), env.describe()
    plain = errand.Env( [ errand.Venv() ] )
    assert plain.stack_for( "prepare" ) == plain.stack_for( "run" )


if test( "a layer takes no condition: `when` is gone" ):
    try:
        errand.Vars( { "A": "1" }, when = "fp=64" )
        raise AssertionError( "`when` was accepted" )
    except TypeError:
        pass


if test( "the preparation may be on another machine: then it is set up there, and carried" ):
    same = errand.Env( [ errand.Ssh( "a" ), errand.Slurm( gpus = 1 ) ], prepare = [ errand.Ssh( "a" ) ] )
    assert not same.prepares_elsewhere() and same.places() == [ same ]
    two = errand.Env( [ errand.Ssh( "gpu-box" ), errand.Venv() ],
                      prepare = [ errand.Ssh( "build-box" ), errand.Uv() ], tools = { "cmake": "cmake3" } )
    assert two.prepares_elsewhere()
    here_then_there = errand.Env( [ errand.Ssh( "gpu-box" ) ], prepare = [ ] )
    assert here_then_there.prepares_elsewhere(), "built here, run there"
    # set up machine by machine, each with its own layers, the tools alike
    places = two.places()
    assert [ L.ssh_of( p.stack ).host for p in places ] == [ "gpu-box", "build-box" ]
    assert all( p.prepare is None and p.tools == { "cmake": "cmake3" } and p.name == two.name for p in places )


if test( "what was built over there is carried to the copy that runs, through here" ):
    from types import SimpleNamespace
    from errand.cli import drive
    calls = [ ]
    kept = drive.L.fetch, drive.L.put
    drive.L.fetch = lambda paths, host, there, local, *a, **k: calls.append( ( "fetch", host, list( paths ), local ) )
    drive.L.put = lambda local, host, remote, *a, **k: calls.append( ( "put", host, str( local ), str( remote ) ) )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path( tmp )
            env = errand.Env( [ ] )
            env.name = "gpu"
            box = lambda host: SimpleNamespace( root = root, there = Path( f"/far/{host}" ),
                                                ssh = SimpleNamespace( host = host, options = [ ], transfer = None ) )
            local = SimpleNamespace( root = root, there = root, ssh = None )
            ( root / "build" / "gpu" ).mkdir( parents = True )

            drive._carry( env, local, box( "run-box" ), root )          # built here, run there
            assert calls == [ ( "put", "run-box", str( root / "build" / "gpu" ), "/far/run-box/build/gpu" ) ], calls

            calls.clear()
            drive._carry( env, box( "build-box" ), local, root )        # built there, run here
            assert calls == [ ( "fetch", "build-box", [ "build/gpu" ], root ) ], calls

            calls.clear()
            staging = errand.config.state( root ) / "carry" / "gpu"
            ( staging / "build" / "gpu" ).mkdir( parents = True )
            drive._carry( env, box( "build-box" ), box( "run-box" ), root )   # two machines: through here
            assert calls == [ ( "fetch", "build-box", [ "build/gpu" ], staging ),
                              ( "put", "run-box", str( staging / "build" / "gpu" ), "/far/run-box/build/gpu" ) ], calls
    finally:
        drive.L.fetch, drive.L.put = kept


if test( "two schedulers in one list is refused, when the environment is declared" ):
    try:
        errand.Env( [ errand.Slurm(), errand.Slurm() ] )
        raise AssertionError( "two schedulers were accepted in the run phase" )
    except ValueError as err:
        assert "2 schedulers" in str( err ) and "prepare = [" in str( err ), err
    try:
        errand.Env( [ ], prepare = [ errand.Slurm(), errand.Slurm() ] )
        raise AssertionError( "two schedulers were accepted in the preparation" )
    except ValueError as err:
        assert "2 schedulers ( in `prepare` )" in str( err ), err


if test( "one pass when both phases are the same layers and nothing is sized from the plan" ):
    assert errand.Env( [ errand.Venv() ] ).single_pass()
    assert errand.Env( [ errand.Ssh( "h" ), errand.Venv() ] ).single_pass()
    assert not errand.Env( [ errand.Slurm() ] ).single_pass(), "a scheduler is sized from the plan"
    assert not errand.Env( [ errand.Venv() ], prepare = [ ] ).single_pass()


if test( "preparing asks a scheduler for one task, sized from nothing" ):
    slurm = errand.Slurm( nodes = 4, time = "1:00:00" )
    needs = { "cpus": 8, "gpus": 2, "exclusive": True }
    run = slurm.flags( L.Context( root = Path( "/" ), needs = needs, phase = "run" ) )
    prepare = slurm.flags( L.Context( root = Path( "/" ), needs = needs, phase = "prepare" ) )
    assert "--nodes" in run and run[ run.index( "--nodes" ) + 1 ] == "4" and "--exclusive" in run
    assert prepare[ prepare.index( "--nodes" ) + 1 ] == "1" and "--ntasks" in prepare
    assert "--exclusive" not in prepare and "--gpus" not in prepare and "--cpus-per-task" not in prepare


if test( "setup keeps every layer of either phase current, once each" ):
    shared = errand.Vars( { } )
    env = errand.Env( [ errand.Uv(), shared ], prepare = [ errand.Venv( python = "/a/python" ), shared ] )
    assert [ ( i, l ) for i, l in env.layers() ] == [ ( 0, env.stack[ 0 ] ), ( 1, shared ), ( 2, env.prepare[ 0 ] ) ]


def _where( ):
    from types import SimpleNamespace
    return SimpleNamespace( root = Path( "/proj" ), ssh = None, there = Path( "/proj" ), cache = None,
                            boot = "/errand/_boot.py" )


if test( "a session is reached by its agent, in an allocation through its agent, or by watching a job" ):
    from errand.cli.drive import Reach
    kind = lambda layers, phase = "run", prepare = None: Reach( errand.Env( layers, prepare ), { }, phase, _where() ).kind
    assert kind( [ errand.Venv( python = "/opt/prj/bin/python" ) ] ) == "agent"
    assert kind( [ errand.Slurm( gpus = 1 ), errand.Venv( python = "/opt/prj/bin/python" ) ] ) == "alive", \
        "held warm a short while by default: the run finds the allocation its preparation had"
    assert kind( [ errand.Slurm( gpus = 1, keep_alive = 0 ), errand.Venv( python = "/opt/prj/bin/python" ) ] ) == "alive", \
        "an allocation for one command: through its agent as well ( ADR 0009 )"
    assert kind( [ errand.Slurm( watch = 60, time = "1:00:00" ) ] ) == "watched"
    assert kind( [ errand.Slurm() ], "prepare", prepare = [ ] ) == "agent", "prepared outside the allocation"


if test( "under --batch, the run is submitted through the run's layers, sized from the plan" ):
    from errand.cli.drive import Reach
    image = errand.Apptainer( image = "c.sif" )
    env = errand.Env( [ errand.Slurm(), image ], prepare = [ errand.Slurm( cpus = 4 ), image ] )
    reach = Reach( env, { }, "run", _where(), needs = { "gpus": 1 }, batch = True )
    line = reach.line( { "verb": "run" }, { "ERRAND_IN_ENV": "x" } )
    argv = reach.wrapped.argv
    assert argv[ 0 ] == "sbatch" and "--gpus" in argv and "--cpus-per-task" not in argv, argv
    script = argv[ argv.index( "--wrap" ) + 1 ]
    # the session, inside the container, from the copy of errand the container sees
    assert "apptainer exec" in script and "-m errand.agents.ops session" in script, script
    assert line.startswith( "cd /proj && sbatch" ), line


TWO = '''
import errand
errand.envs[ "two" ] = errand.Env( [ errand.Venv(), errand.Vars( {{ "WHO": "run" }} ) ],
                                   prepare = [ errand.Vars( {{ "WHO": "prep" }} ) ] )
'''

WORK = '''
import os
from errand import test
if test( "hello" ):
    print( "who", os.environ.get( "WHO" ) )
'''


if test( "two passes: the preparation writes the plan, the run checks it and runs it", tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", TWO.format(), { "test_a.py": WORK } )
        code, output = run_errand( project, "run", "--no-queue", "--env", "two", "**::*" )
        assert code == 0, output
        # prepared on its own, by the preparation's layers ( its plan, below ), then run by the run's
        # ( through their agents ); errand no longer says it prepared ( ADR 0016: its work is transient )
        assert "who run" in output, "the run phase goes through the run phase's layers"
        plans = list( ( project / "errand-outputs" / "state" / "plans" ).glob( "*-two.json" ) )
        assert len( plans ) == 1, plans
        plan = json.loads( plans[ 0 ].read_text() )
        assert [ e[ "name" ] for e in plan[ "entries" ] ] == [ "hello" ], plan


if test( "a run phase that does not find what was prepared refuses to run it" ):
    import json, os, subprocess, sys
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", TWO.format(), { "test_a.py": WORK } )
        known = { "pattern": "**::*", "target_args": [ ], "no_queue": True, "from_default": False }
        env = { **os.environ, "ERRAND_STAMP": "2026-01-01_00h00m00",
                "PYTHONPATH": str( Path( errand.__file__ ).resolve().parent.parent ) }

        def session( **kw ):
            req = { "root": str( project ), "env": "two", "tags": { }, "verb": "run",
                    **kw, "known": { **known, **kw.pop( "known", { } ) } }
            return subprocess.run( [ sys.executable, "-m", "errand.agents.ops", "session", json.dumps( req ) ],
                                   cwd = project, env = env, capture_output = True, text = True )

        got = session( prepare_only = True, known = { "phase": "prepare" } )
        assert got.returncode == 0, got.stdout + got.stderr
        # prepared on another machine, the plan comes with the request: the run checks against it, and keeps it
        plans = project / "errand-outputs" / "state" / "plans"
        plan = json.loads( next( plans.glob( "*-two.json" ) ).read_text() )
        for f in plans.glob( "*" ):
            f.unlink()
        got = session( known = { "phase": "run", "from_plan": True, "plan": plan } )
        assert got.returncode == 0 and "who run" in got.stdout, got.stdout + got.stderr
        assert list( plans.glob( "*-two.json" ) ), "kept where the run is, for status"
        ( project / "test_b.py" ).write_text( WORK )            # the sources moved in between
        got = session( known = { "phase": "run", "from_plan": True } )
        assert got.returncode == 1 and "not what was prepared" in got.stdout, got.stdout + got.stderr
