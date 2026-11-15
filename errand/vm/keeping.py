"""The keeper's side of a machine: boot once there is room, stay up while somebody uses it, stop.

The keeper runs on the machine that runs QEMU ( ADR 0008 ), as a process of that machine's agent,
started by a command's hold ( `using` ). QEMU is its child, in its process group, so whatever ends
the keeper -- a SIGTERM, the agent stopping it, a kill of the whole group -- ends QEMU with it;
on Linux a SIGKILL of the keeper alone does too ( PDEATHSIG ). Nothing it does goes through a
connection that may be lost: its host is this machine.

It stays up while a command holds `use.lock`, or a session runs in the guest ( the guest's agents
say so in their `running` files ), then for `keep`.
"""
from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time

from .. import layers as L
from .claim import held as claim_on
from .common import _alive, _lock, _read, BOOT_TIMEOUT
from .datadisk import DATA_DRIVE, DATA_SCRIPT, FLUSH_SCRIPT, powershell

GUEST_ASKED = 30.0     # seconds between two questions to the guest: is a session running there?
GUEST_BUSY  = 60.0     # a guest agent that said `running` this recently runs a session


class Keeping:
    """The keeper's side: boot once there is room, stay up while somebody uses it, stop."""

    def keep( self, config: dict ) -> int:
        """Hold a claim, boot, wait for idleness, stop. Run as its own process, on the machine
        that runs QEMU."""
        _log_to( self.live / "keeper.log" )
        ( self.live / "keeper.pid" ).write_text( str( os.getpid() ) )
        # A SIGTERM ( `errand vm stop`, the agent stopping it ) must unwind through the `finally`
        # below: the guest's disk is flushed, then QEMU goes.
        signal.signal( signal.SIGTERM, lambda *_: sys.exit( 0 ) )
        self._kill_leftover()
        overlay, pid, data = f"{self.spot}/overlay.qcow2", None, None
        try:
            ( self.live / "state" ).write_text( "queued" )
            with claim_on( self.host, { "cpus": config[ "cpus" ], "ram": config[ "ram" ] },
                           f"windows vm {self.name[ : 8 ]}" ) as claim:
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
                    print( f"windows did not answer within {BOOT_TIMEOUT // 60} minutes, or QEMU stopped:\n"
                           f"{_read_there( self, f'{self.spot}/qemu.log' )}", flush = True )
                    return 1
                if data:
                    got = self.guest( powershell( DATA_SCRIPT ), capture = True )
                    if "errand-data-ok" not in ( got.stdout or "" ):
                        print( f"the disk that is kept could not be made {DATA_DRIVE}:\n"
                               f"{( got.stdout or '' )[ -800 : ]}{( got.stderr or '' )[ -800 : ]}", flush = True )
                        ( self.live / "state" ).write_text( "failed" )
                        return 1
                ( self.live / "state" ).write_text( "ready" )
                held = None           # the locks, kept until this process is gone
                while held is None:
                    time.sleep( 2.0 )
                    if self.gone( pid ):
                        print( "QEMU stopped by itself", flush = True )
                        break
                    held = self._idle( config[ "keep" ], claim )
        finally:
            self._wind_up( pid, data, overlay )
        return 0

    def _wind_up( self, pid, data, overlay ):
        """Each step tried on its own: one that fails must not leave QEMU running. QEMU's pid is
        forgotten only once it is known dead, so that the next keeper finishes the job."""
        ( self.live / "state" ).write_text( "stopping" )
        signal.signal( signal.SIGTERM, signal.SIG_IGN )      # a second SIGTERM must not cut this short
        stopped = pid is None
        if pid is not None:
            if data and not self.gone( pid ):
                # Every command flushed already; this is for whatever ran since, or was cut short.
                with contextlib.suppress( Exception ):
                    self.guest( powershell( FLUSH_SCRIPT ), quiet = True, timeout = 60 )
            for _ in range( 3 ):
                with contextlib.suppress( Exception ):
                    self.stop_there( pid )
                    stopped = self.alive_there( pid ) is False
                if stopped:
                    break
                time.sleep( 5.0 )
        with contextlib.suppress( Exception ):
            self.host.shell( L.sh( [ "rm", "-f", overlay ] ), quiet = True )
        if stopped:
            ( self.live / "qemu.pid" ).unlink( missing_ok = True )
        else:
            print( f"QEMU ( pid {pid} ) could not be stopped: the next keeper will", flush = True )
        ( self.live / "keeper.pid" ).unlink( missing_ok = True )
        ( self.live / "state" ).write_text( "stopped" if stopped else "orphaned" )

    def data_disk( self, size ) -> str | None:
        """The disk that is kept, made the first time -> its path. One per image, in the project:
        it outlives restarts and reinstalls of the same declaration alike."""
        if not size:
            return None
        path = f"{self.image}/data.qcow2"
        self.there( 'test -f "$1" || qemu-img create -q -f qcow2 "$1" "$2"', path, size, what = "the data disk" )
        return path

    def _idle( self, keep: float, claim = None ):
        """Long enough since the last command, no command holding the machine, no session running
        in the guest, and nobody about to send one? -> the locks, to be held until this process
        exits; or None.

        While nobody uses it, the machine is only kept warm: its claim says so, and somebody who
        needs its cores asks for them -- then it goes now, whatever `keep` says."""
        used = self._in_use()
        if claim is not None:
            if used == getattr( self, "_warm", True ):
                self._warm = not used
                claim.preemptible( not used )
            if not used and claim.evicted():
                keep = -1
        try:
            since = time.time() - ( self.live / "used" ).stat().st_mtime
        except OSError:
            since = keep + 1
        if since <= keep or used:
            return None
        start = _lock( self.live / "start.lock", block = False )
        if start is None:
            return None
        use = _lock( self.live / "use.lock", block = False )
        if use is None:
            start.close()
            return None
        ( self.live / "state" ).write_text( "stopping" )
        return ( start, use )

    def _in_use( self ) -> bool:
        """A command holds the machine ( `use.lock` ), or a session runs in the guest."""
        lock = _lock( self.live / "use.lock", block = False )
        if lock is None:
            # Said here rather than by the command's hold, which may be killed outright: `keep`
            # counts from the end of the last command, however it ended.
            ( self.live / "used" ).touch()
            return True
        lock.close()
        busy = self._guest_busy()
        if busy:
            ( self.live / "used" ).touch()          # its `keep` counts from the session's end
        return busy

    def _guest_busy( self ) -> bool:
        """Asked of the guest at most every GUEST_ASKED seconds: an agent there that said `running`
        lately runs a session -- a command whose client went ( a laptop closed ) included."""
        now = time.monotonic()
        if now - getattr( self, "_busy_asked", -1e9 ) < GUEST_ASKED:
            return getattr( self, "_busy_said", False )
        self._busy_asked = now
        script = ( "$t = (Get-Date).AddSeconds(-%d); "
                   "if (Get-ChildItem -Path 'C:\\errand\\agents\\*\\running' -ErrorAction SilentlyContinue | "
                   "Where-Object { $_.LastWriteTime -gt $t }) { 'errand-busy' } else { 'errand-idle' }" ) % GUEST_BUSY
        try:
            got = self.guest( powershell( script ), capture = True, timeout = 30 )
            self._busy_said = "errand-busy" in ( got.stdout or "" )
        except Exception:
            self._busy_said = False
        return self._busy_said

    def _kill_leftover( self ):
        """A keeper killed outright on a system without PDEATHSIG leaves its QEMU running. The next
        keeper finishes the job, if that pid is still a QEMU."""
        pid = _read( self.live / "qemu.pid" )
        if pid and "qemu" in _command_of( pid ):
            self.stop_there( pid )
        ( self.live / "qemu.pid" ).unlink( missing_ok = True )


def _log_to( path ):
    """This process's output, into its log: whoever started it may be gone."""
    fd = os.open( str( path ), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644 )
    for to in ( 1, 2 ):
        os.dup2( fd, to )
    os.close( fd )
    sys.stdout = os.fdopen( 1, "w", buffering = 1 )
    sys.stderr = os.fdopen( 2, "w", buffering = 1 )


def _command_of( pid ) -> str:
    got = subprocess.run( [ "ps", "-o", "command=", "-p", str( pid ) ], capture_output = True, text = True )
    return got.stdout


def _read_there( m, path ) -> str:
    got = m.host.shell( L.sh( [ "tail", "-c", "800", path ] ), capture = True, quiet = True )
    return got.stdout or ""
