"""Windows, as an environment: a machine errand installs, boots, and lets go of.

    errand.envs[ "win" ] = errand.Env( [ errand.Windows() ] )

    errand shell --env win -- cmake -B build -G Ninja
    errand shell --env win -- cmake --build build

That is the whole declaration, and what it gets by default is a Windows Server
evaluation, which needs no licence for 180 days and is rebuilt before it runs
out, with the MSVC build tools in it ( cl, link, cmake, ninja, msbuild, already
on PATH ). A key, another ISO, a Python, more to install: each is one argument.

The layer is a virtual machine under QEMU, reached through ssh -- so it is
first in its stack, like `Ssh`, and for the same reason: getting there means
copying the project in before and fetching what was asked for after. Or it is
right after an `Ssh`, and QEMU runs over there:

    errand.envs[ "win" ] = errand.Env( [ errand.Ssh( host = "x86-box", root = … ),
                                         errand.Windows() ] )

which is how an ARM laptop gets a Windows at all.

**The deciding is here, the doing is wherever QEMU is.** The layer is handed
`ctx.host` -- this machine, or the one an `Ssh` leads to -- and everything it
does there is a shell line run through it, whose answer is read back here:
what that machine is, whether an image is installed, starting QEMU, copying the
project in, running the command, bringing results back. Nothing of errand runs
over there; all it needs there is QEMU, ssh, rsync and tar. The disks and the guest's
key live in THAT machine's cache; the locks, the state and the keeper live in
this one's.

**Three moments, three costs.**

    install   once per declaration, 20 to 60 minutes. What comes out is a
              disk image, kept in ~/.cache/errand/windows/<fingerprint>/ on
              the machine that runs QEMU, and shared by every project that
              declares the same thing. It is a build like any other layer's:
              `errand setup` does it, a changed declaration redoes it, `--dry-run`
              says so.
    boot      once per warm period, half a minute to a few. Every boot starts
              from a fresh copy-on-write layer over that image, so nothing a
              run left behind survives a restart.
    run       once per command: the project goes in ( rsync: what changed ),
              the command runs through cmd.exe, what `fetch` names comes back.

**Up for as long as somebody needs it, and counted while it is.** A booted
machine stays up while an errand process that used it is alive -- so a run of
several commands boots once -- and then `keep` more ( none by default: a boot
is half a minute, and an idle machine holds what it holds for nothing ). All
that time it holds its cores and its memory, so when it runs on this machine
it holds them IN THE QUEUE, under a claim like any other work, and shows up in
`errand queue`. A small keeper process owns the machine ( and the claim ): it
starts QEMU once there is room, stops it once nobody holds it, and is what
`errand vm stop` stops. Commands on one machine take turns.

Nothing here is Windows-specific but the recipe; another guest would be another
recipe over the same `Machine`.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
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

# rsync, which copies the project in: only what changed crosses, where a tar
# carried all of it at every command. MSYS2's, which runs without the rest of
# MSYS2 -- the program and the DLLs it loads, nothing else. Pinned, being what
# an image is made of; downloaded and unpacked by the machine that runs QEMU.
MSYS2_REPO     = "https://repo.msys2.org/msys/x86_64"
MSYS2_PACKAGES = [ "rsync-3.5.1-2", "msys2-runtime-3.6.10-7", "libopenssl-3.6.5-1", "libiconv-1.19-1",
                   "libidn2-2.3.8-1", "libintl-0.22.5-1", "libunistring-1.4.2-1", "liblz4-1.10.0-1",
                   "popt-1.19-1", "libxxhash-0.8.4-1", "libzstd-1.5.7-1" ]
RSYNC_FILES    = [ "rsync.exe", "msys-2.0.dll", "msys-crypto-3.dll", "msys-iconv-2.dll", "msys-idn2-0.dll",
                   "msys-intl-8.dll", "msys-unistring-5.dll", "msys-lz4-1.dll", "msys-popt-0.dll",
                   "msys-xxhash-0.dll", "msys-zstd-1.dll" ]
GUEST_MSYS     = r"C:\errand\msys"
GUEST_RSYNC    = "C:/errand/msys/usr/bin/rsync.exe"

# Bumped whenever what an image is made of changes in this file: the recipe is
# part of the declaration, and an edit to it must be noticed like any other.
RECIPE = 2

INSTALL_TIMEOUT = 4 * 3600
BOOT_TIMEOUT    = 20 * 60
EXCLUDES = [ *L.RSYNC_EXCLUDES, ".errand" ]


class VmError( RuntimeError ):
    """Something about this machine cannot run one: said once, plainly."""


# ── the layer ────────────────────────────────────────────────────────────────

@dataclass
class Windows:
    """First, or right after the `Ssh` that leads to the machine that boots it.
    Everything after it runs on Windows.

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
    keep     : str = "0"             # how long it stays up once no errand process holds it any more
    data     : str | None = "32G"    # a disk kept from one boot to the next, as E:, where the project
                                     # lands -- so what a command leaves ( a build ) is there for the next
                                     # one. Grows as it is written, up to this; None: everything is C:, reset
    root     : str | None = None     # where the project goes; C:/errand/<project name>
    when     : str | None = None     # a condition: an expression over the tags and `phase`

    # Not a field: what `layers.vm_of` recognizes, like `Ssh` is recognized by its class.
    is_vm = True

    def wrap( self, cmd: L.Command, ctx: L.Context ) -> L.Command:
        # Never folded: `run` takes over, as for Ssh -- getting there means
        # booting, copying in, and fetching afterwards.
        raise RuntimeError( "Windows must be the first layer of an environment, or follow its Ssh" )

    def describe( self ):
        return "windows"

    def declared( self ) -> dict:
        """What is INSTALLED, as opposed to how it is booted."""
        return { "iso": self.iso, "key": self.key, "index": self.index, "disk": self.disk,
                 "msvc": self.msvc, "python": self.python, "provision": list( self.provision ) }

    def booted( self ) -> dict:
        return { "cpus": self.cpus, "ram": self.ram, "keep": self.keep, "data": self.data }

    # -- kept current, like any other layer ----------------------------------

    def spec( self, ctx ) -> list:
        # Read from the project as this process sees it, wherever it runs.
        return _spec( self.declared(), ctx.origin )

    def image_name( self, ctx ) -> str:
        """Named by what it was installed FROM, so two projects declaring the
        same Windows share one image."""
        return L.fingerprint( *self.spec( ctx ) )

    def image( self, ctx ) -> Path:
        """Where the installed disk lives when QEMU runs on this machine."""
        return images_dir() / self.image_name( ctx )

    def probe_shell( self, ctx ) -> str:
        return ready_line( self.image_name( ctx ), keyed = bool( self.key ) )

    def probe( self, ctx ) -> bool:
        return ctx.host.shell( self.probe_shell( ctx ), quiet = True ).returncode == 0

    def build( self, ctx ) -> list:
        return [ Install( self, ctx ) ]

    # -- being let in ---------------------------------------------------------

    def guest_root( self, ctx ) -> str:
        if self.root:
            return self.root
        # On the disk that is kept, when there is one: a copy there is updated
        # rather than made again, and what was built beside it stays.
        return f"{DATA_DRIVE}:/{ctx.root.name}" if self.data else f"C:/errand/{ctx.root.name}"

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
        there = self.guest_root( ctx )
        # PYTHONPATH as computed here names directories of THIS machine.
        env = { k: v for k, v in cmd.env.items() if k != "PYTHONPATH" }
        wrapped = L.compose( inner, L.Command( L.under( cmd.argv, "python" ), env ),
                             L.Context( root = Path( there ), tags = ctx.tags, remote = True ) )
        if any( "\n" in str( a ) for a in cmd.argv ):
            # cmd.exe reads one line: the rest would be dropped without a word.
            echo( "  a command for windows is one line: cmd.exe would drop everything after a newline "
                  "-- put the script in a file of the project, and run that" )
            return 1
        name = self.image_name( ctx )
        if ctx.host.shell( ready_line( name, keyed = True ), quiet = True ).returncode:
            echo( f"  windows is not installed yet {where( ctx.host )} -- errand setup <name>" )
            return 1
        try:
            m = Machine( ctx.host, Facts.of( ctx.host ), name )
            need( m.facts, ( "rsync", ), package_hint( m.facts, [ "rsync" ] ) )
            with m.using( self.booted(), echo ):
                echo( f"  copy in -> windows:{there}" )
                m.push( there )
                line = self.line( wrapped, there )
                echo( f"  > {line}" )
                code = m.guest( line ).returncode
                if self.data:
                    m.guest( powershell( FLUSH_SCRIPT ), quiet = True )
                wanted = [ *( pull or [ ] ), *self.fetch ]
                if wanted:
                    echo( f"  fetch <- windows:{there} [{', '.join( wanted )}]" )
                    m.fetch( wanted, there )
                return code
        except VmError as err:
            echo( f"  {err}" )
            return 1
        except subprocess.CalledProcessError as err:
            echo( f"  could not copy the project in: {err}" )
            return 1


