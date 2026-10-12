"""Windows, as an environment: a machine errand installs, boots, and lets go of.

    errand.envs[ "win" ] = errand.Env( [ errand.Windows() ] )

    errand --env win -- cmake -B build -G Ninja
    errand --env win -- cmake --build build

That is the whole declaration, and what it gets by default is a Windows Server
evaluation, which needs no licence for 180 days and is rebuilt before it runs
out, with the MSVC build tools in it ( cl, link, cmake, ninja, msbuild, already
on PATH ). A key, another ISO, a Python, more to install: each is one argument.

The layer is a virtual machine under QEMU, reached through ssh -- so it is
first in its stack, like `Ssh`, and for the same reason: getting there means
copying the project in before and fetching what was asked for after.

**Three moments, three costs.**

    install   once per declaration, 20 to 60 minutes. What comes out is a
              disk image, kept in ~/.cache/errand/windows/<fingerprint>/ and
              shared by every project that declares the same thing. It is a
              build like any other layer's: `--setup` does it, a changed
              declaration redoes it, `--dry-run` says so.
    boot      once per warm period, half a minute to a few. Every boot starts
              from a fresh copy-on-write layer over that image, so nothing a
              run left behind survives a restart.
    run       once per command: a tar of the project goes in, the command runs
              through cmd.exe, what `fetch` names comes back.

**Kept warm, and counted while it is.** A booted machine stays up `keep` after
its last command, so the next one does not pay for the boot. All that time it
holds its cores and its memory -- whether it is compiling or idle -- so it
holds them IN THE QUEUE, under a claim like any other work, and shows up in
`errand --queue`. A small keeper process owns the machine and the claim: it
starts QEMU once the queue has room, stops it once idle, and is what
`errand --vm-stop` stops. Commands on one machine take turns.

Nothing here is Windows-specific but the recipe; another guest would be another
recipe over the same `Machine`.
"""
from __future__ import annotations

import contextlib
import fcntl
import fnmatch
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import layers as L, queue

# Windows Server 2025, evaluation edition, English: 180 days without a key, and
# a download Microsoft hands out without asking anything. Index 1 of it is
# Standard, Server Core -- no desktop, which nothing run over ssh needs, and
# which installs and boots in half the time.
EVALUATION_ISO = "https://go.microsoft.com/fwlink/?linkid=2293312&clcid=0x409&culture=en-us&country=us"
REBUILD_AFTER  = 170         # days: rebuilt a little before the 180 run out and Windows starts shutting itself down

USER     = "Administrator"
# Only ever typed at the console of a machine nobody looks at: sshd takes a key,
# and password logins are switched off before the port is ever reachable.
PASSWORD = "Errand-vm-1!"
VCVARS   = r"C:\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
BUILD_TOOLS = "https://aka.ms/vs/17/release/vs_BuildTools.exe"

# Bumped whenever what an image is made of changes in this file: the recipe is
# part of the declaration, and an edit to it must be noticed like any other.
RECIPE = 1

INSTALL_TIMEOUT = 4 * 3600
BOOT_TIMEOUT    = 20 * 60
EXCLUDES = [ *L.RSYNC_EXCLUDES, ".errand" ]


class VmError( RuntimeError ):
    """Something about this machine cannot run one: said once, plainly."""


# ── the layer ────────────────────────────────────────────────────────────────

