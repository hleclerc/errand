"""`WindowsBox`: a Windows that is just there -- a machine of the user's, reached by the `Ssh` before it.

    errand.envs[ "win" ] = errand.Env( [ errand.Ssh( host = "winbox" ), errand.WindowsBox() ] )

The `Ssh` says how to get there ( host, options, a jump host ); the `WindowsBox` says what is there, as `Windows` does for
a machine errand boots. Everything after it runs on Windows, the way it runs in errand's own machine: cmd.exe lines, the
project copied in by rsync, an agent started through the layers, results fetched by tar.

What errand puts on that machine is all in `C:\\errand`, nothing on its PATH, nothing in its registry -- deleting the
directory undoes it:

    C:\\errand\\msys       rsync, from MSYS2's packages ( the guest's, pinned ), downloaded here and copied over
    C:\\errand\\uv         uv, for a `python = "3.13.1"` the machine does not have, and that Python ( `uv-python` )
    C:\\errand\\venv       a venv of that Python ( found: `py -3`, `python`; or uv's ), which the commands and the
                          provisioning run with: the machine's own Python is never written to
    C:\\errand\\src        errand's own sources, as for any other machine
    C:\\errand\\ready      one file per declaration set up: what `errand run` checks
    C:\\errand\\work       the projects' copies

Installing is `errand setup`'s, never a run's: a run on a box not set up stops and says so. `provision` ( PowerShell, a
`.ps1` of the project or a line ) is run then, once per declaration; changed, it is run again.
"""
from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .. import layers as L
from .common import _backslashed, VmError
from .datadisk import powershell
from .guest import VCVARS
from .talk import Talk
from .transfer import GUEST_MSYS, GUEST_RSYNC, MSYS2_PACKAGES, MSYS2_REPO, RSYNC_FILES, SSH_FILES, SSH_PACKAGES


ERRAND  = r"C:\errand"
VENV    = rf"{ERRAND}\venv"              # the venv commands run with
PYTHON  = rf"{VENV}\Scripts"
READY   = rf"{ERRAND}\ready"
UV_DIR  = rf"{ERRAND}\uv"

# Bumped whenever what setting a box up means changes in this file.
RECIPE = 2


@dataclass
class WindowsBox( L.Gateway, L.Artefact ):
    """Right after the `Ssh` that reaches a Windows machine: everything after it runs there.

    `python`: None runs the Python the machine has ( `py -3`, else `python` ); "3.13.1" has uv install that one into
    `C:\\errand`. `msvc`: vcvars64 before every command, the Build Tools being there. `provision`: PowerShell, run by
    `errand setup`."""
    python   : str | None = None
    msvc     : bool = False
    provision: list = field( default_factory = list )   # PowerShell: a `.ps1` of the project, or a line
    fetch    : list = field( default_factory = list )   # what to bring back after each command
    also     : list = field( default_factory = list )   # sibling checkouts the work needs ( `../loom` )
    root     : str | None = None                        # where the project goes; C:/errand/work/<project name>
    when     : str | None = None

    # What the paths a machine errand boots goes through recognize ( `layers.vm_of` ), and what tells the two apart.
    is_vm  = True
    is_box = True
    setup_only = True                    # a machine of somebody's: installed on by `errand setup` only
    data   = None                        # no disk of its own to flush
    keep   = "0"
    # The `Ssh` before it, set when the environment is declared ( `config.Env` ): how to get there.
    via    = None

    def wrap( self, cmd, ctx ):
        raise RuntimeError( "WindowsBox must follow the Ssh that reaches the machine" )

    def describe( self ):
        return "windows-box"

    def identity( self ) -> str:
        """What its record is named by: which machine, the `Ssh` before it saying."""
        return f"windows-box:{self.via.host if self.via is not None else 'here'}"

    def booted( self ) -> dict:
        return { }

    # -- what it is set up from ------------------------------------------------

    def spec( self, ctx ) -> list:
        from .windows import _provision_part
        return [ RECIPE, self.python, self.msvc, *[ _provision_part( p, ctx.origin ) for p in self.provision ] ]

    def image_name( self, ctx ) -> str:
        return L.fingerprint( *self.spec( ctx ) )

    def probe( self, ctx ) -> bool:
        """Set up for this declaration: asked of the machine itself."""
        try:
            return Box( self, ctx.root ).ready( self.image_name( ctx ) )
        except VmError:
            return False

    def build( self, ctx ) -> list:
        return [ Setup( self, ctx ) ]

    def requires( self, ctx ) -> list:
        """Of this machine, which reaches the box."""
        return [ ( "command -v ssh", "ssh, not found" ), ( "command -v scp", "scp, not found" ),
                 ( "command -v rsync", "rsync, not found" ) ]

    # -- being let in -------------------------------------------------------------

    def guest_root( self, ctx ) -> str:
        return self.root or f"C:/errand/work/{ctx.root.name}"

    def line( self, cmd: L.Command, guest_root: str ) -> str:
        """`cmd` as one cmd.exe line, from the project's copy there, with errand's Python first on the PATH."""
        parts = [ f'cd /d "{_backslashed( guest_root )}"' ]
        if self.msvc:
            parts.append( f'call "{VCVARS}" >nul' )
        parts += [ f'set "{k}={v}"' for k, v in with_venv( cmd.env ).items() ]
        parts.append( subprocess.list2cmdline( [ str( a ) for a in cmd.argv ] ) )
        return " && ".join( parts )

    def run( self, inner, cmd: L.Command, ctx: L.Context, pull = None, echo = print ):
        # Everything on the box goes through its agent ( `cli.guest`, ADR 0009 ): no cmd.exe line.
        raise RuntimeError( "a Windows box is reached through its agent ( errand run, errand shell )" )


