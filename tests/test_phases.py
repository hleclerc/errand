"""Preparing, then running: layers with conditions, one pass or two, and the plan between them."""
import json
import tempfile
from pathlib import Path

import errand
from errand import test, batch as B, layers as L

from _infra import run_errand, write_project


def names( stack ):
    return [ l.describe() for l in stack ]


if test( "a layer with `when` is in the phases its condition holds in, one without in both" ):
    env = errand.Env( [ errand.Ssh( "login" ),
                        errand.Slurm( cpus = 16, when = "phase=prepare" ),
                        errand.Slurm( partition = "gpu", gpus = 1, when = "phase=run" ),
                        errand.Apptainer( image = "c.sif" ) ] )
    prepare, run = env.stack_for( "prepare" ), env.stack_for( "run" )
    assert prepare[ 1 ].cpus == 16 and run[ 1 ].partition == "gpu"
    assert names( prepare )[ 0 ] == names( run )[ 0 ] == "ssh:login"
    assert prepare[ 2 ] is run[ 2 ], "the container is the same layer in both"
    assert not env.single_pass()


if test( "a condition reads the selected tags too" ):
    env = errand.Env( [ errand.Vars( { "A": "1" }, when = "fp=64" ), errand.Venv() ] )
    assert len( env.stack_for( "run", { "fp": "64" } ) ) == 2
    assert len( env.stack_for( "run", { "fp": "32" } ) ) == 1


if test( "two schedulers in one phase is refused, when the environment is declared" ):
    try:
        errand.Env( [ errand.Slurm(), errand.Slurm( when = "phase=run" ) ] )
        raise AssertionError( "two schedulers were accepted in the run phase" )
    except ValueError as err:
        assert "2 schedulers in the run phase" in str( err ), err
    try:
        errand.Env( [ ], phase = "run" )
        raise AssertionError( "`phase` was accepted as a tag" )
    except ValueError as err:
        assert "not a tag" in str( err ), err


if test( "one pass when both phases are the same layers and nothing is sized from the plan" ):
    assert errand.Env( [ errand.Venv() ] ).single_pass()
    assert errand.Env( [ errand.Ssh( "h" ), errand.Venv() ] ).single_pass()
    assert not errand.Env( [ errand.Slurm() ] ).single_pass(), "a scheduler is sized from the plan"
    assert not errand.Env( [ errand.Venv( when = "phase=run" ) ] ).single_pass()


if test( "preparing asks a scheduler for one task, sized from nothing" ):
    slurm = errand.Slurm( nodes = 4, time = "1:00:00" )
    needs = { "cpus": 8, "gpus": 2, "exclusive": True }
    run = slurm.flags( L.Context( root = Path( "/" ), needs = needs, phase = "run" ) )
    prepare = slurm.flags( L.Context( root = Path( "/" ), needs = needs, phase = "prepare" ) )
    assert "--nodes" in run and run[ run.index( "--nodes" ) + 1 ] == "4" and "--exclusive" in run
    assert prepare[ prepare.index( "--nodes" ) + 1 ] == "1" and "--ntasks" in prepare
    assert "--exclusive" not in prepare and "--gpus" not in prepare and "--cpus-per-task" not in prepare


if test( "setup keeps every layer of either phase current" ):
    env = errand.Env( [ errand.Venv( python = "/a/python", when = "phase=prepare" ),
                        errand.Uv( when = "phase=run" ), errand.Vars( { }, when = "never" ) ] )
    assert [ i for i, _ in env.indexed() ] == [ 0, 1 ]


def _where( ):
    from types import SimpleNamespace
    return SimpleNamespace( root = Path( "/proj" ), ssh = None, there = Path( "/proj" ), cache = None,
                            boot = "/errand/_boot.py" )


if test( "a session is reached by its agent, by a command through a scheduler, or by watching a job" ):
    from errand.cli.drive import Reach
    kind = lambda layers, phase = "run": Reach( errand.Env( layers ), { }, phase, _where() ).kind
    assert kind( [ errand.Venv( python = "/opt/prj/bin/python" ) ] ) == "agent"
    assert kind( [ errand.Slurm( gpus = 1 ), errand.Venv( python = "/opt/prj/bin/python" ) ] ) == "command"
    assert kind( [ errand.Slurm( watch = 60, time = "1:00:00" ) ] ) == "watched"
    assert kind( [ errand.Slurm( when = "phase=run" ) ], "prepare" ) == "agent", "prepared outside the allocation"


if test( "under --batch, the run is submitted through the run's layers, sized from the plan" ):
    from errand.cli.drive import Reach
    env = errand.Env( [ errand.Slurm( cpus = 4, when = "phase=prepare" ),
                        errand.Slurm( when = "phase=run" ),
                        errand.Apptainer( image = "c.sif" ) ] )
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
errand.envs[ "two" ] = errand.Env( [ errand.Vars( {{ "WHO": "prep" }}, when = "phase=prepare" ),
                                     errand.Venv( when = "phase=run" ),
                                     errand.Vars( {{ "WHO": "run" }}, when = "phase=run" ) ] )
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
        # prepared on its own, by the preparation's layers, then run by the run's ( through their agents )
        assert "prepared 1 entry in two" in output, output
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
            req = { "root": str( project ), "env": "two", "tags": { }, "verb": "run", "kinds": [ ],
                    **kw, "known": { **known, **kw.pop( "known", { } ) } }
            return subprocess.run( [ sys.executable, "-m", "errand.agents.ops", "session", json.dumps( req ) ],
                                   cwd = project, env = env, capture_output = True, text = True )

        got = session( prepare_only = True, known = { "phase": "prepare" } )
        assert got.returncode == 0, got.stdout + got.stderr
        ( project / "test_b.py" ).write_text( WORK )            # the sources moved in between
        got = session( known = { "phase": "run", "from_plan": True } )
        assert got.returncode == 1 and "not what was prepared" in got.stdout, got.stdout + got.stderr