@dataclass
class Windows:
    """Must be the first layer. Everything after it runs on Windows.

    Every argument has a default that covers the common case -- compiling and
    testing native code -- so most declarations name none of them.
    """
    iso      : str | None = None     # a path or a URL; None is the evaluation
    key      : str | None = None     # a product key; None is the evaluation, which needs none
    index    : int = 1               # which image of the ISO: 1 is Server Core on the evaluation
    cpus     : int = 4
    ram      : str = "8G"
    disk     : str = "64G"           # grows as it is written, up to this
    msvc     : bool = True           # the build tools, and vcvars64 before every command
    python   : str | None = None     # "3.13.1": that python.org release, on PATH
    provision: list = field( default_factory = list )   # PowerShell: a `.ps1` of the project, or a line
    fetch    : list = field( default_factory = list )   # what to bring back after each command
    keep     : str = "15m"           # how long a booted machine waits for the next command
    root     : str | None = None     # where the project goes; C:/errand/<project name>

    # Not a field: what `layers.vm_of` recognizes, like `Ssh` is recognized by its class.
    is_vm = True

    def wrap( self, cmd: L.Command, ctx: L.Context ) -> L.Command:
        # Never folded: `run` takes over, as for Ssh -- getting there means
        # booting, copying in, and fetching afterwards.
        raise RuntimeError( "Windows must be the first layer of an environment" )

    def describe( self ):
        return "windows"

    # -- kept current, like any other layer ----------------------------------

    def spec( self, ctx ) -> list:
        # Flat: `fingerprint` reads the CONTENT of a path only at the top level,
        # and a script edited is a script that must be run again.
        return [ RECIPE, _iso_identity( self.iso, ctx.root ), self.key, self.index, self.disk,
                 self.msvc, self.python, *[ _provision_part( p, ctx.root ) for p in self.provision ] ]

    def image( self, ctx ) -> Path:
        """Where the installed disk lives: named by what it was installed FROM,
        so two projects declaring the same Windows share one."""
        return images_dir() / L.fingerprint( *self.spec( ctx ) )

    def probe( self, ctx ) -> bool:
        ready = self.image( ctx ) / "ready"
        if not ready.exists():
            return False
        # An evaluation counts down from the day it was installed, and shuts
        # itself down every hour once it has run out -- which would look like a
        # flaky build rather than an expired licence. Rebuilt before that.
        age = ( time.time() - ready.stat().st_mtime ) / 86400
        return bool( self.key ) or age < REBUILD_AFTER

    def build( self, ctx ) -> list:
        recipe = {
            "image": str( self.image( ctx ) ), "iso": self.iso or EVALUATION_ISO,
            "root" : str( ctx.root ), "key": self.key, "index": self.index,
            "cpus" : self.cpus, "ram": self.ram, "disk": self.disk, "msvc": self.msvc,
            "python": self.python, "provision": [ _provision_part( p, ctx.root, as_path = True )
                                                  for p in self.provision ],
        }
        return [ L.sh( [ sys.executable, "-m", "errand.vm", "build", json.dumps( recipe ) ] ) ]

    # -- being let in ---------------------------------------------------------

    def guest_root( self, ctx ) -> str:
        return self.root or f"C:/errand/{ctx.root.name}"

    def line( self, cmd: L.Command, guest_root: str ) -> str:
        """`cmd` as one cmd.exe line, run from the project's copy over there."""
        parts = [ f'cd /d "{_backslashed( guest_root )}"' ]
        if self.msvc:
            parts.append( f'call "{VCVARS}" >nul' )
        # The quoted form: `set "K=v"` keeps no trailing blank before the `&&`.
        parts += [ f'set "{k}={v}"' for k, v in cmd.env.items() ]
        parts.append( subprocess.list2cmdline( [ str( a ) for a in cmd.argv ] ) )
        return " && ".join( parts )

    def run( self, inner, cmd: L.Command, ctx: L.Context, pull = None, echo = print ):
        image = self.image( ctx )
        if not ( image / "ready" ).exists():
            echo( "  windows is not installed yet -- errand --env <name> --setup" )
            return 1
        there = self.guest_root( ctx )
        # PYTHONPATH as computed here names directories of THIS machine.
        env = { k: v for k, v in cmd.env.items() if k != "PYTHONPATH" }
        wrapped = L.compose( inner, L.Command( L.under( cmd.argv, "python" ), env ),
                             L.Context( root = Path( there ), tags = ctx.tags, remote = True ) )
        try:
            with Machine( image ).using( self, echo ) as m:
                echo( f"  copy in -> windows:{there}" )
                m.push( ctx.root, there )
                line = self.line( wrapped, there )
                echo( f"  > {line}" )
                code = m.ssh( line ).returncode
                wanted = [ *( pull or [ ] ), *self.fetch ]
                if wanted:
                    echo( f"  fetch <- windows:{there} [{', '.join( wanted )}]" )
                    m.fetch( wanted, there, ctx.root )
                return code
        except VmError as err:
            echo( f"  {err}" )
            return 1
        except subprocess.CalledProcessError as err:
            echo( f"  could not copy the project in: {err}" )
            return 1


def _backslashed( path: str ) -> str:
    return path.replace( "/", "\\" )


def _iso_identity( iso, root: Path ):
    """What an ISO is, for the fingerprint, without reading five gigabytes of it."""
    if not iso:
        return EVALUATION_ISO
    if "://" in iso:
        return iso
    path = Path( iso ).expanduser()
    path = path if path.is_absolute() else root / path
    try:
        st = path.stat()
        return f"{path}:{st.st_size}:{int( st.st_mtime )}"
    except OSError:
        return f"<missing {path}>"


def _provision_part( p: str, root: Path, as_path = False ):
    """A `.ps1` of the project is hashed by content ( or handed over by path ); a
    line of PowerShell is itself."""
    if str( p ).endswith( ".ps1" ):
        path = Path( p ) if Path( p ).is_absolute() else root / p
        return str( path ) if as_path else path
    return { "line": p } if as_path else p


def _seconds( text ) -> float:
    """`15m`, `2h`, `30s`, `0`, 90 -> seconds."""
    text = str( text ).strip().lower()
    scale = { "s": 1, "m": 60, "h": 3600, "d": 86400 }
    if text and text[ -1 ] in scale:
        return float( text[ : -1 ] ) * scale[ text[ -1 ] ]
    return float( text )


# ── where things live ────────────────────────────────────────────────────────

def cache_dir( ) -> Path:
    return Path( os.environ.get( "XDG_CACHE_HOME" ) or Path.home() / ".cache" ) / "errand"


