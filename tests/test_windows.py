"""A Windows machine as an environment: everything that can be checked without booting one."""
import contextlib
import os
import shlex
import shutil
import subprocess
import tempfile
import xml.dom.minidom
from pathlib import Path

from errand import test
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


if test( "windows may follow the ssh that leads to the machine that boots it" ):
    far = Env( [ L.Ssh( host = "lmo" ), vm.Windows() ] )
    assert far.vm is not None and far.ssh is not None
    for stack in ( [ L.Ssh( host = "lmo" ), L.Vars( { "A": "1" } ), vm.Windows() ],
                   [ vm.Windows(), L.Ssh( host = "lmo" ) ] ):
        try:
            Env( stack )
        except ValueError:
            pass
        else:
            raise AssertionError( f"accepted: {stack}" )


if test( "the deciding is here: what it asks over there are lines, named from the project here" ):
    over = L.Context( root = Path( "/there/proj" ), remote = True, origin = ROOT,
                      host = L.Over( L.Ssh( host = "lmo" ), "/there/proj" ) )
    [ step ] = vm.Windows().build( over )
    assert callable( step ) and str( step ).endswith( "on lmo" ), str( step )
    assert vm.Windows().image_name( over ) == vm.Windows().image_name( ctx() ), \
        "the image is named from the declaration as read HERE, wherever it is installed"
    line = vm.Windows().probe_shell( over )
    assert line.startswith( "sh -c " ), line
    assert f"errand/windows/{vm.Windows().image_name( over )}/ready" in line, line
    assert "-mtime" in line and "-mtime" not in vm.Windows( key = "K" ).probe_shell( over )


if test( "ssh hands a machine to boot its own host, and brings back what it fetched" ):
    seen, fetched = { }, [ ]

    def run( self, inner, cmd, ctx, pull = None, echo = print ):
        seen.update( host = ctx.host, root = ctx.root, origin = ctx.origin, pull = pull, argv = cmd.argv )
        return 7

    kept = vm.Windows.run, L.push, L.fetch
    vm.Windows.run = run
    L.push  = lambda *a, **kw: None
    L.fetch = lambda paths, *a, **kw: fetched.extend( paths )
    try:
        code = L.Ssh( host = "lmo", root = "/there/proj" ).run(
            [ vm.Windows( fetch = [ "build" ] ) ], L.Command( [ "cl", "/c", "a.cpp" ] ),
            ctx(), pull = [ "runs/x" ], echo = lambda s: None )
    finally:
        vm.Windows.run, L.push, L.fetch = kept
    assert code == 7, "the command's own code comes back through both"
    assert isinstance( seen[ "host" ], L.Over ) and seen[ "host" ].ssh.host == "lmo"
    assert str( seen[ "root" ] ) == "/there/proj" and seen[ "origin" ] == ROOT
    assert seen[ "pull" ] == [ "runs/x" ] and seen[ "argv" ] == [ "cl", "/c", "a.cpp" ]
    assert fetched == [ "runs/x", "build" ], "what windows brought over there comes back here"


if test( "what the machine is, asked through its host and read back" ):
    with tempfile.TemporaryDirectory() as tmp, cache( tmp ):
        facts = vm.Facts.of( L.Here( Path( tmp ) ) )
        assert facts.where == "here" and facts.cache == tmp, facts
        assert { "ssh", "tar" } <= facts.tools, facts.tools
        assert facts.arch and facts.system and facts.user, facts


def facts( **kw ):
    return vm.Facts( **{ **dict( where = "on lmo", arch = "x86_64", system = "Linux", user = "me", kvm = "rw",
                                 kvm_group = "kvm", cache = "/home/me/.cache", os_ids = { "ubuntu", "debian" },
                                 tools = { "ssh", "tar" } ), **kw } )


if test( "what is missing is said with the command that fixes it, on that machine" ):
    assert vm.qemu_hint( facts() ) == "sudo apt install qemu-system-x86 qemu-utils"
    assert vm.qemu_hint( facts( system = "Darwin", os_ids = set() ) ) == "brew install qemu"
    assert vm.qemu_hint( facts( os_ids = { "fedora" } ) ).startswith( "sudo dnf" )
    assert vm.qemu_hint( facts( os_ids = { "alpine" } ) ).startswith( "install QEMU" )
    try:
        vm.need( facts(), ( "qemu-img", "qemu-system-x86_64" ), vm.qemu_hint( facts() ) )
    except vm.VmError as err:
        assert "are not installed on lmo -- sudo apt install" in str( err ), err
    else:
        raise AssertionError( "missing tools went unnoticed" )
    assert vm.accel( facts() )[ 0 ] == "kvm"
    assert vm.accel( facts( kvm = "absent" ) )[ 0 ] == "tcg"
    for f, said in ( ( facts( kvm = "no" ), "sudo usermod -aG kvm me" ),
                     ( facts( arch = "arm64" ), "errand.Ssh( host" ) ):
        try:
            vm.accel( f )
        except vm.VmError as err:
            assert said in str( err ), err
        else:
            raise AssertionError( f"accepted: {f}" )


