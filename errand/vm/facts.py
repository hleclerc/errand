"""What the machine that runs QEMU is -- asked once, read back here -- and what is missing on it.
"""
from __future__ import annotations

from dataclasses import dataclass

from .common import _sh, VmError, where


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
f root "$( pwd )"
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
    root     : str = ""              # the project's copy over there, where the images are

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
                    kvm_group = found.get( "kvm_group", "kvm" ), cache = found.get( "cache", "" ), root = found.get( "root", "" ),
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