class Install:
    """`errand setup` for a `Windows` layer, as one step: what it says it would do,
    and the doing -- many lines through `ctx.host`, decided here between them."""

    def __init__( self, layer: Windows, ctx: L.Context ):
        self.layer, self.ctx = layer, ctx

    def __str__( self ):
        return f"install windows {self.layer.image_name( self.ctx )[ : 8 ]} {where( self.ctx.host )}"

    def __call__( self, echo = print ) -> int:
        return install( self.ctx.host, self.layer.image_name( self.ctx ), self.layer.declared(),
                        self.layer.booted(), echo )


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



def _spec( declared: dict, root: Path ) -> list:
    # Flat: `fingerprint` reads the CONTENT of a path only at the top level,
    # and a script edited is a script that must be run again.
    return [ RECIPE, _iso_identity( declared[ "iso" ], root ), declared[ "key" ], declared[ "index" ],
             declared[ "disk" ], declared[ "msvc" ], declared[ "python" ],
             *[ _provision_part( p, root ) for p in declared[ "provision" ] ] ]


def where( host ) -> str:
    return "here" if not host.remote else f"on {host.describe()}"


def _sh( script: str, *args ) -> str:
    """A POSIX script as one line for `host.shell`: whatever the login shell
    over there is ( zsh, fish ), the script is read by `sh`."""
    return L.sh( [ "sh", "-c", script, "errand", *[ str( a ) for a in args ] ] )


def ready_line( name: str, keyed: bool ) -> str:
    """A line whose exit code says whether that image is installed -- and, for an
    evaluation, not about to run out -- on the machine that runs it."""
    script = f'r="${{XDG_CACHE_HOME:-$HOME/.cache}}/errand/windows/{name}/ready"; test -f "$r"'
    if not keyed:
        # An evaluation counts down from the day it was installed, and shuts
        # itself down every hour once it has run out -- which would look like a
        # flaky build rather than an expired licence. Rebuilt before that.
        script += f' && test -n "$( find "$r" -mtime -{REBUILD_AFTER} )"'
    return _sh( script )


# ── where things live ────────────────────────────────────────────────────────

def cache_dir( ) -> Path:
    return Path( os.environ.get( "XDG_CACHE_HOME" ) or Path.home() / ".cache" ) / "errand"


def images_dir( ) -> Path:
    """The images, when QEMU runs on this machine. Over there, the same place in THAT cache."""
    return cache_dir() / "windows"


def live_dir( ) -> Path:
    """The state, the locks and the keeper of every machine this one has
    booted, here or elsewhere: on this machine, where the deciding is."""
    return cache_dir() / "vm"


# ── what the machine that runs QEMU is: asked once, read back here ──────────

FACTS = r"""
f() { echo "errand-fact $1=$2"; }
f arch "$( uname -m )"
f system "$( uname -s )"
f user "$( id -un )"
if [ -e /dev/kvm ]; then
    if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then f kvm rw
    else f kvm no; f kvm_group "$( stat -c %G /dev/kvm 2>/dev/null || stat -f %Sg /dev/kvm )"; fi
else f kvm absent; fi
f cache "${XDG_CACHE_HOME:-$HOME/.cache}"
( . /etc/os-release 2>/dev/null && f os "$ID $ID_LIKE" )
for t in qemu-system-x86_64 qemu-img ssh scp ssh-keygen tar rsync zstd curl wget; do
    command -v "$t" >/dev/null 2>&1 && f tool "$t"
done
true
"""