if test( "a machine is up while an errand process holds it, and not a moment more by default" ):
    assert vm.Windows().keep == "0"
    with tempfile.TemporaryDirectory() as tmp, cache( tmp ):
        m = vm.Machine( L.Here( Path( tmp ) ), facts( cache = tmp ), "img" )
        ( m.live / "holders" ).mkdir( parents = True )
        ( m.live / "used" ).touch()
        ( m.live / "holders" / str( os.getpid() ) ).touch()           # this process: alive
        ( m.live / "holders" / "999999" ).touch()                     # a process long gone
        assert m._idle( 0 ) is None, "held by a live errand process: it stays up"
        assert m.holders() == [ str( os.getpid() ) ], "the dead one is forgotten"
        ( m.live / "holders" / str( os.getpid() ) ).unlink()
        held = m._idle( 0 )
        assert held is not None and m.state() == "stopping", "nobody holds it: it goes"
        for lock in held:
            lock.close()
        os.utime( m.live / "used" )
        assert m._idle( 3600 ) is None, "`keep` still means what it says once nobody holds it"


if test( "no image, no command -- and said so" ):
    with tempfile.TemporaryDirectory() as tmp, cache( tmp ):
        said = [ ]
        here = L.Context( root = Path( tmp ) )
        assert vm.Windows().run( [ ], L.Command( [ "dir" ] ), here, echo = said.append ) == 1
        assert "not installed yet here" in said[ 0 ], said
        said.clear()
        assert vm.Windows().run( [ ], L.Command( [ "python", "-c", "a = 1\nprint( a )" ] ), here,
                                 echo = said.append ) == 1
        assert "one line" in said[ 0 ], "a newline is refused, not silently cut by cmd.exe"


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


if test( "the project lands on the disk that is kept, named after it, unless told otherwise" ):
    assert vm.Windows().guest_root( ctx() ) == "E:/project"
    assert vm.Windows( data = None ).guest_root( ctx() ) == "C:/errand/project", "no kept disk: reset with C:"
    assert vm.Windows( root = "D:/w" ).guest_root( ctx() ) == "D:/w"


if test( "the disk that is kept is attached as it is, and made usable in the guest by a script cmd.exe cannot break" ):
    argv = " ".join( vm.qemu_argv( "/s.qcow2", accel = ( "kvm", "host" ), port = 1, cpus = 1, ram = "1G",
                                   data = "/img/data.qcow2" ) )
    assert "file=/img/data.qcow2,format=qcow2" in argv and "drive=data,bus=ide.2" in argv
    assert "drive=data" not in " ".join( vm.qemu_argv( "/s.qcow2", accel = ( "kvm", "host" ), port = 1,
                                                       cpus = 1, ram = "1G" ) )
    assert "data" in vm.Windows().booted() and vm.Windows().booted()[ "data" ] == "32G"
    line = vm.powershell( vm.DATA_SCRIPT )
    assert line.startswith( "powershell -NoProfile" ) and "\n" not in line and '"' not in line
    assert "-DriveLetter E" in vm.DATA_SCRIPT and "IsOffline" in vm.DATA_SCRIPT


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
        assert any( "would run: install windows" in s and s.endswith( "here" ) for s in said ), said
        assert not vm.images_dir().exists()


if test( "an evaluation is rebuilt before it runs out; a licensed install is not" ):
    with tempfile.TemporaryDirectory() as tmp, cache( tmp ):
        here = L.Context( root = Path( tmp ) )
        for layer, expected in ( ( vm.Windows(), False ), ( vm.Windows( key = "K" ), True ) ):
            image = layer.image( here )
            image.mkdir( parents = True )
            ( image / "ready" ).write_text( "x" )
            assert layer.probe( here ), "asked through the host, like anywhere else"
            os.utime( image / "ready", ( 0, 0 ) )      # installed in 1970
            assert layer.probe( here ) is expected


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
    quoted = vm.setup_script( msvc = False, provision = [ { "line": "& 'C:\\P y\\python.exe' -m pip" } ] )
    assert "Step 'provision: & ''C:\\P y\\python.exe'' -m pip'" in quoted, \
        "a quote in the line must not end the label, and the script with it"


