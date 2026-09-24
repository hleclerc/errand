"""Layers: folding a command, and noticing an environment has drifted."""
import tempfile
from pathlib import Path

from errand import test
from errand import layers as L, setup
from errand.config import Env


ROOT = Path( "/project" )


def ctx( **tags ):
    return L.Context( root = ROOT, tags = tags )


def folded( stack, **tags ):
    return L.compose( stack, L.Command( [ "python", "-m", "errand", "x" ] ), ctx( **tags ) )


if test( "an empty stack changes nothing" ):
    cmd = folded( [ ] )
    assert cmd.argv == [ "python", "-m", "errand", "x" ] and cmd.env == { }


if test( "vars reach the child" ):
    cmd = folded( [ L.Vars( { "A": "1", "B": 2 } ) ] )
    assert cmd.env == { "A": "1", "B": "2" }          # everything a string, for a process


if test( "a vars layer may read the tags that were selected" ):
    stack = [ L.Vars( lambda t: { "FTYPE": "FP" + t.get( "fp", "64" ) } ) ]
    assert folded( stack, fp = "32" ).env == { "FTYPE": "FP32" }
    assert folded( stack ).env == { "FTYPE": "FP64" }   # the default, when nothing asked


if test( "an interpreter-selecting layer swaps argv[0], and only that" ):
    cmd = folded( [ L.Venv( python = "/v/bin/python" ) ] )
    assert cmd.argv == [ "/v/bin/python", "-m", "errand", "x" ]


if test( "a container brings its own interpreter" ):
    cmd = folded( [ L.Apptainer( image = "c/cuda.sif", flags = [ "--nv" ] ) ] )
    assert cmd.argv[ : 2 ] == [ "apptainer", "exec" ]
    assert "--nv" in cmd.argv
    assert str( ROOT / "c/cuda.sif" ) in cmd.argv
    assert cmd.argv[ -4 : ] == [ "python", "-m", "errand", "x" ]


if test( "the stack reads outside-in" ):
    cmd = folded( [ L.Apptainer( image = "c/cuda.sif" ), L.Vars( { "A": "1" } ) ] )
    assert cmd.argv[ 0 ] == "apptainer"        # the outer layer is outermost
    assert cmd.env == { "A": "1" }             # the inner one still got its say


if test( "ssh refuses to be folded like the others" ):
    try:
        folded( [ L.Apptainer( image = "x.sif" ), L.Ssh( host = "h" ) ] )
    except RuntimeError as err:
        assert "first" in str( err )
    else:
        assert False, "getting to another machine is not a command rewrite"


if test( "a container in the stack is part of where it ran" ):
    assert L.container_of( [ L.Vars( { } ) ] ) is None
    assert L.container_of( [ L.Apptainer( image = "c/cuda.sif" ) ] ) == "cuda.sif"
    assert L.container_of( [ L.Docker( image = "org/img:1" ) ] ) == "org_img-1"


# --- drift ------------------------------------------------------------------

if test( "a fingerprint follows the CONTENTS of what a layer names" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        reqs = root / "requirements.txt"
        reqs.write_text( "numpy\n" )

        e = Env( "x", [ L.Micromamba( "demo", requirements = "requirements.txt" ) ] )
        c = L.Context( root = root )

        before = setup.wanted( e, c )
        assert setup.recorded( root, e ) != before        # nothing built yet

        setup._record( root, e, before )
        assert setup.recorded( root, e ) == before        # ...and now it agrees

        reqs.write_text( "numpy\nscipy\n" )
        assert setup.wanted( e, c ) != before             # the file changed: stale


if test( "a missing file is a fingerprint too, not a crash" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        e = Env( "x", [ L.Micromamba( "demo", requirements = "absent.txt" ) ] )
        got = setup.wanted( e, L.Context( root = root ) )
        assert got and all( isinstance( v, str ) for v in got.values() )


if test( "changing a pip spec is a reason to install again" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        c = L.Context( root = root )
        a = setup.wanted( Env( "x", [ L.Apptainer( image = "i.sif", pip = [ "jax" ] ) ] ), c )
        b = setup.wanted( Env( "x", [ L.Apptainer( image = "i.sif", pip = [ "jax[cuda]" ] ) ] ), c )
        assert a != b


if test( "an environment that declares nothing is never stale" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        e = Env( "x", [ L.Vars( { "A": "1" } ) ] )
        assert setup.status( root, e, L.Context( root = root ) ) == setup.OK


if test( "a batch allocation wraps, it does not replace the interpreter" ):
    cmd = folded( [ L.Slurm( partition = "gpu", gpus = 1, time = "2:00:00" ) ] )
    assert cmd.argv[ 0 ] == "srun"
    assert cmd.argv[ -4 : ] == [ "python", "-m", "errand", "x" ]
    assert "--partition" in cmd.argv and "gpu" in cmd.argv
    # nothing unset becomes a flag: srun would take `--nodes None` literally
    assert "--nodes" not in cmd.argv and "--account" not in cmd.argv


if test( "slurm stacks in front of a container, ssh in front of both" ):
    stack = [ L.Slurm( partition = "gpu" ), L.Apptainer( image = "c/x.sif" ) ]
    cmd = folded( stack )
    assert cmd.argv[ 0 ] == "srun"
    assert "apptainer" in cmd.argv and cmd.argv.index( "apptainer" ) > cmd.argv.index( "srun" )


if test( "a module load needs a shell to exist at all" ):
    # `module` is a shell function, not a program.
    cmd = folded( [ L.Module( "gcc/13", "cuda/12" ) ] )
    assert cmd.argv[ : 2 ] == [ "sh", "-lc" ]
    assert "module load gcc/13" in cmd.argv[ 2 ] and "module load cuda/12" in cmd.argv[ 2 ]
    assert "exec" in cmd.argv[ 2 ]


if test( "nix and guix are the same shape as the rest" ):
    assert folded( [ L.Nix( flake = ".", shell = "dev" ) ] ).argv[ : 4 ] == \
        [ "nix", "develop", ".#dev", "-c" ]
    assert folded( [ L.Guix( packages = [ "python" ] ) ] ).argv[ : 4 ] == \
        [ "guix", "shell", "python", "--" ]


if test( "a batch job on a node-local root is a warning, not a mystery" ):
    # It fails deep in the job, with a chdir complaint from the batch system
    # and then an import error -- nothing that points at the actual cause.
    stack = [ L.Ssh( host = "h", root = "/tmp/proj" ), L.Slurm() ]
    said = L.warnings_for( stack, Path( "/tmp/proj" ) )
    assert said and "node-local" in said[ 0 ] and "shared filesystem" in said[ 0 ]

    assert L.warnings_for( stack, Path( "/home/me/proj" ) ) == [ ]
    # ...and without a batch system, /tmp is nobody's business
    assert L.warnings_for( [ L.Ssh( host = "h" ) ], Path( "/tmp/proj" ) ) == [ ]
