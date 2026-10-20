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


if test( "under --batch, a preparation submits the run it prepared, from inside its allocation" ):
    env = errand.Env( [ errand.Slurm( cpus = 4, when = "phase=prepare" ),
                        errand.Slurm( gpus = 1, when = "phase=run" ),
                        errand.Apptainer( image = "c.sif" ) ] )
    seen = { }

    def fake_run( argv, **kw ):
        seen[ "argv" ] = argv
        class Done:
            returncode, stdout, stderr = 0, "Submitted batch job 4242", ""
        return Done()

    real = B.subprocess.run
    B.subprocess.run = fake_run
    try:
        got = B.detach( env, { }, [ "run", "--phase", "prepare" ], root = Path( "/proj" ),
                        log = Path( "/tmp/x.log" ), child_env = { }, phase = "prepare",
                        then = [ "run", "--submit-run" ] )
    finally:
        B.subprocess.run = real
    assert got == { "kind": "batch", "handle": "4242" }, got
    argv = seen[ "argv" ]
    assert argv[ 0 ] == "sbatch" and "--cpus-per-task" in argv and "--gpus" not in argv, argv
    script = argv[ argv.index( "--wrap" ) + 1 ]
    # the preparation inside the container, and THEN the submission, outside it
    assert "apptainer exec" in script and "--phase prepare" in script, script
    assert script.index( "--phase prepare" ) < script.index( "--submit-run" ), script
    assert "apptainer" not in script[ script.index( "&&" ) : ], "the submission is outside the container"


if test( "under --batch, the submission takes the interpreter of the environment, not the machine's" ):
    # the machine's `python3` has no errand: the submission goes through the layers that choose an interpreter ( a venv, a
    # micromamba environment ), never through a container
    env = errand.Env( [ errand.Slurm( gpus = 1 ), errand.Venv( python = "/opt/prj/bin/python" ),
                        errand.Apptainer( image = "c.sif" ) ] )
    seen = { }

    def fake_run( argv, **kw ):
        seen[ "argv" ] = argv
        class Done:
            returncode, stdout, stderr = 0, "Submitted batch job 7", ""
        return Done()

    real = B.subprocess.run
    B.subprocess.run = fake_run
    try:
        B.detach( env, { }, [ "run", "--phase", "prepare" ], root = Path( "/proj" ), log = Path( "/tmp/x.log" ), child_env = { },
                  phase = "prepare", then = [ "run", "--submit-run" ] )
    finally:
        B.subprocess.run = real
    script = seen[ "argv" ][ seen[ "argv" ].index( "--wrap" ) + 1 ]
    after = script[ script.index( "&&" ) : ]
    assert "/opt/prj/bin/python -m errand run --submit-run" in after, after
    assert "apptainer" not in after, after


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
        assert "--phase prepare" in output and "--from-plan" in output, output
        assert "who run" in output, "the run phase goes through the run phase's layers"
        plans = list( ( project / ".errand" / "plans" ).glob( "*-two.json" ) )
        assert len( plans ) == 1, plans
        plan = json.loads( plans[ 0 ].read_text() )
        assert [ e[ "name" ] for e in plan[ "entries" ] ] == [ "hello" ], plan


if test( "a run phase that does not find what was prepared refuses to run it" ):
    import os, subprocess, sys
    from errand import cli
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", TWO.format(), { "test_a.py": WORK } )
        # The two phases by hand, as a dispatch would start them: one stamp, inside `two`.
        env = { **os.environ, "ERRAND_STAMP": "2026-01-01_00h00m00", cli.IN_ENV: "two",
                "PYTHONPATH": str( Path( errand.__file__ ).resolve().parent.parent ) }
        phase = lambda *extra: subprocess.run( [ sys.executable, "-m", "errand", "run", *extra, "--no-queue", "**::*" ],
                                               cwd = project, env = env, capture_output = True, text = True )
        got = phase( "--phase", "prepare" )
        assert got.returncode == 0, got.stdout + got.stderr
        ( project / "test_b.py" ).write_text( WORK )            # the sources moved in between
        got = phase( "--from-plan" )
        assert got.returncode == 1 and "not what was prepared" in got.stdout, got.stdout + got.stderr
