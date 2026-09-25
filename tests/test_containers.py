"""Running inside a container, whichever engine this machine has.

The shape of the command is checked everywhere, with no engine at all. The
round trip through a real container is checked with whatever answers here --
apptainer, docker or podman -- and skipped, saying which is which, when none
does. An engine that is installed but not answering is a different problem
from one that is absent, and the skip says so.

Nothing below wants a GPU, a private registry or a prepared machine: the image
is python:3-slim and the work is arithmetic.
"""
import os
import subprocess
import tempfile
from pathlib import Path

from errand import test, bench, Param
from errand import layers as L

from _infra import BASE_IMAGE, container_engine, container_engines, run_errand, write_project


ROOT = Path( "/project" )


def folded( layer ):
    return L.compose( [ layer ], L.Command( [ "python", "-m", "errand", "x" ] ),
                      L.Context( root = ROOT ) )


# --- the shape of the command ----------------------------------------------

if test( "docker mounts the project and works there" ):
    argv = folded( L.Docker( image = "img:1" ) ).argv
    assert argv[ : 3 ] == [ "docker", "run", "--rm" ]
    assert [ "-v", f"{ROOT}:{ROOT}" ] == argv[ argv.index( "-v" ) : argv.index( "-v" ) + 2 ]
    assert argv[ argv.index( "-w" ) + 1 ] == str( ROOT )
    assert argv[ -4 : ] == [ "python", "-m", "errand", "x" ]


if test( "docker runs as the caller, so the results are the caller's" ):
    # A daemon-backed container writes as root by default. The output tree
    # would come out owned by somebody else, and the next run outside the
    # container could not even clear it.
    argv = folded( L.Docker( image = "img:1" ) ).argv
    assert argv[ argv.index( "--user" ) + 1 ] == f"{os.getuid()}:{os.getgid()}"
    assert "--user" not in folded( L.Docker( image = "img:1", user = None ) ).argv
    assert folded( L.Docker( image = "img:1", user = "1000:1000" ) ).argv[ 3 : 5 ] == \
        [ "--user", "1000:1000" ]


if test( "podman is rootless, so it is left alone" ):
    # It already maps the caller; a --user on top of that maps somebody else.
    argv = folded( L.Podman( image = "img:1" ) ).argv
    assert argv[ 0 ] == "podman" and "--user" not in argv


if test( "the environment crosses into a container" ):
    cmd = L.compose( [ L.Docker( image = "img:1" ), L.Vars( { "MARK": "crossed" } ) ],
                     L.Command( [ "python", "-m", "errand" ] ), L.Context( root = ROOT ) )
    assert [ "-e", "MARK=crossed" ] == cmd.argv[ cmd.argv.index( "-e" ) : cmd.argv.index( "-e" ) + 2 ]
    # ...and not ALSO as a variable of the docker client's own process, which
    # would be a second, silent way for it to arrive.
    assert cmd.env == { }


if test( "apptainer uses the image's own interpreter" ):
    argv = folded( L.Apptainer( image = "c/x.sif", flags = [ "--nv" ] ) ).argv
    assert argv[ : 2 ] == [ "apptainer", "exec" ]
    assert "--nv" in argv and str( ROOT / "c/x.sif" ) in argv
    assert argv[ -4 : ] == [ "python", "-m", "errand", "x" ]


if test( "extra mounts are relative to the project" ):
    for layer, flag in ( ( L.Docker( image = "i", mounts = { "src": "/opt/src" } ), "-v" ),
                         ( L.Apptainer( image = "i.sif", mounts = { "src": "/opt/src" } ), "--bind" ) ):
        argv = folded( layer ).argv
        assert f"{ROOT / 'src'}:/opt/src" in argv, argv
        assert flag in argv


if test( "an image is named the same way whatever engine holds it" ):
    assert L.Docker( image = "ghcr.io/me/img:1.2" ).container == "ghcr.io_me_img-1.2"
    assert L.Apptainer( image = "containers/cuda.sif" ).container == "cuda.sif"