def images_dir( ) -> Path:
    return cache_dir() / "windows"


# ── QEMU ─────────────────────────────────────────────────────────────────────

QEMU_HINT = "apt install qemu-system-x86 qemu-utils  ·  dnf install qemu-kvm qemu-img  ·  brew install qemu"


def _tool( name: str, hint: str ) -> str:
    found = shutil.which( name )
    if not found:
        raise VmError( f"{name} is not installed -- {hint}" )
    return found


def accel( ) -> tuple:
    """-> ( accelerator, cpu ). Windows here is x86-64, so the host must be too:
    emulating one on an ARM machine is measured in hours per boot."""
    arch = platform.machine().lower()
    if arch not in ( "x86_64", "amd64" ):
        raise VmError( f"this machine is {arch}, and the Windows errand installs is x86-64: "
                       f"it would be emulated instruction by instruction. Not supported" )
    if sys.platform == "darwin":
        return "hvf", "host"
    if os.access( "/dev/kvm", os.R_OK | os.W_OK ):
        # The Hyper-V enlightenments: Windows asks for them, and without them
        # it spins on timers it believes are real hardware.
        return "kvm", "host,hv_relaxed,hv_vapic,hv_spinlocks=0x1fff,hv_time"
    return "tcg", "max"


def _escaped( path ) -> str:
    """A path inside a QEMU option string, where a comma separates options."""
    return str( path ).replace( ",", ",," )


def qemu_argv( disk: Path, *, port: int, cpus: int, ram, iso: Path | None = None,
               media: Path | None = None, pidfile: Path | None = None ) -> list:
    how, cpu = accel()
    argv = [ _tool( "qemu-system-x86_64", QEMU_HINT ),
             "-machine", "q35", "-accel", how, "-cpu", cpu,
             "-smp", str( cpus ), "-m", f"{int( queue.parse_size( ram ) )}M",
             "-rtc", "base=utc",
             "-monitor", "none", "-serial", "none", "-parallel", "none",
             # Inbox drivers only -- an AHCI disk and an e1000e card are what
             # Windows knows without being given anything, so there is no
             # driver disk to fetch and keep in step.
             "-drive", f"if=none,id=system,file={_escaped( disk )},format=qcow2,discard=unmap",
             "-device", "ide-hd,drive=system,bus=ide.0",
             "-nic", f"user,model=e1000e,hostfwd=tcp:127.0.0.1:{port}-:22" ]
    # Somebody debugging an install wants to SEE it: ERRAND_VM_VNC=1 puts the
    # screen on vnc://127.0.0.1:5901.
    vnc = os.environ.get( "ERRAND_VM_VNC" )
    argv += [ "-vnc", f"127.0.0.1:{vnc}" ] if vnc else [ "-display", "none" ]
    if iso is not None:
        # Booted from once: the reboots in the middle of setup must land on the
        # disk it is writing, not start the install over.
        argv += [ "-drive", f"if=none,id=setup,file={_escaped( iso )},media=cdrom,readonly=on",
                  "-device", "ide-cd,drive=setup,bus=ide.1", "-boot", "once=d" ]
    if media is not None:
        # A directory of this machine, seen by the guest as a USB stick. Setup
        # looks for `autounattend.xml` at the root of removable drives -- of
        # its own accord, which is the whole trick of an unattended install.
        argv += [ "-drive", f"if=none,id=media,file=fat:{_escaped( media )},format=raw",
                  "-device", "qemu-xhci", "-device", "usb-storage,drive=media,removable=on" ]
    if pidfile is not None:
        argv += [ "-pidfile", str( pidfile ) ]
    return argv


def free_port( ) -> int:
    with socket.socket() as s:
        s.bind( ( "127.0.0.1", 0 ) )
        return s.getsockname()[ 1 ]


# ── one installed image, and the machine booted from it ─────────────────────

def _lock( path: Path, block = True ):
    """An exclusive flock on `path` -> the open file, or None if not now."""
    handle = open( path, "a" )
    try:
        fcntl.flock( handle, fcntl.LOCK_EX | ( 0 if block else fcntl.LOCK_NB ) )
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _alive( pid ) -> bool:
    try:
        os.kill( int( pid ), 0 )
        return True
    except ( OSError, ValueError ):
        return False


def _read( path: Path, default = "" ) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return default