@dataclass
class Facts:
    where    : str                   # "here", "on lmo": for what is said about it
    arch     : str
    system   : str                   # uname -s: Linux, Darwin
    user     : str
    kvm      : str                   # rw, no ( there but not ours ), absent
    kvm_group: str
    cache    : str                   # its ~/.cache, as an absolute path over there
    os_ids   : set                   # ID and ID_LIKE of /etc/os-release: ubuntu, debian
    tools    : set

    @classmethod
    def of( cls, host ) -> "Facts":
        got = host.shell( _sh( FACTS ), capture = True )
        found, tools = { }, set()
        for line in ( got.stdout or "" ).splitlines():
            # Only what was asked: an rc file over there may say things of its own.
            if line.startswith( "errand-fact " ):
                key, _, value = line[ len( "errand-fact " ) : ].partition( "=" )
                if key == "tool":
                    tools.add( value )
                else:
                    found[ key ] = value
        if "arch" not in found:
            raise VmError( f"could not ask {where( host ).replace( 'on ', '' )} what it is: "
                           f"{( got.stderr or '' ).strip()[ -400 : ]}" )
        return cls( where = where( host ), arch = found[ "arch" ].lower(), system = found.get( "system", "" ),
                    user = found.get( "user", "" ), kvm = found.get( "kvm", "absent" ),
                    kvm_group = found.get( "kvm_group", "kvm" ), cache = found.get( "cache", "" ),
                    os_ids = set( found.get( "os", "" ).split() ), tools = tools )


def qemu_hint( facts: Facts ) -> str:
    """The command that installs QEMU on THAT machine: one command, not a menu,
    and said plainly when the system is not one this knows."""
    if facts.system == "Darwin":
        return "brew install qemu"
    ids = facts.os_ids
    if ids & { "debian", "ubuntu" }:
        return "sudo apt install qemu-system-x86 qemu-utils"
    if ids & { "fedora", "rhel", "centos" }:
        return "sudo dnf install qemu-kvm qemu-img"
    if "arch" in ids:
        return "sudo pacman -S qemu-full"
    if ids & { "suse", "opensuse", "sles" }:
        return "sudo zypper install qemu-x86 qemu-tools"
    return "install QEMU ( qemu-system-x86 and qemu-img ) with its package manager"


def package_hint( facts: Facts, names ) -> str:
    """For tools whose package has their name everywhere: rsync, zstd."""
    names = " ".join( names )
    if facts.system == "Darwin":
        return f"brew install {names}"
    ids = facts.os_ids
    for known, how in ( ( { "debian", "ubuntu" }, "sudo apt install" ), ( { "fedora", "rhel", "centos" }, "sudo dnf install" ),
                        ( { "arch" }, "sudo pacman -S" ), ( { "suse", "opensuse", "sles" }, "sudo zypper install" ) ):
        if ids & known:
            return f"{how} {names}"
    return f"install {names} with its package manager"


def need( facts: Facts, tools, hint: str ):
    missing = [ t for t in tools if t not in facts.tools ]
    if missing:
        raise VmError( f"{', '.join( missing )} {'is' if len( missing ) == 1 else 'are'} not installed "
                       f"{facts.where} -- {hint}" )


def accel( facts: Facts ) -> tuple:
    """-> ( accelerator, cpu ). Windows here is x86-64, so the host must be too:
    emulating one on an ARM machine is measured in hours per boot."""
    if facts.arch not in ( "x86_64", "amd64" ):
        raise VmError( f"the machine {facts.where} is {facts.arch}, and the Windows errand installs is "
                       f"x86-64: it would be emulated instruction by instruction. Not supported -- "
                       f"reach an x86-64 machine that can: [ errand.Ssh( host = … ), errand.Windows() ]" )
    if facts.system == "Darwin":
        return "hvf", "host"
    if facts.kvm == "rw":
        # The Hyper-V enlightenments: Windows asks for them, and without them
        # it spins on timers it believes are real hardware.
        return "kvm", "host,hv_relaxed,hv_vapic,hv_spinlocks=0x1fff,hv_time"
    if facts.kvm == "no":
        # There, but not for this user -- the usual case over ssh: a desktop
        # session is granted it on the side, a login from elsewhere is not.
        # Emulating instead would be hours per boot, for want of one command.
        raise VmError( f"/dev/kvm is there {facts.where}, but {facts.user} may not use it -- "
                       f"sudo usermod -aG {facts.kvm_group} {facts.user}, then log in again" )
    return "tcg", "max"


def _escaped( path ) -> str:
    """A path inside a QEMU option string, where a comma separates options."""
    return str( path ).replace( ",", ",," )


def qemu_argv( disk: str, *, accel: tuple, port: int, cpus: int, ram, iso: str | None = None,
               media: str | None = None, data: str | None = None ) -> list:
    """The command line, for the machine that runs it: paths are ITS paths."""
    how, cpu = accel
    argv = [ "qemu-system-x86_64",
             "-machine", "q35", "-accel", how, "-cpu", cpu,
             "-smp", str( cpus ), "-m", f"{int( queue.parse_size( ram ) )}M",
             "-rtc", "base=utc",
             "-monitor", "none", "-serial", "none", "-parallel", "none",
             # Inbox drivers only -- an AHCI disk and an e1000e card are what
             # Windows knows without being given anything, so there is no
             # driver disk to fetch and keep in step.
             "-drive", f"if=none,id=system,file={_escaped( disk )},format=qcow2,discard=unmap",
             "-device", "ide-hd,drive=system,bus=ide.0",
             # The disk that is kept: written to directly, never through an
             # overlay. Port 2, since 1 is the install medium's.
             *( [ "-drive", f"if=none,id=data,file={_escaped( data )},format=qcow2,discard=unmap",
                  "-device", "ide-hd,drive=data,bus=ide.2" ] if data else [ ] ),
             "-nic", f"user,model=e1000e,hostfwd=tcp:127.0.0.1:{port}-:22" ]
    # Somebody debugging an install wants to SEE it: ERRAND_VM_VNC=1 puts the
    # screen on vnc://127.0.0.1:5901, of the machine that runs it.
    vnc = os.environ.get( "ERRAND_VM_VNC" )
    argv += [ "-vnc", f"127.0.0.1:{vnc}" ] if vnc else [ "-display", "none" ]
    if iso is not None:
        # Booted from once: the reboots in the middle of setup must land on the
        # disk it is writing, not start the install over.
        argv += [ "-drive", f"if=none,id=setup,file={_escaped( iso )},media=cdrom,readonly=on",
                  "-device", "ide-cd,drive=setup,bus=ide.1", "-boot", "once=d" ]
    if media is not None:
        # A directory of that machine, seen by the guest as a USB stick. Setup
        # looks for `autounattend.xml` at the root of removable drives -- of
        # its own accord, which is the whole trick of an unattended install.
        # Read-only, and said so: a USB disk over a read-only node is refused
        # unless the drive declares it.
        argv += [ "-drive", f"if=none,id=media,file=fat:{_escaped( media )},format=raw,readonly=on",
                  "-device", "qemu-xhci", "-device", "usb-storage,drive=media,removable=on" ]
    return argv