if test( "building an image is never done through the image" ):
    # `wrap` runs a command INSIDE the image, which does not exist yet while it
    # is being built.
    ctx = L.Context( root = ROOT )
    steps = L.Apptainer( image = "c/x.sif", recipe = "c/x.def" ).build( ctx )
    assert steps and all( "exec" not in s.split()[ : 2 ] for s in steps )
    # Named the way the project declares it, because the step is run FROM the
    # root -- this one when the image is built here, the remote one when it is
    # built over there. An absolute path would exist on one machine of the two.
    assert "c/x.def" in steps[ 0 ] and str( ROOT ) not in steps[ 0 ], steps[ 0 ]

    steps = L.Docker( image = "img:1", recipe = "Dockerfile" ).build( ctx )
    assert steps and steps[ 0 ].startswith( "docker build" )

    # An image someone else publishes has nothing to build.
    assert L.Docker( image = "img:1" ).build( ctx ) == [ ]


if test( "what this machine can actually run" ):
    # Always runs: it is what makes a thin setup visible rather than silent.
    for name, how in container_engines().items():
        print( f"  {name}: {how}" )


# --- a real container -------------------------------------------------------

APPTAINER_PROJECT = '''
from errand import configure, env, Apptainer, Vars

configure( exclude = [ "_lib" ] )

env( "boxed",
     [ Apptainer( image = "image.sif", recipe = "image.def" ),
       Vars( {{ "PYTHONPATH": "{root}/_lib", "MARK": "crossed" }} ) ],
     boxed = True )
'''

DOCKER_PROJECT = '''
from errand import configure, env, {cls}, Vars

configure( exclude = [ "_lib" ] )

env( "boxed",
     [ {cls}( image = "{image}" ),
       Vars( {{ "PYTHONPATH": "{root}/_lib", "MARK": "crossed" }} ) ],
     boxed = True )
'''

RECIPE = f"""Bootstrap: docker
From: {BASE_IMAGE}
"""

WORK = '''
import os, sys
from errand import bench, Param

if p := bench( "inside", n = Param( 2 ) ):
    p.results[ "n" ]      = p.n
    p.results[ "mark" ]   = os.environ.get( "MARK" )
    p.results[ "python" ] = sys.version.split( )[ 0 ]
'''


if test( "a run inside a container comes back out", tags = [ "container", "slow" ] ):
    engine = container_engine()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp ) / "proj"
        if engine == "apptainer":
            errandfile = APPTAINER_PROJECT.format( root = root )
            files = { "bench_work.py": WORK, "image.def": RECIPE }
        else:
            errandfile = DOCKER_PROJECT.format(
                cls = "Podman" if engine == "podman" else "Docker",
                image = BASE_IMAGE, root = root )
            files = { "bench_work.py": WORK }

        project = write_project( root, errandfile, files, vendor = True )
        code, output = run_errand( project, "-k", "bench", "--env", "boxed", "--n=2,3" )
        assert code == 0, output

        leaves = sorted( ( project / "runs" ).rglob( "result.yaml" ) )
        assert len( leaves ) == 2, f"{[ str( p ) for p in leaves ]}\n{output}"

        from errand import yamlish
        for leaf in leaves:
            got = yamlish.read( leaf )
            assert got[ "status" ] == "PASS", got
            assert got[ "results" ][ "mark" ] == "crossed", "the Vars layer did not cross"
            # the container's own interpreter, not the one that started errand
            assert got[ "results" ][ "python" ], got

        # `{place}` says which container it ran in, because the same work in two
        # images is two different sets of numbers.
        places = { yamlish.read( p )[ "place" ] for p in leaves }
        assert all( "@" in place for place in places ), places

        # and everything it wrote is the caller's, not root's
        for leaf in leaves:
            assert leaf.stat().st_uid == os.getuid(), "a container wrote as somebody else"


if test( "an image is built from its recipe when it is missing", tags = [ "container", "slow" ] ):
    engine = container_engine( only = "apptainer" )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp ) / "proj"
        project = write_project( root, APPTAINER_PROJECT.format( root = root ),
                                 { "bench_work.py": WORK, "image.def": RECIPE }, vendor = True )
        assert not ( project / "image.sif" ).exists()

        code, output = run_errand( project, "-k", "bench", "--env", "boxed" )
        assert code == 0, output
        assert ( project / "image.sif" ).exists(), f"the recipe was never built\n{output}"

        # ...and having been built, it is not built again
        code, again = run_errand( project, "-k", "bench", "--env", "boxed" )
        assert code == 0, again
        assert "apptainer build" not in again, "a fresh image must not be rebuilt"

        # ...until the recipe changes
        ( project / "image.def" ).write_text( RECIPE + "\n%environment\n    export EXTRA=1\n" )
        code, third = run_errand( project, "-k", "bench", "--env", "boxed" )
        assert code == 0, third
        assert "apptainer build" in third, "an edited recipe must be noticed"