class Machine:
    """The machine booted from one image, with its keeper.

    Two locks, always taken in this order:

        start.lock   held while deciding whether a keeper must be started, and
                     by a keeper while it stops -- so nobody decides "it is up"
                     about a machine that is going down
        use.lock     held for as long as a command uses the machine -- which
                     is how commands take turns, and how the keeper knows that
                     nobody is about to
    """

    def __init__( self, image: Path ):
        self.image = image
        self.live  = image / "live"

    # -- the caller's side ----------------------------------------------------

    @property
    def port( self ) -> int:
        return int( _read( self.live / "port", "0" ) )

    def state( self ) -> str:
        return _read( self.live / "state", "stopped" )

    def keeper_alive( self ) -> bool:
        return _alive( _read( self.live / "keeper.pid" ) ) and self.state() not in ( "stopping", "stopped" )

    @contextlib.contextmanager
    def using( self, layer: Windows, echo = print ):
        self.live.mkdir( parents = True, exist_ok = True )
        start = _lock( self.image / "start.lock" )
        try:
            if not self.keeper_alive():
                self._spawn( layer )
            use = _lock( self.image / "use.lock" )
        finally:
            start.close()
        try:
            ( self.live / "used" ).touch()
            self._wait_ready( echo )
            yield self
        finally:
            ( self.live / "used" ).touch()
            use.close()

    def _spawn( self, layer: Windows ):
        # Said here, where somebody reads it, rather than in the keeper's log.
        accel()
        _tool( "qemu-system-x86_64", QEMU_HINT )
        _tool( "qemu-img", QEMU_HINT )
        ( self.live / "config.json" ).write_text( json.dumps( {
            "cpus": layer.cpus, "ram": layer.ram, "keep": _seconds( layer.keep ) } ) )
        ( self.live / "state" ).write_text( "starting" )
        env = { k: v for k, v in os.environ.items() if k != queue.CLAIM }
        # Wherever this errand was imported from is where the keeper imports it
        # from: a checkout on PYTHONPATH must not be swapped for an install.
        package_parent = str( Path( __file__ ).resolve().parent.parent )
        env[ "PYTHONPATH" ] = os.pathsep.join( p for p in ( package_parent, env.get( "PYTHONPATH" ) ) if p )
        with open( self.live / "keeper.log", "w" ) as log:
            child = subprocess.Popen( [ sys.executable, "-m", "errand.vm", "keep", str( self.image ) ],
                                      stdin = subprocess.DEVNULL, stdout = log, stderr = subprocess.STDOUT,
                                      env = env, start_new_session = True )
        ( self.live / "keeper.pid" ).write_text( str( child.pid ) )

    def _wait_ready( self, echo ):
        said, since = None, time.time()
        while True:
            state = self.state()
            if state == "ready":
                return
            if not _alive( _read( self.live / "keeper.pid" ) ) or state in ( "stopped", "failed" ):
                tail = _read( self.live / "keeper.log" )[ -800 : ]
                raise VmError( f"the windows machine did not come up:\n{tail}" )
            if state != said:
                echo( { "starting": "  starting the windows machine",
                        "queued"  : "  waiting for the machine to have room for it ( errand --queue )",
                        "booting" : "  booting windows" }.get( state, f"  windows: {state}" ) )
                said, since = state, time.time()
            if state == "booting" and time.time() - since > BOOT_TIMEOUT:
                raise VmError( f"windows did not answer within {BOOT_TIMEOUT // 60} minutes" )
            time.sleep( 1.0 )

    # -- talking to it --------------------------------------------------------

    def options( self ) -> list:
        """What ssh and scp both need: the key, and no host key to remember --
        every boot is a machine nobody has met, on a port that changes."""
        return [ "-i", str( self.image / "key" ), "-o", "IdentitiesOnly=yes",
                 "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                 "-o", "LogLevel=ERROR", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5" ]

    def ssh( self, line: str, **kw ):
        return subprocess.run( [ "ssh", "-p", str( self.port ), *self.options(),
                                 f"{USER}@127.0.0.1", line ], **kw )

    def scp( self, src: str, dst: str ):
        subprocess.run( [ "scp", "-q", "-P", str( self.port ), *self.options(), src, dst ],
                        check = True )

    def answers( self ) -> bool:
        try:
            got = self.ssh( "echo errand-ok", capture_output = True, text = True, timeout = 30 )
        except subprocess.TimeoutExpired:
            return False
        return got.returncode == 0 and "errand-ok" in got.stdout

    def push( self, local_root: Path, there: str ):
        """The project, minus what rsync would leave out too, as one tar: no
        rsync on Windows, and one file crosses far faster than ten thousand."""
        win = _backslashed( there )
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path( tmp ) / "push.tar"
            with tarfile.open( archive, "w", dereference = True ) as tar:
                for path, rel in _walk( local_root ):
                    tar.add( path, arcname = rel, recursive = False )
            self.ssh( f'if not exist "{win}" mkdir "{win}"', check = True )
            self.scp( str( archive ), f"{USER}@127.0.0.1:{there}.tar" )
        self.ssh( f'tar -x -f "{there}.tar" -C "{there}" && del "{win}.tar"', check = True )

    def fetch( self, paths, there: str, local_root: Path ):
        """Best effort, as over ssh: what the command never produced is nothing to bring back."""
        for p in paths:
            p = str( p ).strip( "/" )
            got = self.ssh( f'cd /d "{_backslashed( there )}" && if exist "{_backslashed( p )}" '
                            f'tar -c -f "{there}.out.tar" "{p}"', capture_output = True )
            if got.returncode:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                archive = Path( tmp ) / "out.tar"
                try:
                    self.scp( f"{USER}@127.0.0.1:{there}.out.tar", str( archive ) )
                except subprocess.CalledProcessError:
                    continue
                with tarfile.open( archive ) as tar:
                    if hasattr( tarfile, "data_filter" ):
                        tar.extractall( local_root, filter = "data" )
                    else:
                        tar.extractall( local_root )

    # -- the keeper's side ----------------------------------------------------

    def keep( self ) -> int:
        """Hold a claim, boot, wait for idleness, stop. Run as its own process."""
        config = json.loads( ( self.live / "config.json" ).read_text() )
        ( self.live / "keeper.pid" ).write_text( str( os.getpid() ) )
        # A SIGTERM ( `--vm-stop` ) must unwind through the `finally` below, or
        # QEMU outlives its keeper and nobody counts what it holds.
        signal.signal( signal.SIGTERM, lambda *_: sys.exit( 0 ) )
        self._kill_leftover()
        overlay, machine = self.live / "overlay.qcow2", None
        try:
            ( self.live / "state" ).write_text( "queued" )
            with queue.claim( { "cpus": config[ "cpus" ], "ram": config[ "ram" ] },
                              label = f"windows vm {self.image.name[ : 8 ]}" ):
                ( self.live / "port" ).write_text( str( free_port() ) )
                overlay.unlink( missing_ok = True )
                _overlay( self.image / "base.qcow2", overlay )
                ( self.live / "state" ).write_text( "booting" )
                machine = subprocess.Popen( qemu_argv( overlay, port = self.port, cpus = config[ "cpus" ],
                                                       ram = config[ "ram" ], pidfile = self.live / "qemu.pid" ),
                                            stdin = subprocess.DEVNULL )
                if not _wait_for( self, machine, BOOT_TIMEOUT ):
                    ( self.live / "state" ).write_text( "failed" )
                    return 1
                ( self.live / "state" ).write_text( "ready" )
                held = None          # the locks, kept until this process is gone
                while machine.poll() is None and held is None:
                    time.sleep( 2.0 )
                    held = self._idle( config[ "keep" ] )
        finally:
            ( self.live / "state" ).write_text( "stopping" )
            # Thrown away rather than shut down: the next boot starts from the
            # image again, so there is nothing in this one worth a clean exit.
            if machine is not None and machine.poll() is None:
                machine.terminate()
                try:
                    machine.wait( timeout = 30 )
                except subprocess.TimeoutExpired:
                    machine.kill()
            overlay.unlink( missing_ok = True )
            ( self.live / "keeper.pid" ).unlink( missing_ok = True )
            ( self.live / "state" ).write_text( "stopped" )
        return 0

    def _idle( self, keep: float ):
        """Long enough since the last command, and nobody about to send one?
        -> the locks, to be held until this process exits; or None."""
        try:
            since = time.time() - ( self.live / "used" ).stat().st_mtime
        except OSError:
            since = keep + 1
        if since <= keep:
            return None
        start = _lock( self.image / "start.lock", block = False )
        if start is None:
            return None
        use = _lock( self.image / "use.lock", block = False )
        if use is None:
            start.close()
            return None
        ( self.live / "state" ).write_text( "stopping" )
        return ( start, use )

    def _kill_leftover( self ):
        """A keeper killed outright leaves its QEMU running, holding a port and
        memory nobody counts any more. The next keeper finishes the job."""
        pid = _read( self.live / "qemu.pid" )
        if pid and _alive( pid ):
            with contextlib.suppress( OSError ):
                os.kill( int( pid ), signal.SIGTERM )
        ( self.live / "qemu.pid" ).unlink( missing_ok = True )


