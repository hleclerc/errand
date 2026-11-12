"""A command's side of a machine: is it up, start a keeper if not, hold it while the command runs.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .. import queue
from .common import _alive, _lock, _read, _seconds, BOOT_TIMEOUT, VmError
from .facts import accel, need, qemu_hint


class Caller:
    """A command's side of the machine: is it up, and holding it while a command uses it."""

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
        package_parent = str( Path( __file__ ).resolve().parent.parent.parent )
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