def with_venv( env: dict ) -> dict:
    """`env` with errand's venv first on the PATH -- inside the command's own PATH when it has one: cmd.exe reads every
    `%PATH%` of a line before running any of it, so a second `set "PATH=...;%PATH%"` would drop the first."""
    import re
    env = dict( env )
    key = next( ( k for k in env if k.upper() == "PATH" ), None )
    if key is None:
        return { "PATH": f"{PYTHON};%PATH%", **env }
    value = str( env[ key ] )
    env[ key ] = ( re.sub( "%PATH%", lambda m: f"{PYTHON};%PATH%", value, count = 1, flags = re.I )
                   if re.search( "%PATH%", value, re.I ) else f"{PYTHON};{value}" )
    return env


def _scp_options( options ) -> list:
    """ssh's options as scp reads them: its port is `-P`."""
    out, it = [ ], iter( options )
    for o in it:
        out += [ "-P", next( it, "" ) ] if o == "-p" else [ o ]
    return out


class Box( Talk ):
    """A `WindowsBox`, from here: what `Guest` and `Setup` talk to it with ( as `Machine` for a booted one )."""
    port = 0

    def __init__( self, layer: WindowsBox, root ):
        ssh = layer.via
        if ssh is None:
            raise VmError( "WindowsBox must follow an Ssh to the machine: errand does not run on Windows itself yet" )
        self.layer, self.ssh = layer, ssh
        self.host  = L.Here( root )
        self.said  = f"windows box {ssh.host}"
        from .. import config
        self.scratch = str( config.state( Path( root ) ) / "windows-box" )
        Path( self.scratch ).mkdir( parents = True, exist_ok = True )

    @property
    def address( self ) -> str:
        return self.ssh.host

    def _reach( self, tool: str, port_flag: str = "" ) -> list:
        options = L.ssh_options( self.ssh.options )
        return [ tool, *( _scp_options( options ) if tool == "scp" else options ) ]

    @contextlib.contextmanager
    def using( self, booted = None, echo = print ):
        """Nothing to boot or hold: it is there."""
        yield self

    def ready( self, name: str ) -> bool:
        got = self.guest( f'if exist "{READY}\\{name}" ( exit 0 ) else ( exit 3 )', capture = True )
        if got.returncode not in ( 0, 3 ):
            raise VmError( f"cannot reach {self.said}: {( got.stderr or '' ).strip()[ -300 : ]}" )
        return got.returncode == 0

    def must( self, line: str, what: str, capture = False ):
        got = self.guest( line, capture = capture )
        if got.returncode:
            said = ( ( got.stderr or "" ) + ( got.stdout or "" ) ).strip()[ -600 : ] if capture else ""
            raise VmError( f"{what} failed on {self.ssh.host}" + ( f":\n{said}" if said else "" ) )
        return got

    def put( self, local: Path, remote: str ):
        """A file of this machine onto the box ( `C:/errand/...` )."""
        if self.scp( str( local ), f"{self.address}:{remote}" ):
            raise VmError( f"could not copy {local.name} to {self.ssh.host}:{remote}" )


# -- setting a box up ---------------------------------------------------------------