if test( "durations read the way they are written" ):
    assert vm._seconds( "15m" ) == 900 and vm._seconds( "2h" ) == 7200
    assert vm._seconds( "30s" ) == 30 and vm._seconds( 0 ) == 0


if test( "qemu is asked for inbox hardware only, and a port on localhost" ):
    argv = vm.qemu_argv( "/d,isk.qcow2", accel = vm.accel( facts() ), port = 2222, cpus = 4, ram = "8G",
                         iso = "/w.iso", media = "/m" )
    joined = " ".join( argv )
    assert "-accel kvm" in joined and "hv_time" in joined
    assert "file=/d,,isk.qcow2" in joined, "a comma in a path must not end the option"
    assert "hostfwd=tcp:127.0.0.1:2222-:22" in joined
    assert "-m 8192M" in joined and "-smp 4" in joined
    assert "e1000e" in joined and "ide-hd" in joined
    assert "once=d" in joined and "removable=on" in joined
    assert "format=raw,readonly=on" in joined, "QEMU refuses a USB disk over a read-only node otherwise"


if test( "the project goes in by rsync, to the path the guest's rsync reads" ):
    assert vm.msys_path( "E:/proj" ) == "/e/proj" and vm.msys_path( "C:\\errand\\p y\\" ) == "/c/errand/p y"
    argv = shlex.split( vm.rsync_line( [ "ssh", "-p", "2222", "-i", "/c/k ey" ], "E:/proj" ) )
    assert argv[ 0 ] == "rsync" and argv[ -2 : ] == [ "./", "Administrator@127.0.0.1:/e/proj/" ], argv
    assert shlex.split( argv[ argv.index( "-e" ) + 1 ] ) == [ "ssh", "-p", "2222", "-i", "/c/k ey" ]
    assert argv[ argv.index( "--rsync-path" ) + 1 ] == vm.GUEST_RSYNC
    assert "--delete" not in argv, "what a command built over there must stay"


if shutil.which( "rsync" ) and test( "what is copied in leaves out what an Ssh push would" ):
    with tempfile.TemporaryDirectory() as tmp:
        root, out = Path( tmp ) / "p", Path( tmp ) / "out"
        for p in ( "src/a.cpp", "runs/x/result.yaml", ".git/HEAD", "build/a.o", ".errand/env-w.yaml" ):
            ( root / p ).parent.mkdir( parents = True, exist_ok = True )
            ( root / p ).write_text( "x" )
        # The line as the machine that runs QEMU would run it, from its root,
        # into a directory here rather than the guest.
        argv = shlex.split( vm.rsync_line( [ "ssh" ], "E:/proj" ) )
        for flag in ( "-e", "--rsync-path" ):
            del argv[ argv.index( flag ) : argv.index( flag ) + 2 ]
        assert subprocess.run( [ *argv[ : -1 ], f"{out}/" ], cwd = root ).returncode == 0
        names = { str( p.relative_to( out ) ) for p in out.rglob( "*" ) }
        assert names == { "src", "src/a.cpp" }, names


if test( "a link to nothing does not fail the copy; anything else does" ):
    done = lambda code, err = "": subprocess.CompletedProcess( [ ], code, "", err )
    assert not vm.rsync_failed( done( 0 ) )
    assert not vm.rsync_failed( done( 23, 'symlink has no referent: "/p/tl24/vfs"\n'
                                          "rsync error: some files/attrs were not transferred (code 23)\n" ) )
    assert vm.rsync_failed( done( 23, 'rsync: [receiver] mkstemp "/e/p/x" failed: Permission denied (13)\n'
                                      "rsync error: some files/attrs were not transferred (code 23)\n" ) )
    assert vm.rsync_failed( done( 12, "rsync: connection unexpectedly closed\n" ) )


if test( "rsync goes into the image, and the host is told what it lacks" ):
    script = vm.setup_script()
    assert script.index( "Step 'rsync'" ) < script.index( "vs_buildtools" )
    assert "noacl" in script and "rsync.exe' ) --version" in script
    assert vm.package_hint( facts(), [ "rsync", "zstd" ] ) == "sudo apt install rsync zstd"
    assert vm.package_hint( facts( system = "Darwin", os_ids = set() ), [ "rsync" ] ) == "brew install rsync"
    assert "rsync.exe" in vm.RSYNC_FILES and any( p.startswith( "rsync-" ) for p in vm.MSYS2_PACKAGES )