def msys_path( path: str ) -> str:
    """A Windows path as the rsync in the guest reads it: E:/x is /e/x."""
    path = str( path ).replace( "\\", "/" )
    if re.match( r"^[A-Za-z]:", path ):
        path = f"/{path[ 0 ].lower()}{path[ 2 : ]}"
    return path.rstrip( "/" )


def rsync_line( reach: list, there: str ) -> str:
    """The project, minus what an `Ssh` push leaves out too, into `there` in the
    guest -- run from its root on the machine that runs QEMU. Links followed, as
    NTFS has none worth the name; no permission, owner or group, which the
    guest's ACLs would only garble. Nothing deleted: what a command built beside
    the sources is not on this side, and must stay over there."""
    return L.sh( [ "rsync", "-rtL", "-e", L.sh( reach ), "--rsync-path", GUEST_RSYNC,
                   *[ f"--exclude={e}" for e in EXCLUDES ], "./", f"{USER}@127.0.0.1:{msys_path( there )}/" ] )


# rsync's 23 ( "some files were not transferred" ) and 24 ( "some vanished" ),
# when every complaint is one of these, are a copy as good as can be: a link
# to nothing has nothing to copy, as for an `Ssh` push.
HARMLESS = re.compile( r"symlink has no referent|file has vanished|^rsync (error|warning): some files" )


def rsync_failed( got ) -> bool:
    if not got.returncode:
        return False
    said = [ l for l in ( got.stderr or "" ).splitlines() if l.strip() ]
    return got.returncode not in ( 23, 24 ) or not all( HARMLESS.search( l.strip() ) for l in said )


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


DATA_DRIVE = "E"

# Run in the guest once it answers, every boot: the disk that is kept made
# usable. Windows Server leaves a disk it has not seen offline ( its SAN
# policy ), a new one is blank, and a letter is not promised from one boot to
# the next -- so each is seen to. The system disk is the boot one; the kept
# one is the other.
DATA_SCRIPT = f"""
$ErrorActionPreference = 'Stop'
$d = Get-Disk | Where-Object {{ -not $_.IsBoot -and -not $_.IsSystem }} | Select-Object -First 1
if ( -not $d ) {{ throw 'no data disk' }}
if ( $d.IsOffline )  {{ Set-Disk -Number $d.Number -IsOffline $false }}
if ( $d.IsReadOnly ) {{ Set-Disk -Number $d.Number -IsReadOnly $false }}
if ( ( Get-Disk -Number $d.Number ).PartitionStyle -eq 'RAW' ) {{
    Initialize-Disk -Number $d.Number -PartitionStyle GPT
    New-Partition -DiskNumber $d.Number -UseMaximumSize -DriveLetter {DATA_DRIVE} | Out-Null
    Format-Volume -DriveLetter {DATA_DRIVE} -FileSystem NTFS -NewFileSystemLabel errand-data -Confirm:$false | Out-Null
}} else {{
    $p = Get-Partition -DiskNumber $d.Number | Where-Object Type -eq 'Basic' | Select-Object -First 1
    if ( $p.DriveLetter -ne '{DATA_DRIVE}' ) {{
        Set-Partition -DiskNumber $d.Number -PartitionNumber $p.PartitionNumber -NewDriveLetter {DATA_DRIVE}
    }}
}}
# Scanned on every write otherwise, which halves a compiler's speed -- as for C:\\errand.
try {{ Add-MpPreference -ExclusionPath {DATA_DRIVE}:\\ }} catch {{ }}
Write-Output 'errand-data-ok'
"""


# What Windows has not written yet, written. The machine is thrown away rather
# than shut down, which to the disk that is kept is a power cut: without this
# the files of the last command are there, with their names and sizes, and
# zeros inside.
FLUSH_SCRIPT = f"Write-VolumeCache -DriveLetter {DATA_DRIVE}"


def powershell( script: str ) -> str:
    """`script` as one cmd.exe line: encoded, so that no quote or newline of it
    has to survive cmd.exe."""
    import base64
    return "powershell -NoProfile -NonInteractive -EncodedCommand " + \
           base64.b64encode( script.encode( "utf-16-le" ) ).decode()


GUEST_OPTIONS = [ "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=no",
                  "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
                  "-o", "BatchMode=yes", "-o", "ConnectTimeout=5" ]