def _overlay( base: Path, overlay: Path ):
    subprocess.run( [ _tool( "qemu-img", QEMU_HINT ), "create", "-q", "-f", "qcow2",
                      "-b", str( base ), "-F", "qcow2", str( overlay ) ], check = True )


def _wait_for( machine: Machine, process, timeout: float ) -> bool:
    """Until sshd answers, QEMU dies, or `timeout`."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        if machine.answers():
            return True
        time.sleep( 3.0 )
    return False


def _walk( root: Path ):
    """( path, relative name ) of everything worth copying in."""
    def excluded( name ):
        return any( fnmatch.fnmatch( name, e ) for e in EXCLUDES )
    for here, dirs, files in os.walk( root ):
        dirs[ : ] = [ d for d in dirs if not excluded( d ) ]
        for name in dirs + files:
            if excluded( name ):
                continue
            path = Path( here ) / name
            if path.is_symlink() and not path.exists():
                continue                # dangling: nothing to copy
            yield path, path.relative_to( root ).as_posix()


def running( ) -> list:
    """-> [ Machine ] whose keeper is alive."""
    if not images_dir().is_dir():
        return [ ]
    return [ m for m in ( Machine( d ) for d in sorted( images_dir().iterdir() ) if d.is_dir() )
             if _alive( _read( m.live / "keeper.pid" ) ) ]


def stop_all( echo = print ) -> int:
    """`errand --vm-stop`: every warm machine, now."""
    machines = running()
    for m in machines:
        echo( f"  stopping windows vm {m.image.name[ : 8 ]}" )
        with contextlib.suppress( OSError, ValueError ):
            os.kill( int( _read( m.live / "keeper.pid" ) ), signal.SIGTERM )
    if not machines:
        echo( "  no virtual machine is running" )
    return 0


# ── installing ───────────────────────────────────────────────────────────────

def obtain_iso( where: str, root: Path, echo = print ) -> Path:
    if "://" not in where:
        path = Path( where ).expanduser()
        path = path if path.is_absolute() else root / path
        if not path.exists():
            raise VmError( f"no ISO at {path}" )
        return path
    target = cache_dir() / "iso" / f"{L.fingerprint( where )}.iso"
    if target.exists():
        return target
    target.parent.mkdir( parents = True, exist_ok = True )
    partial = target.with_suffix( ".part" )
    echo( f"  downloading {where}" )
    try:
        with urllib.request.urlopen( where, timeout = 60 ) as got, open( partial, "wb" ) as out:
            total = int( got.headers.get( "Content-Length" ) or 0 )
            done, told = 0, -1
            while chunk := got.read( 1 << 20 ):
                out.write( chunk )
                done += len( chunk )
                if total and ( tenth := done * 10 // total ) != told:
                    echo( f"    {done >> 20} / {total >> 20} MB" )
                    told = tenth
    except OSError as err:
        raise VmError( f"could not download the ISO ( {err} ) -- download it by hand and "
                       f"declare it: errand.Windows( iso = 'path/to/windows.iso' )" ) from err
    os.replace( partial, target )
    return target


def autounattend( *, key = None, index = 1 ) -> str:
    """What Windows Setup reads instead of asking: one partition, the image at
    `index`, an Administrator who logs on once, and that logon running
    `errand-setup.ps1` from whichever drive carries it."""
    product = ( f"<ProductKey><Key>{key}</Key><WillShowUI>OnError</WillShowUI></ProductKey>"
                if key else "" )
    component = ( 'processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" '
                  'language="neutral" versionScope="nonSxS"' )
    # Windows 11 refuses to install without a TPM and Secure Boot; neither
    # matters to a compiler. Harmless on Server, which does not check.
    bypass = "".join(
        f'<RunSynchronousCommand wcm:action="add"><Order>{i}</Order>'
        f'<Path>reg add HKLM\\SYSTEM\\Setup\\LabConfig /v {what} /t REG_DWORD /d 1 /f</Path>'
        f'</RunSynchronousCommand>'
        for i, what in enumerate( ( "BypassTPMCheck", "BypassSecureBootCheck", "BypassRAMCheck" ), 1 ) )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-International-Core-WinPE" {component}>
      <SetupUILanguage><UILanguage>en-US</UILanguage></SetupUILanguage>
      <InputLocale>en-US</InputLocale>
      <SystemLocale>en-US</SystemLocale>
      <UILanguage>en-US</UILanguage>
      <UserLocale>en-US</UserLocale>
    </component>
    <component name="Microsoft-Windows-Setup" {component}>
      <RunSynchronous>{bypass}</RunSynchronous>
      <DiskConfiguration>
        <Disk wcm:action="add">
          <DiskID>0</DiskID>
          <WillWipeDisk>true</WillWipeDisk>
          <CreatePartitions>
            <CreatePartition wcm:action="add"><Order>1</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
          </CreatePartitions>
          <ModifyPartitions>
            <ModifyPartition wcm:action="add">
              <Order>1</Order><PartitionID>1</PartitionID><Active>true</Active>
              <Format>NTFS</Format><Label>Windows</Label><Letter>C</Letter>
            </ModifyPartition>
          </ModifyPartitions>
        </Disk>
      </DiskConfiguration>
      <ImageInstall>
        <OSImage>
          <InstallFrom><MetaData wcm:action="add"><Key>/IMAGE/INDEX</Key><Value>{index}</Value></MetaData></InstallFrom>
          <InstallTo><DiskID>0</DiskID><PartitionID>1</PartitionID></InstallTo>
        </OSImage>
      </ImageInstall>
      <UserData>
        <AcceptEula>true</AcceptEula>
        {product}
      </UserData>
    </component>
  </settings>
  <settings pass="specialize">
    <component name="Microsoft-Windows-Shell-Setup" {component}>
      <ComputerName>errand-win</ComputerName>
      <TimeZone>UTC</TimeZone>
    </component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup" {component}>
      <UserAccounts>
        <AdministratorPassword><Value>{PASSWORD}</Value><PlainText>true</PlainText></AdministratorPassword>
      </UserAccounts>
      <AutoLogon>
        <Enabled>true</Enabled><Username>{USER}</Username><LogonCount>1</LogonCount>
        <Password><Value>{PASSWORD}</Value><PlainText>true</PlainText></Password>
      </AutoLogon>
      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <ProtectYourPC>3</ProtectYourPC>
      </OOBE>
      <FirstLogonCommands>
        <SynchronousCommand wcm:action="add">
          <Order>1</Order>
          <CommandLine>cmd /c for %d in (D E F G H I J K L M) do if exist %d:\\errand-setup.ps1 powershell -NoProfile -ExecutionPolicy Bypass -File %d:\\errand-setup.ps1</CommandLine>
          <Description>errand</Description>
        </SynchronousCommand>
      </FirstLogonCommands>
    </component>
  </settings>
</unattend>
"""


