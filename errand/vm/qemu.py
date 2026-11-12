"""The QEMU command line.
"""
from __future__ import annotations

import os

from .. import queue


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