class Machine:
    """One installed image, and the machine booted from it.

    Over there -- wherever `host` leads -- are the disks, the guest's key and
    QEMU; they are only ever touched through `host`, a line at a time. Here are
    the state, the locks and the keeper, under `live_dir()`.

    Two locks, always taken in this order:

        start.lock   held while deciding whether a keeper must be started, and
                     by a keeper while it stops -- so nobody decides "it is up"
                     about a machine that is going down
        use.lock     held for as long as a command uses the machine -- which
                     is how commands take turns, and how the keeper knows that
                     nobody is about to
    """

    def __init__( self, host, facts: Facts, name: str ):
        self.host, self.facts, self.name = host, facts, name
        self.image = f"{facts.cache}/errand/windows/{name}"     # over there
        self.spot  = f"{self.image}/live"                        # over there: overlay, tars, log
        self.live  = live_dir() / f"{re.sub( r'[^A-Za-z0-9._-]', '_', host.describe() )}-{name}"
        self._port = None

    # -- the caller's side ----------------------------------------------------

    @property
    def port( self ) -> int:
        return self._port or int( _read( self.live / "port", "0" ) )

    def state( self ) -> str:
        return _read( self.live / "state", "stopped" )

    def keeper_alive( self ) -> bool:
        return _alive( _read( self.live / "keeper.pid" ) ) and self.state() not in ( "stopping", "stopped" )

    @contextlib.contextmanager
    def using( self, booted: dict, echo = print ):
        """`booted`: { cpus, ram, keep }, as `Windows.booted` says it."""
        self.live.mkdir( parents = True, exist_ok = True )
        start = _lock( self.live / "start.lock" )
        try:
            if not self.keeper_alive():
                self._spawn( booted )
            # This process holds the machine until it ends, not only for this
            # command: the next one it sends must not pay for another boot.
            # Never removed -- the keeper forgets a holder once its pid is gone.
            ( self.live / "holders" ).mkdir( exist_ok = True )
            ( self.live / "holders" / str( os.getpid() ) ).touch()
            use = _lock( self.live / "use.lock" )
        finally:
            start.close()
        try:
            ( self.live / "used" ).touch()
            self._wait_ready( echo )
            yield self
        finally:
            ( self.live / "used" ).touch()
            use.close()

    def _spawn( self, booted: dict ):
        # Said here, where somebody reads it, rather than in the keeper's log.
        accel( self.facts )
        need( self.facts, ( "qemu-system-x86_64", "qemu-img" ), qemu_hint( self.facts ) )
        ( self.live / "config.json" ).write_text( json.dumps( {
            "host": self.host.spec(), "name": self.name, "cpus": booted[ "cpus" ], "ram": booted[ "ram" ],
            "keep": _seconds( booted[ "keep" ] ), "data": booted.get( "data" ) } ) )
        ( self.live / "state" ).write_text( "starting" )
        env = { k: v for k, v in os.environ.items() if k != queue.CLAIM }
        # Wherever this errand was imported from is where the keeper imports it
        # from: a checkout on PYTHONPATH must not be swapped for an install.
        package_parent = str( Path( __file__ ).resolve().parent.parent )
        env[ "PYTHONPATH" ] = os.pathsep.join( p for p in ( package_parent, env.get( "PYTHONPATH" ) ) if p )
        with open( self.live / "keeper.log", "w" ) as log:
            child = subprocess.Popen( [ sys.executable, "-m", "errand.vm", "keep", str( self.live ) ],
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
                        "queued"  : "  waiting for the machine to have room for it ( errand queue )",
                        "booting" : f"  booting windows {self.facts.where}" }.get( state, f"  windows: {state}" ) )
                said, since = state, time.time()
            if state == "booting" and time.time() - since > BOOT_TIMEOUT:
                raise VmError( f"windows did not answer within {BOOT_TIMEOUT // 60} minutes" )
            time.sleep( 1.0 )

    # -- doing things over there ----------------------------------------------

    def there( self, script: str, *args, what = "" ):
        """A POSIX script over there, which must work: -> its output."""
        got = self.host.shell( _sh( script, *args ), capture = True )
        if got.returncode:
            raise VmError( f"{what or 'a step'} failed {self.facts.where}: "
                           f"{( got.stderr or got.stdout or '' ).strip()[ -600 : ]}" )
        return got.stdout

    def write( self, path: str, text: str ):
        got = self.host.shell( _sh( 'cat > "$1"', path ), input = text, capture = True )
        if got.returncode:
            raise VmError( f"could not write {path} {self.facts.where}: {got.stderr.strip()[ -300 : ]}" )

    def start( self, disk: str, *, cpus, ram, iso = None, media = None, data = None, log: str ) -> tuple:
        """QEMU started over there and let go of -> ( port, pid ). The port is
        drawn at random and tried: only that machine knows which ones are free."""
        how, pidfile = accel( self.facts ), f"{log}.pid"
        for _ in range( 5 ):
            port = random.randint( 20000, 60000 )
            argv = qemu_argv( disk, accel = how, port = port, cpus = cpus, ram = ram, iso = iso, media = media,
                              data = data )
            # QEMU lets go by itself, and only once the machine is set up: a
            # port taken or a disk locked is its exit code, now, not a death
            # to notice later -- and the pid is the one IT writes, not a guess
            # at which process a shell put in the background.
            got = self.host.shell( _sh( 'p=$1 l=$2; shift 2; rm -f "$p"; "$@" > "$l" 2>&1 < /dev/null; code=$?; '
                                        'cat "$l"; [ $code -eq 0 ] && echo "errand-pid=$( cat "$p" )"; exit $code',
                                        pidfile, log, *argv, "-daemonize", "-pidfile", pidfile ),
                                   capture = True )
            out = ( got.stdout or "" ) + ( got.stderr or "" )
            found = re.search( r"errand-pid=(\d+)", out )
            if got.returncode == 0 and found:
                self._port = port
                return port, int( found.group( 1 ) )
            if "hostfwd" not in out and "host forwarding" not in out:
                raise VmError( f"QEMU did not start {self.facts.where}:\n{out.strip()[ -800 : ]}" )
        raise VmError( f"no free port for ssh into the machine {self.facts.where}, five tries" )

    def alive_there( self, pid ):
        """-> True, False, or None when the question could not be put ( ssh down )."""
        got = self.host.shell( L.sh( [ "kill", "-0", str( pid ) ] ), quiet = True )
        if got.returncode == 0:
            return True
        return None if self.host.remote and got.returncode == 255 else False

    def gone( self, pid ) -> bool:
        """Dead, asked twice a few seconds apart: a machine's disk is renamed, or
        its claim let go, on this answer -- one stray `no` must not do that."""
        if self.alive_there( pid ) is not False:
            return False
        time.sleep( 3.0 )
        return self.alive_there( pid ) is False

    def stop_there( self, pid ):
        """Thrown away rather than shut down: the next boot starts from the image
        again, so there is nothing in this one worth a clean exit."""
        self.host.shell( _sh( 'kill "$1" 2>/dev/null; i=0; '
                              'while kill -0 "$1" 2>/dev/null && [ $i -lt 30 ]; do sleep 1; i=$(( i + 1 )); done; '
                              'kill -9 "$1" 2>/dev/null; true', pid ), quiet = True )

    # -- talking to the guest, from the machine that runs it ------------------

    def _reach( self, tool: str, port_flag: str ) -> list:
        return [ tool, port_flag, str( self.port ), "-i", f"{self.image}/key", *GUEST_OPTIONS ]

    def guest( self, line: str, **kw ):
        """`line`, run by cmd.exe in Windows."""
        return self.host.shell( L.sh( [ *self._reach( "ssh", "-p" ), f"{USER}@127.0.0.1", line ] ), **kw )

    def scp( self, src: str, dst: str ) -> int:
        """Between the machine that runs QEMU and the guest; one side is `Administrator@127.0.0.1:…`."""
        return self.host.shell( L.sh( [ *self._reach( "scp", "-P" ), "-q", src, dst ] ) ).returncode

    def answers( self ) -> bool:
        try:
            got = self.guest( "echo errand-ok", capture = True, timeout = 40 )
        except subprocess.TimeoutExpired:
            return False
        return got.returncode == 0 and "errand-ok" in ( got.stdout or "" )

    def wait_for( self, pid, timeout: float ) -> bool:
        """Until sshd answers, QEMU dies, or `timeout`."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.gone( pid ):
                return False
            if self.answers():
                return True
            time.sleep( 3.0 )
        return False

    def push( self, there: str ):
        """The project as the machine that runs QEMU has it, into the guest:
        what changed since the last time, when `there` is on the kept disk."""
        win = _backslashed( there )
        code = self.guest( f'if not exist "{win}" mkdir "{win}"' ).returncode
        if code:
            raise subprocess.CalledProcessError( code, "copy into windows" )
        got = self.host.shell( rsync_line( self._reach( "ssh", "-p" ), there ), capture = True )
        if rsync_failed( got ):
            raise VmError( f"could not copy the project into windows ( rsync: {got.returncode} ):\n"
                           f"{( got.stderr or '' ).strip()[ -800 : ]}" )

    def fetch( self, paths, there: str ):
        """Into the project as the machine that runs QEMU has it -- from where an
        `Ssh` before it brings them back in turn. Best effort, as over ssh: what
        the command never produced is nothing to bring back."""
        win, archive = _backslashed( there ), f"{self.spot}/out.tar"
        for p in paths:
            p = str( p ).strip( "/" )
            # The old archive deleted first, and a missing path an error: never
            # bring back what an earlier command left.
            made = self.guest( f'del "{win}.out.tar" 2>nul & cd /d "{win}" && '
                               f'if exist "{_backslashed( p )}" ( tar -c -f "{there}.out.tar" "{p}" ) else exit 1',
                               quiet = True )
            if made.returncode or self.scp( f"{USER}@127.0.0.1:{there}.out.tar", archive ):
                continue
            self.host.shell( L.sh( [ "tar", "-x", "-f", archive ] ) + " && " + L.sh( [ "rm", "-f", archive ] ) )

    # -- the keeper's side ----------------------------------------------------

    def keep( self, config: dict ) -> int:
        """Hold a claim, boot, wait for idleness, stop. Run as its own process,
        here; QEMU runs wherever `host` leads."""
        ( self.live / "keeper.pid" ).write_text( str( os.getpid() ) )
        # A SIGTERM ( `errand vm stop` ) must unwind through the `finally` below, or
        # QEMU outlives its keeper and nobody counts what it holds.
        signal.signal( signal.SIGTERM, lambda *_: sys.exit( 0 ) )
        self._kill_leftover()
        overlay, pid, data = f"{self.spot}/overlay.qcow2", None, None
        try:
            ( self.live / "state" ).write_text( "queued" )
            # The queue is this machine's: cores over there are counted only
            # when over there is here.
            with queue.claim( { "cpus": config[ "cpus" ], "ram": config[ "ram" ] },
                              label = f"windows vm {self.name[ : 8 ]}", enabled = not self.host.remote ):
                self.there( 'mkdir -p "$1" && rm -f "$3" && qemu-img create -q -f qcow2 -b "$2" -F qcow2 "$3"',
                            self.spot, f"{self.image}/base.qcow2", overlay, what = "the overlay" )
                data = self.data_disk( config.get( "data" ) )
                ( self.live / "state" ).write_text( "booting" )
                port, pid = self.start( overlay, cpus = config[ "cpus" ], ram = config[ "ram" ], data = data,
                                        log = f"{self.spot}/qemu.log" )
                ( self.live / "port" ).write_text( str( port ) )
                ( self.live / "qemu.pid" ).write_text( str( pid ) )
                if not self.wait_for( pid, BOOT_TIMEOUT ):
                    ( self.live / "state" ).write_text( "failed" )
                    return 1
                if data:
                    got = self.guest( powershell( DATA_SCRIPT ), capture = True )
                    if "errand-data-ok" not in ( got.stdout or "" ):
                        print( f"the disk that is kept could not be made {DATA_DRIVE}:\n"
                               f"{( got.stdout or '' )[ -800 : ]}{( got.stderr or '' )[ -800 : ]}", flush = True )
                        ( self.live / "state" ).write_text( "failed" )
                        return 1
                ( self.live / "state" ).write_text( "ready" )
                held, ticks = None, 0     # the locks, kept until this process is gone
                while held is None:
                    time.sleep( 2.0 )
                    ticks += 1
                    # Asked rarely: over ssh every question is a connection.
                    if ticks % 15 == 0 and self.gone( pid ):
                        break
                    held = self._idle( config[ "keep" ] )
        finally:
            ( self.live / "state" ).write_text( "stopping" )
            if pid is not None:
                if data:
                    # Every command flushed already; this is for whatever ran
                    # since, or was cut short.
                    with contextlib.suppress( subprocess.TimeoutExpired ):
                        self.guest( powershell( FLUSH_SCRIPT ), quiet = True, timeout = 60 )
                self.stop_there( pid )
            self.host.shell( L.sh( [ "rm", "-f", overlay ] ), quiet = True )
            ( self.live / "qemu.pid" ).unlink( missing_ok = True )
            ( self.live / "keeper.pid" ).unlink( missing_ok = True )
            ( self.live / "state" ).write_text( "stopped" )
        return 0

    def data_disk( self, size ) -> str | None:
        """The disk that is kept, made the first time -> its path over there.
        One per image: every project booted from it has its folder on it, and
        it outlives restarts and reinstalls of the same declaration alike."""
        if not size:
            return None
        path = f"{self.image}/data.qcow2"
        self.there( 'test -f "$1" || qemu-img create -q -f qcow2 "$1" "$2"', path, size, what = "the data disk" )
        return path

    def _idle( self, keep: float ):
        """Long enough since the last command, no errand process still holding
        the machine, and nobody about to send one? -> the locks, to be held until
        this process exits; or None."""
        try:
            since = time.time() - ( self.live / "used" ).stat().st_mtime
        except OSError:
            since = keep + 1
        if since <= keep or self.holders():
            return None
        start = _lock( self.live / "start.lock", block = False )
        if start is None:
            return None
        use = _lock( self.live / "use.lock", block = False )
        if use is None or self.holders():
            # Asked again under the locks: a process registers itself under
            # start.lock, so one that came in meanwhile is seen now.
            for lock in ( start, use ):
                if lock is not None:
                    lock.close()
            return None
        ( self.live / "state" ).write_text( "stopping" )
        return ( start, use )

    def holders( self ) -> list:
        """The errand processes that used the machine and are still alive: it
        is theirs until they end. Those that ended are forgotten here."""
        alive = [ ]
        for f in ( self.live / "holders" ).glob( "*" ):
            if _alive( f.name ):
                alive.append( f.name )
            else:
                f.unlink( missing_ok = True )
        return alive

    def _kill_leftover( self ):
        """A keeper killed outright leaves its QEMU running, holding a port and
        memory nobody counts any more. The next keeper finishes the job."""
        pid = _read( self.live / "qemu.pid" )
        if pid:
            self.stop_there( pid )
        ( self.live / "qemu.pid" ).unlink( missing_ok = True )

    # -- installing -----------------------------------------------------------

    def obtain_iso( self, iso: str, echo = print ) -> str:
        """-> the ISO as the machine that runs QEMU names it: a path of the
        project over there, or a download into its cache, made by it."""
        if "://" not in iso:
            out = self.host.shell( _sh( 'cd "$( dirname "$1" )" 2>/dev/null && test -f "$( basename "$1" )" '
                                        '&& echo "errand-path=$( pwd )/$( basename "$1" )"', iso ),
                                   capture = True ).stdout or ""
            found = re.search( r"errand-path=(.*)", out )
            if not found:
                raise VmError( f"no ISO at {iso} {self.facts.where}" )
            return found.group( 1 ).strip()
        target = f"{self.facts.cache}/errand/iso/{L.fingerprint( iso )}.iso"
        if self.host.shell( L.sh( [ "test", "-f", target ] ), quiet = True ).returncode == 0:
            return target
        if "curl" in self.facts.tools:
            fetch = 'curl -fL --retry 3 --progress-bar -o "$2.part" "$1"'
        elif "wget" in self.facts.tools:
            fetch = 'wget -q --show-progress -O "$2.part" "$1"'
        else:
            raise VmError( f"neither curl nor wget {self.facts.where} to download the ISO with" )
        echo( f"  downloading {iso} {self.facts.where}" )
        got = self.host.shell( _sh( f'mkdir -p "$( dirname "$2" )" && {fetch} && mv "$2.part" "$2"', iso, target ) )
        if got.returncode:
            raise VmError( f"could not download the ISO {self.facts.where} -- download it by hand and "
                           f"declare it: errand.Windows( iso = 'path/to/windows.iso' )" )
        return target

    def obtain_rsync( self, into: str, work: str, echo = print ):
        """The rsync of the guest, unpacked from MSYS2's packages into `into`,
        on the install media -- by the machine that runs QEMU, which has a
        zstd to open them with, where Windows may not."""
        if "curl" in self.facts.tools:
            fetch = 'curl -fsSL --retry 3 -o "$p.tar.zst" "$repo/$p-x86_64.pkg.tar.zst"'
        elif "wget" in self.facts.tools:
            fetch = 'wget -q -O "$p.tar.zst" "$repo/$p-x86_64.pkg.tar.zst"'
        else:
            raise VmError( f"neither curl nor wget {self.facts.where} to download rsync for windows with" )
        echo( f"  downloading rsync for windows from msys2 {self.facts.where}" )
        script = ( 'repo="$1" into="$2" work="$3"; shift 3; set -e; mkdir -p "$into" "$work"; cd "$work"; '
                   f'for p in {" ".join( MSYS2_PACKAGES )}; do {fetch}; '
                   'zstd -dqc "$p.tar.zst" | tar -x -f - usr/bin; done; '
                   'for f in "$@"; do cp "usr/bin/$f" "$into/"; done; cd / && rm -rf "$work"' )
        self.there( script, MSYS2_REPO, into, work, *RSYNC_FILES, what = "unpacking rsync for windows" )


def running( ) -> list:
    """-> [ live directory ] whose keeper is alive."""
    if not live_dir().is_dir():
        return [ ]
    return [ d for d in sorted( live_dir().iterdir() )
             if d.is_dir() and _alive( _read( d / "keeper.pid" ) ) ]


def stop_all( echo = print ) -> int:
    """`errand vm stop`: every warm machine, now -- here or elsewhere, since
    every keeper is here."""
    machines = running()
    for live in machines:
        echo( f"  stopping windows vm {live.name}" )
        with contextlib.suppress( OSError, ValueError ):
            os.kill( int( _read( live / "keeper.pid" ) ), signal.SIGTERM )
    if not machines:
        echo( "  no virtual machine is running" )
    return 0


def install( host, name: str, declared: dict, booted: dict, echo = print ) -> int:
    """`errand setup` for a `Windows` layer: install from the ISO, check it answers,
    and only then call it ready -- decided here, done through `host`."""
    try:
        facts = Facts.of( host )
        need( facts, ( "ssh", "scp", "ssh-keygen", "tar" ), "they come with OpenSSH and tar" )
        need( facts, ( "qemu-system-x86_64", "qemu-img" ), qemu_hint( facts ) )
        need( facts, ( "rsync", "zstd" ), package_hint( facts, [ "rsync", "zstd" ] ) )
        how, _ = accel( facts )
        if how == "tcg":
            echo( f"  no hardware virtualization {facts.where} ( /dev/kvm ): this will take HOURS" )
        m = Machine( host, facts, name )
        iso = m.obtain_iso( declared[ "iso" ] or EVALUATION_ISO, echo )

        work = f"{m.image}/build"
        media, disk = f"{work}/media", f"{work}/disk.qcow2"
        m.there( 'rm -rf "$2" && mkdir -p "$3" && '
                 '( test -f "$1/key" || ssh-keygen -q -t ed25519 -N "" -C errand-vm -f "$1/key" ) && '
                 'cp "$1/key.pub" "$3/errand_key.pub"', m.image, work, media, what = "preparing the install" )
        m.write( f"{media}/autounattend.xml", autounattend( key = declared[ "key" ], index = declared[ "index" ] ) )
        m.obtain_rsync( f"{media}/rsync", f"{work}/msys2", echo )
        provision = [ ]
        for i, p in enumerate( declared[ "provision" ] ):
            if str( p ).endswith( ".ps1" ):
                # From the project as that machine has it: `errand setup` pushed it there first.
                m.there( 'cp "$1" "$2"', p, f"{media}/errand-provision-{i}.ps1", what = f"copying {p}" )
                provision.append( p )
            else:
                provision.append( { "line": p } )
        m.write( f"{media}/errand-setup.ps1",
                 setup_script( msvc = declared[ "msvc" ], python = declared[ "python" ], provision = provision ) )
        m.there( 'qemu-img create -q -f qcow2 "$1" "$2"', disk, declared[ "disk" ], what = "the disk" )
    except VmError as err:
        echo( f"  {err}" )
        return 1

    with queue.claim( { "cpus": booted[ "cpus" ], "ram": booted[ "ram" ] },
                      label = "installing windows", echo = echo, enabled = not host.remote ):
        echo( f"  installing windows {facts.where} -- 20 to 60 minutes, with nothing to watch "
              f"( ERRAND_VM_VNC=1 to watch on vnc://127.0.0.1:5901 {facts.where} )" )
        started, pid = time.time(), None
        try:
            _, pid = m.start( disk, cpus = booted[ "cpus" ], ram = booted[ "ram" ], iso = iso, media = media,
                              log = f"{work}/qemu.log" )
            report = started + 600
            # Setup powers the machine off when it is done: that is the signal.
            while not m.gone( pid ):
                time.sleep( 10.0 )
                if time.time() > report:
                    echo( f"    still installing, {( time.time() - started ) / 60:.0f} min" )
                    report += 600
                if time.time() - started > INSTALL_TIMEOUT:
                    echo( f"  the install did not finish in {INSTALL_TIMEOUT // 3600} hours" )
                    return 1
            pid = None
            m.there( 'mv "$1" "$2"', disk, f"{m.image}/base.qcow2", what = "keeping the disk" )
            echo( f"  installed in {( time.time() - started ) / 60:.0f} min; checking that it answers" )
            if not _check( m, booted, work, echo ):
                return 1
        except VmError as err:
            echo( f"  {err}" )
            return 1
        finally:
            if pid is not None:
                m.stop_there( pid )

    m.there( 'date > "$1/ready" && rm -rf "$2"', m.image, work, what = "marking it ready" )
    echo( f"  windows is ready {facts.where}: {m.image}" )
    return 0


def _check( m: Machine, booted: dict, work: str, echo ) -> bool:
    """Boot it once, the way every run will, and read back how setup went."""
    overlay = f"{work}/check.qcow2"
    m.there( 'qemu-img create -q -f qcow2 -b "$1" -F qcow2 "$2"', f"{m.image}/base.qcow2", overlay,
             what = "the overlay" )
    _, pid = m.start( overlay, cpus = booted[ "cpus" ], ram = booted[ "ram" ], log = f"{work}/check.log" )
    try:
        if not m.wait_for( pid, BOOT_TIMEOUT ):
            echo( "  installed, but sshd never answered: the first logon script did not run, "
                  "or failed before sshd -- ERRAND_VM_VNC=1 and errand setup --force to watch it" )
            return False
        status = ( m.guest( r"type C:\errand\setup.status", capture = True ).stdout or "" ).strip()
        if status != "ok":
            log = m.guest( r"type C:\errand-setup.log", capture = True ).stdout or ""
            echo( f"  the setup inside windows went wrong: {status or 'no status'}\n{log[ -1500 : ]}" )
            return False
        return True
    finally:
        m.stop_there( pid )


# ── what the guest is given ──────────────────────────────────────────────────

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
    # A label is a PowerShell string: a quote of the line it names would end it,
    # and the whole script with it. Doubled, it is a quote.
    label = lambda text: "'" + str( text ).replace( "'", "''" ) + "'"
    for i, p in enumerate( provision ):
        if isinstance( p, dict ):
            steps.append( f"\n    Step {label( 'provision: ' + p[ 'line' ][ : 40 ] )}\n    {p[ 'line' ]}" )
        else:
            steps.append( f"\n    Step {label( Path( p ).name )}\n    & ( Join-Path $media 'errand-provision-{i}.ps1' )" )
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

    # What copies the project in. Its POSIX permissions would be mapped onto
    # ACLs, and the files it writes come out unreadable to anybody else: off,
    # so that they inherit the ACLs of where they land, as any other file.
    Step 'rsync'
    $bin = '{GUEST_MSYS}\\usr\\bin'
    New-Item -ItemType Directory -Force $bin, '{GUEST_MSYS}\\etc' | Out-Null
    Copy-Item ( Join-Path $media 'rsync\\*' ) $bin
    Set-Content '{GUEST_MSYS}\\etc\\fstab' 'none / cygdrive binary,posix=0,noacl,user 0 0' -Encoding ascii
    & ( Join-Path $bin 'rsync.exe' ) --version | Out-Null
    if ( $LASTEXITCODE ) {{ throw "rsync: exit $LASTEXITCODE" }}
{''.join( steps )}
    Set-Content C:\\errand\\setup.status 'ok'
}} catch {{
    Set-Content C:\\errand\\setup.status "failed: $_"
}} finally {{
    Stop-Transcript
    Stop-Computer -Force
}}
"""




# ── `python -m errand.vm …`: the keeper, a process of its own, here ─────────

def main( argv = None ) -> int:
    argv = list( sys.argv[ 1 : ] if argv is None else argv )
    if argv[ : 1 ] == [ "keep" ] and len( argv ) == 2:
        live = Path( argv[ 1 ] )
        config = json.loads( ( live / "config.json" ).read_text() )
        host = L.host_of( config[ "host" ] )
        return Machine( host, Facts.of( host ), config[ "name" ] ).keep( config )
    if argv[ : 1 ] == [ "stop" ]:
        return stop_all()
    print( "usage: python -m errand.vm keep LIVE_DIR | stop", file = sys.stderr )
    return 2


if __name__ == "__main__":
    sys.exit( main() )