def setup_script( *, msvc = True, python = None, provision = ( ) ) -> str:
    """The first logon, unattended: sshd first ( so a failure further down can
    still be looked at ), then the tools, then a line saying how it went, then
    off -- the power going off is how the host knows the install is over."""
    steps = [ ]
    if msvc:
        steps.append( f"""
    Step 'msvc build tools'
    Invoke-WebRequest -UseBasicParsing '{BUILD_TOOLS}' -OutFile C:\\vs_buildtools.exe
    $p = Start-Process C:\\vs_buildtools.exe -Wait -PassThru -ArgumentList @(
        '--quiet', '--wait', '--norestart', '--nocache', '--installPath', 'C:\\BuildTools',
        '--add', 'Microsoft.VisualStudio.Workload.VCTools', '--includeRecommended' )
    if ( $p.ExitCode -ne 0 -and $p.ExitCode -ne 3010 ) {{ throw "build tools: exit $( $p.ExitCode )" }}
    Remove-Item C:\\vs_buildtools.exe""" )
    if python:
        steps.append( f"""
    Step 'python {python}'
    Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/{python}/python-{python}-amd64.exe' -OutFile C:\\python-setup.exe
    $p = Start-Process C:\\python-setup.exe -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0' )
    if ( $p.ExitCode -ne 0 ) {{ throw "python: exit $( $p.ExitCode )" }}
    Remove-Item C:\\python-setup.exe""" )
    for i, p in enumerate( provision ):
        if isinstance( p, dict ):
            steps.append( f"\n    Step 'provision: {p[ 'line' ][ : 40 ]}'\n    {p[ 'line' ]}" )
        else:
            steps.append( f"\n    Step '{Path( p ).name}'\n    & ( Join-Path $media 'errand-provision-{i}.ps1' )" )
    return f"""$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Start-Transcript -Path C:\\errand-setup.log
$media = Split-Path -Parent $MyInvocation.MyCommand.Path
function Step( $what ) {{ Write-Host "== $what" }}
New-Item -ItemType Directory -Force C:\\errand | Out-Null
try {{
    Step 'sshd'
    if ( -not ( Get-Service sshd -ErrorAction SilentlyContinue ) ) {{
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
    }}
    Set-Service sshd -StartupType Automatic
    Start-Service sshd
    $keys = 'C:\\ProgramData\\ssh\\administrators_authorized_keys'
    Copy-Item ( Join-Path $media 'errand_key.pub' ) $keys
    icacls $keys /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null
    $config = 'C:\\ProgramData\\ssh\\sshd_config'
    ( Get-Content $config ) -replace '^#?PasswordAuthentication .*', 'PasswordAuthentication no' | Set-Content $config
    Restart-Service sshd
    New-NetFirewallRule -Name errand-sshd -DisplayName 'errand sshd' -Profile Any -Direction Inbound `
        -Protocol TCP -LocalPort 22 -Action Allow -ErrorAction SilentlyContinue | Out-Null

    # A machine that lives for minutes has no use for updates, and the
    # scanning of every file a compiler writes halves its speed.
    Step 'quiet'
    Stop-Service wuauserv -ErrorAction SilentlyContinue
    Set-Service wuauserv -StartupType Disabled -ErrorAction SilentlyContinue
    try {{ Set-MpPreference -DisableRealtimeMonitoring $true -ExclusionPath C:\\errand, C:\\BuildTools }} catch {{ }}
{''.join( steps )}
    Set-Content C:\\errand\\setup.status 'ok'
}} catch {{
    Set-Content C:\\errand\\setup.status "failed: $_"
}} finally {{
    Stop-Transcript
    Stop-Computer -Force
}}
"""


