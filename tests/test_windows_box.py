"""A Windows that is just there, reached by ssh ( `WindowsBox` ): everything that can be checked without one."""
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

from errand import test
from errand import layers as L, setup, vm
from errand.config import Env
from errand.vm import box as B
from errand.layers import gateways


ROOT = Path( "/project" )


def boxed( **kw ):
    return Env( [ L.Ssh( host = "me@winbox", options = [ "-J", "jump", "-p", "2222" ] ), vm.WindowsBox( **kw ) ] )


if test( "a box follows the Ssh that reaches it, and knows which" ):
    env = boxed()
    box = env.vm
    assert box is not None and box.is_box and box.via.host == "me@winbox"
    assert env.ssh is None                        # the Ssh leads to no POSIX machine: the box does it all
    assert env.describe() == "ssh:me@winbox -> windows-box"
    # each environment's box knows its own Ssh, even from one declaration
    shared = vm.WindowsBox()
    a = Env( [ L.Ssh( host = "a" ), shared ] ).vm
    b = Env( [ L.Ssh( host = "b" ), shared ] ).vm
    assert ( a.via.host, b.via.host ) == ( "a", "b" ) and shared.via is None
    for stack in ( [ L.Ssh( host = "x" ), L.Vars( { "A": "1" } ), vm.WindowsBox() ],
                   [ vm.WindowsBox(), L.Ssh( host = "x" ) ] ):
        try:
            Env( stack )
        except ValueError:
            pass
        else:
            raise AssertionError( f"accepted: {stack}" )


if test( "its record is named by the machine, not by the declaration alone" ):
    a = Env( [ L.Ssh( host = "a" ), vm.WindowsBox() ] ).vm
    b = Env( [ L.Ssh( host = "b" ), vm.WindowsBox() ] ).vm
    assert setup.slug( a ) != setup.slug( b )


if test( "a command is one cmd.exe line, errand's Python first on the PATH, msvc only when asked" ):
    box = boxed().vm
    line = box.line( L.Command( [ "python", "-m", "x y" ], { "K": "v" } ), "C:/errand/work/p" )
    assert line.startswith( 'cd /d "C:\\errand\\work\\p" && set "PATH=C:\\errand\\venv\\Scripts;%PATH%"' )
    assert 'set "K=v"' in line and line.endswith( 'python -m "x y"' ) and "vcvars" not in line
    assert "vcvars64" in boxed( msvc = True ).vm.line( L.Command( [ "x" ] ), "C:/p" )
    # a PATH of the command's own keeps the venv first: cmd.exe reads all of a line's %PATH% before running it
    line = box.line( L.Command( [ "x" ], { "PATH": "C:\\tools\\bin;%PATH%" } ), "C:/p" )
    assert line.count( "PATH=" ) == 1 and 'set "PATH=C:\\tools\\bin;C:\\errand\\venv\\Scripts;%PATH%"' in line
    assert box.guest_root( L.Context( root = ROOT ) ) == "C:/errand/work/project"
    assert boxed( root = "D:/w" ).vm.guest_root( L.Context( root = ROOT ) ) == "D:/w"


