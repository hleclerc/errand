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
over there; all it needs there is QEMU, ssh and tar. The disks and the guest's
key live in THAT machine's cache, and so do the locks, the state and the keeper
( ADR 0008 ): what keeps QEMU runs beside it, owned by errand's agent there.

**Three moments, three costs.**

    install   once per declaration, 20 to 60 minutes. What comes out is a
              disk image, kept in the project's errand-outputs/builds/windows/<fingerprint>/
              on the machine that runs QEMU; the one it replaces goes once it
              is ready. It is a build like any other layer's:
              `errand setup` does it, a changed declaration redoes it, `--dry-run`
              says so.
    boot      once per warm period, half a minute to a few. Every boot starts
              from a fresh copy-on-write layer over that image, so nothing a
              run left behind survives a restart.
    run       once per command: the project goes in ( a sync, through the guest's agent: what
              changed ), the command runs, what `fetch` names comes back.

**Up for as long as somebody needs it, and counted while it is.** A booted
machine stays up while an errand process that used it is alive -- so a run of
several commands boots once -- and then `keep` more ( none by default: a boot
is half a minute, and an idle machine holds what it holds for nothing ). All
that time it holds its cores and its memory, so when it runs on this machine
it holds them IN THE QUEUE, under a claim like any other work, and shows up in
`errand queue`. A small keeper process owns the machine ( and the claim ), on the machine
that runs QEMU, as a process of errand's agent there: it starts QEMU as its
child once there is room, stops it once nobody uses it, and is what `errand vm
stop` stops. A command holds the machine through that agent ( `using` ), for
as long as it runs. Commands on one machine take turns.

Nothing here is Windows-specific but the recipe; another guest would be another
recipe over the same `Machine`.

The package's surface for the rest of errand. One file per concern: the layer ( `windows` ),
where things live ( `places` ), what the QEMU host is ( `facts` ), the QEMU command line ( `qemu` ),
copying in and out ( `transfer` ), the booted machine ( `machine` ), installing an image
( `install` ), what the guest is given ( `guest` ) and the keeper process ( `__main__` ).
"""
from __future__ import annotations

from .windows import Windows
from .box import WindowsBox
from .common import _seconds, VmError
from .places import images_dir
from .facts import accel, Facts, need, package_hint, qemu_hint
from .qemu import qemu_argv
from .transfer import MSYS2_PACKAGES, msys_path, RSYNC_FILES
from .datadisk import DATA_SCRIPT, powershell
from .machine import Machine, running, stop_all
from .install import install
from .guest import autounattend, setup_script


__all__ = [
    'VmError',
    'Windows',
    'WindowsBox',
    '_seconds',
    'images_dir',
    'Facts',
    'qemu_hint',
    'package_hint',
    'need',
    'accel',
    'qemu_argv',
    'MSYS2_PACKAGES',
    'RSYNC_FILES',
    'msys_path',
    'DATA_SCRIPT',
    'powershell',
    'Machine',
    'running',
    'stop_all',
    'install',
    'autounattend',
    'setup_script',
]