def build( recipe: dict, echo = print ) -> int:
    """`--setup` for a `Windows` layer: install from the ISO, check it answers,
    and only then call it ready."""
    image = Path( recipe[ "image" ] )
    root  = Path( recipe[ "root" ] )
    try:
        for tool in ( "ssh", "scp", "ssh-keygen" ):
            _tool( tool, "it comes with OpenSSH" )
        _tool( "qemu-img", QEMU_HINT )
        how, _ = accel()
        if how == "tcg":
            echo( "  no hardware virtualization here ( /dev/kvm ): this will take HOURS" )
        iso = obtain_iso( recipe[ "iso" ], root, echo )
    except VmError as err:
        echo( f"  {err}" )
        return 1

    image.mkdir( parents = True, exist_ok = True )
    work = image / "build"
    shutil.rmtree( work, ignore_errors = True )
    media = work / "media"
    media.mkdir( parents = True )
    key = image / "key"
    if not key.exists():
        subprocess.run( [ "ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "errand-vm",
                          "-f", str( key ) ], check = True )
    shutil.copy( f"{key}.pub", media / "errand_key.pub" )
    ( media / "autounattend.xml" ).write_text( autounattend( key = recipe[ "key" ], index = recipe[ "index" ] ) )
    for i, p in enumerate( recipe[ "provision" ] ):
        if not isinstance( p, dict ):
            shutil.copy( p, media / f"errand-provision-{i}.ps1" )
    ( media / "errand-setup.ps1" ).write_text( setup_script( msvc = recipe[ "msvc" ], python = recipe[ "python" ],
                                                             provision = recipe[ "provision" ] ) )
    disk = work / "disk.qcow2"
    subprocess.run( [ "qemu-img", "create", "-q", "-f", "qcow2", str( disk ), recipe[ "disk" ] ], check = True )

    with queue.claim( { "cpus": recipe[ "cpus" ], "ram": recipe[ "ram" ] },
                      label = "installing windows", echo = echo ):
        echo( "  installing windows -- 20 to 60 minutes, with nothing to watch "
              "( ERRAND_VM_VNC=1 to watch on vnc://127.0.0.1:5901 )" )
        started = time.time()
        with open( work / "qemu.log", "w" ) as log:
            process = subprocess.Popen( qemu_argv( disk, port = free_port(), cpus = recipe[ "cpus" ],
                                                   ram = recipe[ "ram" ], iso = iso, media = media ),
                                        stdin = subprocess.DEVNULL, stdout = log, stderr = subprocess.STDOUT )
            report = started + 600
            while process.poll() is None:
                time.sleep( 10.0 )
                if time.time() > report:
                    echo( f"    still installing, {( time.time() - started ) / 60:.0f} min" )
                    report += 600
                if time.time() - started > INSTALL_TIMEOUT:
                    process.kill()
                    echo( f"  the install did not finish in {INSTALL_TIMEOUT // 3600} hours" )
                    return 1
        if process.returncode:
            echo( f"  qemu stopped with code {process.returncode}:\n{_read( work / 'qemu.log' )[ -800 : ]}" )
            return 1
        os.replace( disk, image / "base.qcow2" )

        echo( f"  installed in {( time.time() - started ) / 60:.0f} min; checking that it answers" )
        if not _check( image, recipe, echo ):
            return 1

    ( image / "ready" ).write_text( time.strftime( "%Y-%m-%dT%H:%M:%S%z" ) + "\n" )
    shutil.rmtree( work, ignore_errors = True )
    echo( f"  windows is ready: {image}" )
    return 0


