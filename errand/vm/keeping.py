"""The keeper's side of a machine: boot once there is room, stay up while somebody holds it, stop.
"""
from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time

from .. import layers as L, queue
from .common import _alive, _lock, _read, BOOT_TIMEOUT
from .datadisk import DATA_DRIVE, DATA_SCRIPT, FLUSH_SCRIPT, powershell


class Keeping:
    """The keeper's side: boot once there is room, stay up while somebody holds it, stop."""

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