if test( "what it is set up from decides whether it is set up again: python, msvc, provisioning by content" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        ( root / "tools.ps1" ).write_text( "Write-Output 1" )
        ctx = L.Context( root = root )
        one = boxed( provision = [ "tools.ps1" ] ).vm.image_name( ctx )
        assert one == boxed( provision = [ "tools.ps1" ], fetch = [ "out" ] ).vm.image_name( ctx )
        ( root / "tools.ps1" ).write_text( "Write-Output 2" )
        assert one != boxed( provision = [ "tools.ps1" ] ).vm.image_name( ctx )
        assert boxed( python = "3.13.1" ).vm.image_name( ctx ) != boxed().vm.image_name( ctx )
        assert boxed( msvc = True ).vm.image_name( ctx ) != boxed().vm.image_name( ctx )


if test( "it is reached from here with the Ssh's options: scp gets its port as -P" ):
    m = B.Box( boxed().vm, tempfile.mkdtemp() )
    assert m.address == "me@winbox"
    ssh = m._reach( "ssh" )
    scp = m._reach( "scp" )
    assert ssh[ : 5 ] == [ "ssh", "-J", "jump", "-p", "2222" ] and "ConnectTimeout=10" in " ".join( ssh )
    assert scp[ : 5 ] == [ "scp", "-J", "jump", "-P", "2222" ]


if test( "a box with no Ssh before it is said to need one" ):
    lone = vm.WindowsBox()
    try:
        B.Box( lone, "/tmp" )
    except vm.VmError as err:
        assert "Ssh" in str( err )
    else:
        raise AssertionError( "a box with no way to reach it was accepted" )


if test( "a box not set up stops a run, and says what sets it up" ):
    class Answer:
        def __init__( self, code ):
            self.code, self.lines = code, [ ]
        def shell( self, line, **kw ):
            self.lines.append( line )
            return subprocess.CompletedProcess( line, self.code, "", "" )
    box = boxed().vm
    said = [ ]
    m = B.Box( box, tempfile.mkdtemp() )
    m.host = Answer( 3 )
    assert m.ready( "abc" ) is False and "C:\\errand\\ready\\abc" in m.host.lines[ 0 ]
    m.host = Answer( 255 )
    try:
        m.ready( "abc" )
    except vm.VmError as err:
        assert "cannot reach" in str( err )
    else:
        raise AssertionError( "a box that does not answer was taken for one not set up" )


if test( "setup asks this machine for ssh and scp, and builds the box in one step" ):
    box = boxed().vm
    assert [ what for _, what in box.requires( L.Context( root = ROOT ) ) ] == [ "ssh, not found", "scp, not found" ]
    steps = box.build( L.Context( root = ROOT ) )
    assert len( steps ) == 1 and callable( steps[ 0 ] ) and str( steps[ 0 ] ).startswith( "set up windows-box" )


if test( "an Ssh alone that reaches a Windows says to add a WindowsBox" ):
    for said in ( "'true' is not recognized as an internal or external command,\r\noperable program or batch file.",
                  "true : The term 'true' is not recognized as the name of a cmdlet, function, script file" ):
        stop = gateways.unreachable( "winbox", SimpleNamespace( returncode = 1, stderr = said ) )
        assert stop is not None and "WindowsBox()" in str( stop ) and "winbox" in str( stop )
    assert gateways.unreachable( "posix", SimpleNamespace( returncode = 1, stderr = "mkdir: Permission denied" ) ) is None


if test( "the guest's agent and copies use the box's own address" ):
    from errand.cli import guest as G
    env = boxed()
    where = SimpleNamespace( root = Path( tempfile.mkdtemp() ), ssh = None, there = ROOT, cache = None )
    g = G.Guest( env, { }, where, lambda s: None )
    assert g.box and g.said_where == "on me@winbox"
    g.m = B.Box( env.vm, where.root )
    target = g.target()
    assert target[ "argv" ][ 0 ] == "ssh" and "me@winbox" in target[ "argv" ] and "-T" in target[ "argv" ]


if test( "files cross through an agent of the guest that no layer starts" ):
    from errand.cli import guest as G
    env = boxed( also = [ "../sib" ] )
    where = SimpleNamespace( root = Path( tempfile.mkdtemp() ), ssh = None, there = ROOT, cache = None )
    g = G.Guest( env, { }, where, lambda s: None )
    g.m = B.Box( env.vm, where.root )
    host, envt = g.host_target(), g.target()
    line = host[ "argv" ][ -1 ]
    assert host[ "argv" ][ 0 ] == "ssh" and "me@winbox" in host[ "argv" ] and host[ "id" ] != envt[ "id" ]
    assert f"connect C:/errand/agents/host-{g.key}" in line and "cd /d" not in line and "vcvars" not in line, line
    unpack = G.unpack_line( "C:/errand/src/k1", "k1" )
    # The guest's Python unpacks it ( `bootstrap.UNPACK_PY` ): nothing in the line for cmd.exe to read into.
    assert unpack.startswith( 'python -c "import base64;exec(' ) and unpack.endswith( '"C:/errand/src/k1/errand" k1' )
    assert not any( c in unpack.split( '"' )[ 1 ] for c in "%^&|<>" ), unpack


if test( "bytes on a line's stdin come back as bytes: the tar of errand's sources into a guest" ):
    got = L.Here( Path( tempfile.mkdtemp() ) ).shell( "cat", input = b"\x1f\x8b\x00", capture = True )
    assert got.returncode == 0 and got.stdout == b"\x1f\x8b\x00", got


if test( "the guest's push and pull, through its agent: the project and its `also` in, results straight back here" ):
    import os
    import shutil
    from errand import agents, sync as S
    from errand.cli import guest as G
    d = Path( tempfile.mkdtemp( dir = "/tmp" ) )
    try:
        root, sib, there = d / "proj", d / "sib", d / "guest" / "proj"
        for f, text in { root / "a.py": "a", root / "build/x.o": "o", sib / "s.py": "s" }.items():
            f.parent.mkdir( parents = True, exist_ok = True )
            f.write_text( text )
        os.symlink( "a.py", root / "ln" )
        env = boxed( also = [ "../sib" ] )
        where = SimpleNamespace( root = root, ssh = None, there = root, cache = None )
        said = [ ]
        g = G.Guest( env, { }, where, said.append )
        g.there = str( there )
        os.environ[ "ERRAND_AGENT" ] = "direct"
        from errand import config
        zones, config.settings.zones = config.settings.zones, { "/out": "back" }      # written there, brought back
        g._host_conn = agents.open( { "kind": "local", "dir": str( d / "ag" ), "keep_alive": 5 } )
        g._push_sync()
        assert ( there / "a.py" ).read_text() == "a" and ( d / "guest/sib/s.py" ).read_text() == "s"
        assert not ( there / "ln" ).is_symlink() and ( there / "ln" ).read_text() == "a", "links followed, for Windows"
        assert not ( there / "build" ).exists(), "a build zone is not pushed into"
        assert any( "sync push -> windows:" in s for s in said ) and any( "1 sent" in s for s in said ), said
        ( there / "out" ).mkdir()
        ( there / "out/r.txt" ).write_text( "result" )
        g.fetch( [ "out", "nothing" ] )
        assert ( root / "out/r.txt" ).read_text() == "result"
        said.clear()
        g._push_sync()
        assert not [ s for s in said if "sent" in s ], ( "nothing to send twice", said )
        config.settings.zones = zones
    finally:
        shutil.rmtree( d, ignore_errors = True )


if test( "a box is set up by errand setup only: any other command stops, and says what to run" ):
    from errand.layers import Artefact

    class Held( Artefact, L.Layer ):
        setup_only = True
        built = 0
        def describe( self ):
            return "held"
        def spec( self, ctx ):
            return [ 1 ]
        def probe( self, ctx ):
            return False
        def build( self, ctx ):
            def step( echo ):
                Held.built += 1
                return 0
            return [ step ]

    with tempfile.TemporaryDirectory() as tmp:
        env = Env.make( "w", [ Held() ] )
        said = [ ]
        assert setup.ensure( Path( tmp ), env, L.Context( root = Path( tmp ) ), echo = said.append ) == 1
        assert Held.built == 0 and "errand setup --env w" in said[ -1 ]
        assert setup.ensure( Path( tmp ), env, L.Context( root = Path( tmp ) ), echo = said.append, asked = True ) == 0
        assert Held.built == 1


if test( "errand started on Windows puts the project on a POSIX machine at a POSIX path" ):
    from pathlib import PurePosixPath, PureWindowsPath
    from unittest import mock
    home = Path.home()
    assert gateways.windows_remote_root( None, home / "Projects" / "x" ) == PurePosixPath( "Projects/x" )
    assert gateways.windows_remote_root( None, Path( "/elsewhere/x" ) ) == PurePosixPath( "errand-work/x" )
    assert gateways.windows_remote_root( "D:\\scratch\\x", ROOT ) == PurePosixPath( "D:/scratch/x" )
    assert gateways.windows_remote_root( "/scratch/x", ROOT ) == PurePosixPath( "/scratch/x" )
    with mock.patch.object( L.base, "WINDOWS", True ):
        # a path of the other machine stays POSIX, whatever this one makes of `Path`
        assert L.remote_path( PureWindowsPath( "errand-work\\x" ) ) == PurePosixPath( "errand-work/x" )
        assert L.Over( L.Ssh( host = "h" ), "/home/me/x" ).root == PurePosixPath( "/home/me/x" )
        assert L.remote_path( None ) is None
        # a relative root lands under the remote home, asked once
        gateways._HOMES[ ( "h", ( ) ) ] = "/home/me"
        try:
            assert L.Ssh( host = "h" ).remote_root( L.Context( root = Path( "/elsewhere/x" ) ) ) == PurePosixPath( "/home/me/errand-work/x" )
        finally:
            gateways._HOMES.clear()


if test( "errand started on Windows pulls no links" ):
    from unittest import mock
    from errand.agents import syncop
    with mock.patch.object( L.base, "WINDOWS", True ), \
         mock.patch.object( gateways.agents, "open", lambda target: None ), \
         mock.patch.object( syncop, "pull" ) as pull:
        gateways.fetch( [ "a/b" ], "h", "/home/me/x", Path( tempfile.mkdtemp() ) )
        assert pull.call_args.kwargs[ "links" ] is False and pull.call_args[ 0 ][ 3 ] == [ "a/b" ], pull.call_args
