"""Layers: folding a command, and noticing an environment has drifted."""
import os
import subprocess
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

        e = Env.make( "x", [ L.Micromamba( "demo", requirements = "requirements.txt" ) ] )
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
        e = Env.make( "x", [ L.Micromamba( "demo", requirements = "absent.txt" ) ] )
        got = setup.wanted( e, L.Context( root = root ) )
        assert got and all( isinstance( v, str ) for v in got.values() )


if test( "changing a pip spec is a reason to install again" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        c = L.Context( root = root )
        a = setup.wanted( Env.make( "x", [ L.Apptainer( image = "i.sif", pip = [ "jax" ] ) ] ), c )
        b = setup.wanted( Env.make( "x", [ L.Apptainer( image = "i.sif", pip = [ "jax[cuda]" ] ) ] ), c )
        assert a != b


if test( "an environment that declares nothing is never stale" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        e = Env.make( "x", [ L.Vars( { "A": "1" } ) ] )
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


if test( "a module load passes on the variables of the layers after it" ):
    # `exec A=1 prog` is `exec` looking for a program named `A=1`
    import subprocess
    cmd = L.compose( [ L.Module( "x" ), L.Vars( { "A": "1" } ) ],
                     L.Command( [ "sh", "-c", 'echo "$A"' ] ), ctx() )
    line = cmd.argv[ 2 ].replace( "module load x", "true" )
    assert subprocess.run( [ "sh", "-c", line ], capture_output = True, text = True ).stdout == "1\n"


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


if test( "an environment that is already there is adopted, never recreated" ):
    # The costly mistake this stands against: `micromamba create -y -n vfs
    # python=3.13` run over a vfs that EXISTS, on somebody's first errand
    # command, because nothing had ever been recorded about it. It resolved
    # python 3.13 into a 3.14 environment and took numpy, jax and every
    # editable install out with it.
    class Fake:
        def __init__( self, present ):
            self.present, self.built = present, 0

        def describe( self ): return "fake"
        def spec( self, ctx ): return [ "3.13" ]
        def probe( self, ctx ): return self.present

        def build( self, ctx ):
            self.built += 1
            return [ "true" ]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        c = L.Context( root = root )

        there = Fake( present = True )
        assert setup.ensure( root, Env.make( "x", [ there ] ), c, echo = lambda s: None ) == 0
        assert there.built == 0, "present and never seen before is not a reason to build"
        # ...and it is recorded, so it does not stay `stale` forever.
        assert setup.recorded( root, Env.make( "x", [ there ] ) ) == setup.wanted( Env.make( "x", [ there ] ), c )
        # Saying it out loud still does it.
        assert setup.ensure( root, Env.make( "x", [ there ] ), c, force = True,
                             echo = lambda s: None ) == 0
        assert there.built == 1

        missing = Fake( present = False )
        assert setup.ensure( root, Env.make( "y", [ missing ] ), c, echo = lambda s: None ) == 0
        assert missing.built == 1, "what is not there IS built, first sight or not"


if test( "micromamba installs into what exists and creates only what does not" ):
    class Probed( L.Micromamba ):
        present = False

        def probe( self, ctx ):
            return self.present

    with tempfile.TemporaryDirectory() as tmp:
        c = L.Context( root = Path( tmp ) )
        made = Probed( "demo", python = "3.13" )
        made.present = False
        assert any( "create" in s for s in made.build( c ) )
        made.present = True
        steps = made.build( c )
        assert steps and all( "create" not in s for s in steps ), steps
        assert any( "install" in s for s in steps ), steps


if test( "micromamba where it is not on PATH: the binary and the prefix are declared" ):
    # A command sent to a compute node by `srun` reads no rc file: neither
    # `micromamba` nor MAMBA_ROOT_PREFIX exist there unless they are spelled out.
    there = L.Context( root = Path( "/there" ), remote = True )
    m = L.Micromamba( "demo", executable = "/w/bin/micromamba", root_prefix = "/w/.mamba" )
    made = m.wrap( L.Command( [ "python", "-c", "1" ] ), there )
    assert made.argv[ : 5 ] == [ "/w/bin/micromamba", "--root-prefix", "/w/.mamba", "-n", "demo" ], made.argv
    assert m.probe_shell( there ).startswith( "/w/bin/micromamba --root-prefix /w/.mamba" )

    # Over there, nothing guessed from this machine's home leaks into the command.
    assert L.Micromamba( "demo" ).wrap( L.Command( [ "python" ] ), there ).argv[ :3 ] == [ "micromamba", "-n", "demo" ]

    # ...and whether to create or install is decided over there, not here --
    # after fetching the binary itself, which a fresh account does not have.
    steps = m.build( there )
    assert steps[ 0 ] == L.fetch_micromamba( "/w/bin/micromamba" ), steps
    assert steps[ 1 ].startswith( "if /w/bin/micromamba" ) and "create" in steps[ 1 ], steps

    # A bare `micromamba` says nowhere to put it: nothing is fetched.
    assert all( "micro.mamba.pm" not in s for s in L.Micromamba( "demo" ).build( there ) )


if test( "a declared micromamba that is not there is fetched first" ):
    with tempfile.TemporaryDirectory() as tmp:
        exe = f"{ tmp }/bin/micromamba"
        steps = L.Micromamba( "demo", executable = exe ).build( L.Context( root = Path( tmp ) ) )
        assert steps[ 0 ] == L.fetch_micromamba( exe ) and "create" in steps[ 1 ], steps

        # The line itself, with a stand-in for the download: the platform is
        # put in the url, the binary lands executable where it was declared.
        fake = Path( tmp ) / "fake"
        ( fake / "bin" ).mkdir( parents = True )
        ( fake / "bin" / "micromamba" ).write_text( "#!/bin/sh\necho mm\n" )
        subprocess.run( [ "tar", "-cjf", f"{ tmp }/mm.tar.bz2", "-C", str( fake ), "bin/micromamba" ], check = True )
        ( fake / "curl" ).write_text( f"#!/bin/sh\necho \"$2\" > { tmp }/url\ncat { tmp }/mm.tar.bz2\n" )
        ( fake / "curl" ).chmod( 0o755 )
        env = { **os.environ, "PATH": f"{ fake }:{ os.environ[ 'PATH' ] }" }
        line = L.fetch_micromamba( exe )
        assert subprocess.run( line, shell = True, env = env ).returncode == 0
        assert subprocess.run( [ exe ], capture_output = True, text = True ).stdout == "mm\n"
        url = Path( tmp, "url" ).read_text().strip()
        assert url.startswith( "https://micro.mamba.pm/api/micromamba/" ) and "{" not in url, url

        # There: not fetched again.
        os.remove( f"{ tmp }/url" )
        assert subprocess.run( line, shell = True, env = env ).returncode == 0
        assert not os.path.exists( f"{ tmp }/url" )


if test( "what errand has never recorded is not announced as stale" ):
    class There:
        def describe( self ): return "there"
        def spec( self, ctx ): return [ "3.13" ]
        def probe( self, ctx ): return True
        def build( self, ctx ): return [ "true" ]

    with tempfile.TemporaryDirectory() as tmp:
        root, c = Path( tmp ), L.Context( root = Path( tmp ) )
        e = Env.make( "x", [ There() ] )
        # It is going to be adopted, not rebuilt: saying `stale` would announce
        # work that is not about to happen.
        assert setup.status( root, e, c ) == setup.OK
        setup._record( root, e, { "0:there": "something else" } )
        assert setup.status( root, e, c ) == setup.STALE


if test( "the interpreter is substituted; anything else is a command of its own" ):
    # `errand shell --env gpu -- python -m loom.toolchain` has to run the venv's
    # python; `errand shell --env gpu -- nvidia-smi` must NOT become `python
    # nvidia-smi`, which is what replacing the first word blindly did.
    assert L.under( [ "python", "-c", "1" ], "/opt/py" ) == [ "/opt/py", "-c", "1" ]
    assert L.under( [ "/usr/bin/python3", "-m", "x" ], "/opt/py" ) == [ "/opt/py", "-m", "x" ]
    assert L.under( [ "nvidia-smi", "-L" ], "/opt/py" ) == [ "nvidia-smi", "-L" ]

    made = L.Micromamba( "demo" ).wrap( L.Command( [ "nvidia-smi" ] ), L.Context( root = Path( "." ) ) )
    assert made.argv[ -1 ] == "nvidia-smi" and "python" not in made.argv, made.argv


if test( "an image says how it is built, not only how it is entered" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        c = L.Context( root = root )

        plain = L.Apptainer( image = "c/i.sif", recipe = "c/i.def" ).build( c )
        assert plain and "--fakeroot" not in plain[ 0 ], plain

        # Without root on a host that allows it, and unpacking somewhere with
        # room -- /tmp is where a build dies halfway on a shared machine.
        fancy = L.Apptainer( image = "c/i.sif", recipe = "c/i.def", fakeroot = True,
                             scratch = "/data/scratch",
                             build_flags = [ "--nv" ] ).build( c )
        step = fancy[ 0 ]
        assert "--fakeroot" in step and "--nv" in step, step
        assert step.startswith( "APPTAINER_TMPDIR=/data/scratch "
                                "APPTAINER_CACHEDIR=/data/scratch apptainer build" ), step

        # And it is part of what makes the image stale: changing the scratch
        # directory is not a reason to rebuild, changing the recipe is.
        a = L.Apptainer( image = "c/i.sif", recipe = "c/i.def" )
        b = L.Apptainer( image = "c/i.sif", recipe = "c/i.def", fakeroot = True )
        assert L.fingerprint( *a.spec( c ) ) != L.fingerprint( *b.spec( c ) )


if test( "over ssh, `is it there` is asked of the machine it would be built on" ):
    # An image built on the cluster last week does not exist here; one sitting
    # here does not exist there. Answering against the wrong filesystem means
    # rebuilding on every command, or never building at all.
    c = L.Context( root = Path( "/here" ) )
    assert L.Apptainer( image = "c/i.sif" ).probe_shell( c ) == "test -e c/i.sif", \
           L.Apptainer( image = "c/i.sif" ).probe_shell( c )
    there = L.Context( root = Path( "/there" ), remote = True )
    assert "micromamba -n demo run true" == L.Micromamba( "demo" ).probe_shell( there )

    asked = [ ]

    far = L.Ssh( host = "over-there", root = "/there" )

    class Image:
        def __init__( self, answer ):
            self.answer, self.built = answer, 0

        def describe( self ): return "image"
        def spec( self, ctx ): return [ "r" ]
        def probe( self, ctx ): return True          # here, and beside the point
        def probe_shell( self, ctx ): return "test -e i.sif"

        def build( self, ctx ):
            self.built += 1
            return [ "true" ]

    def answering( code ):
        def shell( self, line, *, quiet = False, tty = False, capture = False ):
            asked.append( ( line, quiet ) )
            return subprocess.CompletedProcess( line, code if line == "test -e i.sif" else 0 )
        return shell

    kept, pushed = L.Over.shell, L.push
    L.push = lambda *a, **kw: None          # no rsync to a host that does not exist
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path( tmp )
            layer = Image( answer = 1 )
            e = Env.make( "far", [ far, layer ] )
            L.Over.shell = answering( 1 )               # not there
            setup.ensure( root, e, L.Context( root = root ), echo = lambda s: None )
            assert layer.built == 1, "absent over there: it gets built, first sight or not"
            assert ( "test -e i.sif", True ) in asked, asked

            layer = Image( answer = 0 )
            e = Env.make( "far2", [ far, layer ] )
            L.Over.shell = answering( 0 )               # already there
            setup.ensure( root, e, L.Context( root = root ), echo = lambda s: None )
            assert layer.built == 0, "there already: adopted, like anywhere else"
    finally:
        L.Over.shell, L.push = kept, pushed


if test( "an image built where there is internet, entered where there is none" ):
    # A national cluster has no internet at all: its image is built on a machine
    # that has some, then copied over, then put where the site executes images from.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        c = L.Context( root = root )
        layer = L.Apptainer( image = "c/i.sif", recipe = "c/i.def", fakeroot = True,
                             build_on = L.Ssh( host = "builder", root = "/b/proj" ),
                             install = "idrcontmgr cp {image}", exe = "singularity" )
        steps = layer.build( c )
        assert len( steps ) == 2 and callable( steps[ 0 ] ), steps
        assert "on builder" in str( steps[ 0 ] ) and "apptainer build --force --fakeroot" in str( steps[ 0 ] ), str( steps[ 0 ] )
        assert steps[ 1 ] == "idrcontmgr cp c/i.sif", steps[ 1 ]
        # where it is built does not change what is built
        plain = L.Apptainer( image = "c/i.sif", recipe = "c/i.def", fakeroot = True )
        assert L.fingerprint( *layer.spec( c ) ) == L.fingerprint( *plain.spec( c ) )

        # entered from the site's own place, the arguments passed on untouched
        enter = L.Apptainer( image = "c/i.sif", exe = "singularity", flags = [ "--nv" ],
                             run_from = "$ALLOWED/i.sif" )
        cmd = L.compose( [ enter ], L.Command( [ "python", "-c", "print( 'a b' )" ] ), c )
        assert cmd.argv[ : 2 ] == [ "sh", "-c" ], cmd.argv
        assert cmd.argv[ 2 ] == 'exec singularity exec --nv $ALLOWED/i.sif "$@"', cmd.argv[ 2 ]
        assert cmd.argv[ 3 : ] == [ "sh", "python", "-c", "print( 'a b' )" ], cmd.argv
        out = subprocess.run( [ "sh", "-c", 'echo "$@"', "sh", *cmd.argv[ 4 : ] ], capture_output = True, text = True )
        assert out.stdout == "python -c print( 'a b' )\n", out.stdout


if test( "the built image is streamed from the builder, never left half-copied" ):
    # `ssh HOST LINE` stood in for by a script that runs LINE here
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path( tmp )
        bin_ = tmp / "bin"; bin_.mkdir()
        ( bin_ / "ssh" ).write_text( '#!/bin/sh\nshift\nexec sh -c "$1"\n' )
        ( bin_ / "ssh" ).chmod( 0o755 )
        builder = tmp / "builder"; ( builder / "c" ).mkdir( parents = True )
        ( builder / "c" / "i.sif" ).write_bytes( b"\0image" * 1000 )
        dest = tmp / "dest"; dest.mkdir()
        path = os.environ[ "PATH" ]
        os.environ[ "PATH" ] = f"{bin_}:{path}"
        try:
            src = L.Over( L.Ssh( host = "builder" ), builder )
            assert L.relay( src, builder / "c" / "i.sif", L.Here( dest ), "c/i.sif" ) == 0
            assert ( dest / "c" / "i.sif" ).read_bytes() == b"\0image" * 1000
            assert not ( dest / "c" / "i.sif.part" ).exists()
            # a source that is not there fails, and leaves nothing to be taken for an image
            assert L.relay( src, builder / "c" / "none.sif", L.Here( dest ), "c/none.sif" ) != 0
            assert not ( dest / "c" / "none.sif" ).exists()
        finally:
            os.environ[ "PATH" ] = path
