"""A Windows machine as an environment: everything that can be checked without booting one."""
import contextlib
import os
import tempfile
import xml.dom.minidom
from pathlib import Path

from errand import test, skip
from errand import layers as L, setup, vm
from errand.config import Env


ROOT = Path( "/project" )


def ctx( ):
    return L.Context( root = ROOT )


@contextlib.contextmanager
def cache( where ):
    """The image cache moved to `where` for the duration: nothing real is touched."""
    old = os.environ.get( "XDG_CACHE_HOME" )
    os.environ[ "XDG_CACHE_HOME" ] = str( where )
    try:
        yield
    finally:
        if old is None:
            os.environ.pop( "XDG_CACHE_HOME" )
        else:
            os.environ[ "XDG_CACHE_HOME" ] = old


if test( "windows is first, like ssh" ):
    try:
        Env( [ L.Vars( { "A": "1" } ), vm.Windows() ] )
    except ValueError as err:
        assert "first" in str( err )
    else:
        raise AssertionError( "a Windows layer after another one was accepted" )
    assert Env( [ vm.Windows() ] ).vm is not None
    assert Env( [ vm.Windows() ] ).ssh is None


if test( "windows refuses to be folded like the others" ):
    try:
        L.compose( [ vm.Windows() ], L.Command( [ "cl" ] ), ctx() )
    except RuntimeError as err:
        assert "first" in str( err )
    else:
        raise AssertionError( "a Windows layer was folded" )


if test( "a command becomes one cmd.exe line, from the project's copy" ):
    line = vm.Windows().line( L.Command( [ "cmake", "--build", "my build" ], { "A": "1" } ),
                              "C:/errand/proj" )
    assert line.startswith( r'cd /d "C:\errand\proj" && ' )
    assert r'call "C:\BuildTools\VC\Auxiliary\Build\vcvars64.bat"' in line   # msvc by default
    assert 'set "A=1"' in line
    assert line.endswith( 'cmake --build "my build"' )


if test( "without msvc, no vcvars" ):
    line = vm.Windows( msvc = False ).line( L.Command( [ "dir" ] ), "C:/x" )
    assert "vcvars" not in line and line.endswith( "dir" )


if test( "the project lands under C:/errand, named after it, unless told otherwise" ):
    assert vm.Windows().guest_root( ctx() ) == "C:/errand/project"
    assert vm.Windows( root = "D:/w" ).guest_root( ctx() ) == "D:/w"


if test( "what it is installed from decides which image, and nothing else does" ):
    base = vm.Windows().image( ctx() )
    assert vm.Windows( cpus = 16, ram = "32G", keep = "1h" ).image( ctx() ) == base, \
        "the size of the machine is how it is BOOTED, not what is installed: no reinstall for it"
    assert vm.Windows( key = "AAAAA-BBBBB" ).image( ctx() ) != base
    assert vm.Windows( python = "3.13.1" ).image( ctx() ) != base
    assert vm.Windows( msvc = False ).image( ctx() ) != base
    assert vm.Windows( provision = [ "choco install git" ] ).image( ctx() ) != base


if test( "a provisioning script is fingerprinted by what it says" ):
    with tempfile.TemporaryDirectory() as tmp:
        here = L.Context( root = Path( tmp ) )
        script = Path( tmp ) / "tools.ps1"
        script.write_text( "Write-Host one" )
        first = vm.Windows( provision = [ "tools.ps1" ] ).image( here )
        script.write_text( "Write-Host two" )
        assert vm.Windows( provision = [ "tools.ps1" ] ).image( here ) != first


if test( "the images live in the cache, shared between projects" ):
    with cache( "/c" ):
        a = vm.Windows().image( L.Context( root = Path( "/one" ) ) )
        b = vm.Windows().image( L.Context( root = Path( "/two" ) ) )
        assert a == b and str( a ).startswith( "/c/errand/windows/" )


if test( "setup says it would install, and installs nothing" ):
    with tempfile.TemporaryDirectory() as tmp, cache( tmp ):
        env = Env.make( "win", [ vm.Windows() ] )
        said = [ ]
        rc = setup.ensure( Path( tmp ), env, L.Context( root = Path( tmp ) ),
                           echo = said.append, dry_run = True )
        assert rc == 0
        assert any( "errand.vm build" in s for s in said ), said
        assert not vm.images_dir().exists()


if test( "an evaluation is rebuilt before it runs out; a licensed install is not" ):
    with tempfile.TemporaryDirectory() as tmp, cache( tmp ):
        for layer, expected in ( ( vm.Windows(), False ), ( vm.Windows( key = "K" ), True ) ):
            image = layer.image( ctx() )
            image.mkdir( parents = True )
            ( image / "ready" ).write_text( "x" )
            assert layer.probe( ctx() )
            os.utime( image / "ready", ( 0, 0 ) )      # installed in 1970
            assert layer.probe( ctx() ) is expected


if test( "the answer file: a key when there is one, none for the evaluation" ):
    assert "<ProductKey>" not in vm.autounattend()
    with_key = vm.autounattend( key = "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE", index = 2 )
    assert "<Key>AAAAA-BBBBB-CCCCC-DDDDD-EEEEE</Key>" in with_key
    assert "<Value>2</Value>" in with_key
    assert "errand-setup.ps1" in with_key


if test( "the answer file is well-formed XML" ):
    xml.dom.minidom.parseString( vm.autounattend( key = "K" ) )


if test( "the first logon opens sshd before anything that may fail, and always powers off" ):
    script = vm.setup_script( python = "3.13.1", provision = [ { "line": "Write-Host hi" }, "/p/x.ps1" ] )
    assert script.index( "sshd" ) < script.index( "vs_buildtools" ) < script.index( "python-3.13.1" )
    assert "PasswordAuthentication no" in script
    assert "Write-Host hi" in script and "errand-provision-1.ps1" in script
    assert "Stop-Computer -Force" in script.split( "finally" )[ -1 ]


if test( "durations read the way they are written" ):
    assert vm._seconds( "15m" ) == 900 and vm._seconds( "2h" ) == 7200
    assert vm._seconds( "30s" ) == 30 and vm._seconds( 0 ) == 0


if test( "qemu is asked for inbox hardware only, and a port on localhost" ):
    try:
        argv = vm.qemu_argv( Path( "/d,isk.qcow2" ), port = 2222, cpus = 4, ram = "8G",
                             iso = Path( "/w.iso" ), media = Path( "/m" ) )
    except vm.VmError as err:
        skip( str( err ) )
    joined = " ".join( argv )
    assert "file=/d,,isk.qcow2" in joined, "a comma in a path must not end the option"
    assert "hostfwd=tcp:127.0.0.1:2222-:22" in joined
    assert "-m 8192M" in joined and "-smp 4" in joined
    assert "e1000e" in joined and "ide-hd" in joined
    assert "once=d" in joined and "removable=on" in joined


if test( "what is copied in leaves out what rsync would" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        for p in ( "src/a.cpp", "runs/x/result.yaml", ".git/HEAD", "build/a.o", ".errand/env-w.yaml" ):
            ( root / p ).parent.mkdir( parents = True, exist_ok = True )
            ( root / p ).write_text( "x" )
        names = { rel for _, rel in vm._walk( root ) }
        assert names == { "src", "src/a.cpp" }, names