def _rsync_files( echo, ssh = False ) -> Path:
    """MSYS2's rsync and the DLLs it loads, unpacked here from the pinned packages ( kept in errand's cache ).
    `ssh`: its ssh as well, for errand started on Windows."""
    from .. import bootstrap
    packages, files = MSYS2_PACKAGES, RSYNC_FILES
    if ssh:
        packages, files = [ *MSYS2_PACKAGES, *SSH_PACKAGES ], [ *RSYNC_FILES, *SSH_FILES ]
    root = bootstrap.local_cache() / "msys2-rsync" / L.fingerprint( packages )
    into = root / "usr" / "bin"
    if all( ( into / f ).is_file() for f in files ):
        return into
    echo( f"    downloading {'rsync and ssh' if ssh else 'rsync'} for windows from msys2" )
    into.mkdir( parents = True, exist_ok = True )
    for p in packages:
        with urllib.request.urlopen( f"{MSYS2_REPO}/{p}-x86_64.pkg.tar.zst", timeout = 120 ) as r:
            packed = r.read()
        with tarfile.open( fileobj = io.BytesIO( _unzstd( packed ) ) ) as t:
            for m in t.getmembers():
                name = m.name.rsplit( "/", 1 )[ -1 ]
                if m.isfile() and m.name.startswith( "usr/bin/" ) and name in files:
                    ( into / name ).write_bytes( t.extractfile( m ).read() )
    missing = [ f for f in files if not ( into / f ).is_file() ]
    if missing:
        raise VmError( f"msys2's packages lack {', '.join( missing )}" )
    # read by msys2's runtime from <root>/etc: `/c/...` is `C:\\...`, and no POSIX permission is mapped onto ACLs
    ( root / "etc" ).mkdir( exist_ok = True )
    ( root / "etc" / "fstab" ).write_text( "none / cygdrive binary,posix=0,noacl,user 0 0\n" )
    # `~` is the Windows profile: ssh reads the same `.ssh/config`, keys and known hosts as Windows' own
    ( root / "etc" / "nsswitch.conf" ).write_text( "db_home: windows\n" )
    return into


def local_rsync( echo = None ) -> Path:
    """rsync for errand started on Windows: MSYS2's, as a box gets it."""
    return _local( echo ) / "rsync.exe"


def local_ssh( echo = None ) -> Path:
    """The ssh that rsync, started on Windows, reaches the other machine with: MSYS2's."""
    return _local( echo ) / "ssh.exe"


def _local( echo ):
    import sys as _sys
    return _rsync_files( echo or ( lambda s: print( s, file = _sys.stderr, flush = True ) ), ssh = True )


def _unzstd( data: bytes ) -> bytes:
    try:
        from compression import zstd            # Python 3.14
        return zstd.decompress( data )
    except ImportError:
        pass
    if shutil.which( "zstd" ) is not None:
        return subprocess.run( [ "zstd", "-dqc" ], input = data, stdout = subprocess.PIPE, check = True ).stdout
    if L.WINDOWS or sys.platform == "darwin":
        # bsdtar ( Windows' own tar.exe, macOS' ) reads zstd: `@-` copies the archive's entries into a plain tar
        got = subprocess.run( [ "tar", "-cf", "-", "@-" ], input = data, stdout = subprocess.PIPE, stderr = subprocess.PIPE )
        if got.returncode == 0:
            return got.stdout
    raise VmError( "neither Python 3.14 nor a `zstd` here, to open msys2's packages with ( brew / apt install zstd )" )


def _ps( script: str ) -> str:
    return powershell( "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'\n" + script )


FIND_PYTHON = r"""
foreach ( $c in @( @( 'py', '-3' ), @( 'python' ), @( 'python3' ) ) ) {
    $exe = Get-Command $c[ 0 ] -ErrorAction SilentlyContinue
    if ( -not $exe -or $exe.Source -like '*WindowsApps*' ) { continue }     # the Store's stub: opens the Store
    $args_ = @( $c | Select-Object -Skip 1 ) + @( '-c', 'import sys; print( sys.executable )' )
    $got = & $exe.Source @args_ 2>$null
    if ( $LASTEXITCODE -eq 0 -and $got ) { Write-Output "errand-python=$( ( $got | Select-Object -Last 1 ).Trim() )"; exit 0 }
}
exit 3
"""


