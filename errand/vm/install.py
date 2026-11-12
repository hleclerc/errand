"""Installing an image: boot the ISO unattended, provision, check, keep the disk.
"""
from __future__ import annotations

import time

from .. import queue
from .guest import autounattend, EVALUATION_ISO, setup_script
from .common import BOOT_TIMEOUT, INSTALL_TIMEOUT, VmError
from .facts import accel, Facts, need, package_hint, qemu_hint
from .machine import Machine


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
