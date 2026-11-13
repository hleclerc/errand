"""What was built is recorded where it lives, from both ends ( ADR 0004 )."""
import contextlib
import os
import subprocess
import tempfile
from pathlib import Path

from errand import test
from errand import config, layers as L, setup, yamlish
from errand.config import Env


@contextlib.contextmanager
def project( apptainer = 'cp "$4" "$3"' ):
    """A root with a recipe, and an `apptainer` that runs `apptainer` here: `build --force TARGET RECIPE`."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp ) / "project"
        bin_ = Path( tmp ) / "bin"
        root.mkdir(); bin_.mkdir()
        ( root / "i.def" ).write_text( "recipe\n" )
        tool = bin_ / "apptainer"
        tool.write_text( f"#!/bin/sh\n{apptainer}\n" )
        tool.chmod( 0o755 )
        path = os.environ[ "PATH" ]
        os.environ[ "PATH" ] = f"{bin_}:{path}"
        try:
            yield root, tool
        finally:
            os.environ[ "PATH" ] = path


def image_env( root ):
    layer = L.Apptainer( image = "i.sif", recipe = "i.def" )
    return layer, Env.make( "x", [ layer ] ), L.Context( root = root )


def dated( path, when ):
    os.utime( path, ( when, when ) )


def ensure( root, env, ctx, said = None, **kw ):
    return setup.ensure( root, env, ctx, echo = ( said if said is not None else [ ] ).append, **kw )


if test( "an image older than its recipe, and never seen, is rebuilt, not adopted" ):
    # manylinux.sif: found under a new environment name, without the pin its
    # recipe had gained in the meantime, and recorded as if built from it.
    with project() as ( root, _ ):
        layer, env, ctx = image_env( root )
        ( root / "i.sif" ).write_text( "old\n" )
        dated( root / "i.sif", 1_000_000 )
        assert setup.status( root, env, ctx ) == setup.STALE
        assert ensure( root, env, ctx ) == 0
        assert ( root / "i.sif" ).read_text() == "recipe\n"
        assert ( root / "i.sif.prev" ).read_text() == "old\n", "the one it replaces is kept"
        assert not ( root / "i.sif.new" ).exists()
        built = setup.look( root, layer, ctx )[ 0 ][ "built" ]
        assert built[ "origin" ] == "built" and built[ "stamp" ]
        assert setup.status( root, env, ctx ) == setup.OK


if test( "an image newer than its recipe is adopted, and says so" ):
    with project() as ( root, tool ):
        layer, env, ctx = image_env( root )
        dated( root / "i.def", 1_000_000 )
        ( root / "i.sif" ).write_text( "theirs\n" )
        assert ensure( root, env, ctx ) == 0
        assert ( root / "i.sif" ).read_text() == "theirs\n"
        assert setup.status( root, env, ctx ) == setup.ADOPTED
        # adopted is not frozen: a declaration changed since is a reason to build
        ( root / "i.def" ).write_text( "another recipe\n" )
        assert ensure( root, env, ctx ) == 0
        assert ( root / "i.sif" ).read_text() == "another recipe\n"


if test( "what is built in place is never rebuilt on a date" ):
    class Prefix( L.Artefact ):
        built = 0
        def describe( self ): return "prefix"
        def spec( self, ctx ): return [ ctx.root / "i.def" ]
        def probe( self, ctx ): return True
        def stamp_shell( self, ctx ): return "echo 1000 7"
        def build( self, ctx ):
            self.built += 1
            return [ "true" ]

    with project() as ( root, _ ):
        layer, said = Prefix(), [ ]
        assert ensure( root, Env.make( "x", [ layer ] ), L.Context( root = root ), said ) == 0
        assert layer.built == 0
        assert any( "older than i.def" in s for s in said ), said


if test( "a failed build leaves the image, stops the run, and is tried again" ):
    with project( 'echo no space left; exit 3' ) as ( root, tool ):
        layer, env, ctx = image_env( root )
        ( root / "i.sif" ).write_text( "old\n" )
        dated( root / "i.sif", 1_000_000 )
        said = [ ]
        assert ensure( root, env, ctx, said ) == 1
        assert ( root / "i.sif" ).read_text() == "old\n"
        assert not ( root / "i.sif.new" ).exists() and not ( root / "i.sif.prev" ).exists()
        assert any( "--no-setup" in s and "untouched" in s for s in said ), said
        record = setup.look( root, layer, ctx )[ 0 ]
        assert record[ "last_attempt" ][ "code" ] == 3, record
        logs = list( ( root / "errand-outputs" / "builds" / "records" ).glob( "*.log" ) )
        assert len( logs ) == 1 and "no space left" in logs[ 0 ].read_text()
        assert "last build failed" in setup.status( root, env, ctx )

        tool.write_text( '#!/bin/sh\ncp "$4" "$3"\n' )
        assert ensure( root, env, ctx ) == 0
        assert "last_attempt" not in setup.look( root, layer, ctx )[ 0 ]
        assert "no space left" not in logs[ 0 ].read_text(), "only the last attempt"
        assert len( list( ( root / "errand-outputs" / "builds" / "records" ).iterdir() ) ) == 2


if test( "an image replaced by hand is not what the record describes" ):
    with project() as ( root, tool ):
        layer, env, ctx = image_env( root )
        assert ensure( root, env, ctx ) == 0
        ( root / "i.sif" ).write_text( "put there by somebody, and longer\n" )
        assert ensure( root, env, ctx ) == 0
        assert "somebody" in ( root / "i.sif" ).read_text()
        assert setup.look( root, layer, ctx )[ 0 ][ "built" ][ "origin" ] == "adopted"


if test( "a changed declaration counts, whatever happened to the stamp" ):
    # A site-packages directory changes for reasons of its own: that must not
    # turn a new requirement into an adoption, and leave it uninstalled.
    with project() as ( root, _ ):
        layer, env, ctx = image_env( root )
        assert ensure( root, env, ctx ) == 0
        ( root / "i.sif" ).write_text( "changed\n" )
        ( root / "i.def" ).write_text( "new recipe\n" )
        assert ensure( root, env, ctx ) == 0
        assert ( root / "i.sif" ).read_text() == "new recipe\n"


if test( "renaming an environment forgets nothing" ):
    with project() as ( root, tool ):
        layer, env, ctx = image_env( root )
        assert ensure( root, env, ctx ) == 0
        tool.write_text( "#!/bin/sh\nexit 1\n" )
        assert ensure( root, Env.make( "renamed", [ layer ] ), ctx ) == 0


if test( "two images of the same name have two records" ):
    a, b = L.Apptainer( image = "a/cuda.sif" ), L.Apptainer( image = "b/cuda.sif" )
    assert setup.slug( a ) != setup.slug( b )
    assert setup.slug( a ).startswith( "apptainer-cuda.sif-" ), setup.slug( a )


if test( "a record is read through what a remote shell says first" ):
    class Chatty:
        def shell( self, line, **how ):
            out = subprocess.run( [ "sh", "-c", line ], capture_output = True, text = True, cwd = root )
            out.stdout = "welcome to the cluster\n" + out.stdout
            return out

    class Thing:
        def describe( self ): return "thing"
        def stamp_shell( self, ctx ): return "echo 12 34"

    with tempfile.TemporaryDirectory() as root:
        place = L.Context( root = Path( root ), host = Chatty() )
        setup_dir = Path( root ) / setup.builds( Path( root ) )
        setup_dir.mkdir( parents = True )
        ( setup_dir / f"{setup.slug( Thing() )}.yaml" ).write_text( yamlish.dump( { "built": { "fingerprint": "f" } } ) )
        record, stamp = setup.look( Path( root ), Thing(), place )
        assert record == { "built": { "fingerprint": "f" } } and stamp == "12 34", ( record, stamp )


if test( "push spares the exact paths of every environment, and says what it deleted" ):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path( tmp )
        here, there, bin_ = tmp / "here", tmp / "there", tmp / "bin"
        for d in ( here, there, bin_ ):
            d.mkdir()
        ( bin_ / "ssh" ).write_text( '#!/bin/sh\nwhile [ "$1" != h ]; do shift; done\nshift\nexec sh -c "$*"\n' )
        ( bin_ / "ssh" ).chmod( 0o755 )
        ( here / "source.py" ).write_text( "1\n" )
        for name in ( "a.sif", "a.sif.new", "b.sif", "manylinux.sif.bak", "stray.sif" ):
            ( there / name ).write_text( "only there\n" )

        kept = dict( config.envs )
        config.envs.clear()
        config.envs[ "one" ] = Env( [ L.Apptainer( image = "a.sif" ) ] )
        config.envs[ "two" ] = Env( [ L.Apptainer( image = "b.sif" ) ] )
        path = os.environ[ "PATH" ]
        os.environ[ "PATH" ] = f"{bin_}:{path}"
        said = [ ]
        try:
            assert "/a.sif.new" in L.own_paths() and "/b.sif" in L.own_paths()
            L.push( here, "h", there, echo = said.append )
        finally:
            os.environ[ "PATH" ] = path
            config.envs.clear()
            config.envs.update( kept )

        names = { p.name for p in there.iterdir() }
        assert names == { "a.sif", "a.sif.new", "b.sif", "source.py" }, names
        assert any( "manylinux.sif.bak" in s for s in said ) and any( "stray.sif" in s for s in said ), said