class Setup:
    """`errand setup` for a `WindowsBox`, as one step: rsync, a Python, the provisioning, then the mark that says so."""

    def __init__( self, layer: WindowsBox, ctx: L.Context ):
        self.layer, self.ctx = layer, ctx

    def __str__( self ):
        return f"set up {self.layer.describe()} {self.layer.image_name( self.ctx )[ : 8 ]}"

    def __call__( self, echo = print ) -> int:
        try:
            self._do( echo )
            return 0
        except VmError as err:
            echo( f"    {err}" )
            return 1

    def _do( self, echo ):
        box, layer = Box( self.layer, self.ctx.root ), self.layer
        if not box.answers():
            raise VmError( f"cannot reach {box.said}: `ssh {box.address} echo ok` must work from this terminal, "
                           "and its shell be cmd.exe ( Windows' OpenSSH default )" )
        box.must( rf'for %d in ( "{ERRAND}" "{ERRAND}\bin" "{ERRAND}\src" "{ERRAND}\work" "{READY}" "{ERRAND}\provision" '
                  rf'"{GUEST_MSYS}\usr\bin" "{GUEST_MSYS}\etc" ) do @if not exist %d mkdir %d', "making C:\\errand" )

        # rsync, which copies the project in
        if box.guest( f'if exist "{_backslashed( GUEST_RSYNC )}" ( exit 0 ) else ( exit 3 )', quiet = True ).returncode:
            files = _rsync_files( echo )
            echo( f"    copying rsync to {box.ssh.host}" )
            for f in RSYNC_FILES:
                box.put( files / f, f"{GUEST_MSYS.replace( chr( 92 ), '/' )}/usr/bin/{f}" )
            box.must( _ps( f"Set-Content '{GUEST_MSYS}\\etc\\fstab' 'none / cygdrive binary,posix=0,noacl,user 0 0' "
                           "-Encoding ascii" ), "writing msys2's fstab" )

        # the Python commands run with
        if layer.python:
            echo( f"    python {layer.python}, by uv, into {ERRAND}" )
            got = box.must( _ps( rf"""
if ( -not ( Test-Path '{UV_DIR}\uv.exe' ) ) {{
    $env:UV_UNMANAGED_INSTALL = '{UV_DIR}'
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
}}
$env:UV_PYTHON_INSTALL_DIR = '{ERRAND}\uv-python'
& '{UV_DIR}\uv.exe' python install {layer.python}
if ( $LASTEXITCODE ) {{ throw "uv python install: exit $LASTEXITCODE" }}
$exe = & '{UV_DIR}\uv.exe' python find --managed-python {layer.python}
if ( $LASTEXITCODE -or -not $exe ) {{ throw "uv python find: exit $LASTEXITCODE" }}
Write-Output "errand-python=$( $exe.Trim() )"
""" ), f"installing python {layer.python}", capture = True )
            found = _said( got, "errand-python=" )
            if not found:
                raise VmError( f"uv installed no python {layer.python} on {box.ssh.host}" )
        else:
            found = self._python( box )
        echo( f"    python: {found}, as a venv in {VENV}" )
        box.must( f'"{found}" -m venv --clear "{VENV}"', f"making a venv of {found}" )

        if layer.msvc:
            box.must( f'if exist "{VCVARS}" ( exit 0 ) else ( exit 3 )',
                      f"msvc = True: the Build Tools ( {VCVARS} )" )

        # the provisioning, in its order
        for i, p in enumerate( layer.provision ):
            if str( p ).endswith( ".ps1" ):
                src = Path( p ) if Path( p ).is_absolute() else self.ctx.origin / p
                remote = f"C:/errand/provision/{i}-{src.name}"
                box.put( src, remote )
                echo( f"    provision: {src.name}" )
                line = ( f'powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{_backslashed( remote )}"' )
            else:
                echo( f"    provision: {str( p )[ : 60 ]}" )
                line = _ps( str( p ) )
            line = f'set "PATH={PYTHON};%PATH%" && {line}'
            box.must( line, f"provision {i + 1} ( {str( p )[ : 40 ]} )" )

        name = layer.image_name( self.ctx )
        box.must( f'echo {name}> "{READY}\\{name}"', "marking it ready" )

    def _python( self, box: Box ) -> str:
        """The interpreter the machine has, its full path as Windows names it."""
        found = _said( box.guest( _ps( FIND_PYTHON ), capture = True ), "errand-python=" )
        if found:
            return found
        raise VmError( f"no Python on {box.ssh.host} ( py -3, python ): install one, or say "
                       "WindowsBox( python = \"3.13.1\" ) and errand installs it into C:\\errand with uv" )


def _said( got, mark: str ) -> str:
    """The value a PowerShell script printed after `mark`, or ''."""
    for l in ( getattr( got, "stdout", "" ) or "" ).splitlines():
        if l.startswith( mark ):
            return l[ len( mark ) : ].strip()
    return ""