def _check( image: Path, recipe: dict, echo ) -> bool:
    """Boot it once, the way every run will, and read back how setup went."""
    machine = Machine( image )
    machine.live.mkdir( parents = True, exist_ok = True )
    ( machine.live / "port" ).write_text( str( free_port() ) )
    overlay = image / "build" / "check.qcow2"
    _overlay( image / "base.qcow2", overlay )
    process = subprocess.Popen( qemu_argv( overlay, port = machine.port, cpus = recipe[ "cpus" ],
                                           ram = recipe[ "ram" ] ), stdin = subprocess.DEVNULL )
    try:
        if not _wait_for( machine, process, BOOT_TIMEOUT ):
            echo( "  installed, but sshd never answered: the first logon script did not run, "
                  "or failed before sshd -- ERRAND_VM_VNC=1 and --setup=force to watch it" )
            return False
        got = machine.ssh( r"type C:\errand\setup.status", capture_output = True, text = True )
        status = ( got.stdout or "" ).strip()
        if status != "ok":
            log = machine.ssh( r"type C:\errand-setup.log", capture_output = True, text = True ).stdout or ""
            echo( f"  the setup inside windows went wrong: {status or 'no status'}\n{log[ -1500 : ]}" )
            return False
        return True
    finally:
        process.terminate()
        with contextlib.suppress( subprocess.TimeoutExpired ):
            process.wait( timeout = 30 )
        if process.poll() is None:
            process.kill()


# ── `python -m errand.vm …`: what setup and the keeper run ─────────────────

def main( argv = None ) -> int:
    argv = list( sys.argv[ 1 : ] if argv is None else argv )
    if argv[ : 1 ] == [ "build" ] and len( argv ) == 2:
        return build( json.loads( argv[ 1 ] ), echo = lambda s: print( s, flush = True ) )
    if argv[ : 1 ] == [ "keep" ] and len( argv ) == 2:
        return Machine( Path( argv[ 1 ] ) ).keep()
    if argv[ : 1 ] == [ "stop" ]:
        return stop_all()
    print( "usage: python -m errand.vm build RECIPE | keep IMAGE | stop", file = sys.stderr )
    return 2


if __name__ == "__main__":
    sys.exit( main() )
