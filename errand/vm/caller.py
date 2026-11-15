"""A command's side of a machine: held while the command uses it, wherever QEMU runs ( ADR 0008 ).

Nothing is decided or kept here any more. The command asks the agent of the machine that runs QEMU
-- the one its `Ssh` leads to, or one of this machine's -- for a hold ( `using.use` ): a process
over there that starts a keeper if there is none, as a process of that agent, waits for the machine,
says its port, and holds it until this command lets go. That hold may not outlive this command, so
a command killed or cut off lets go of the machine at once.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

from .common import _read, _seconds, VmError
from .facts import accel, need, qemu_hint


class Caller:
    """A command's side of the machine: holding it while a command uses it."""

    @property
    def port( self ) -> int:
        return self._port or int( _read( self.live / "port", "0" ) )

    def state( self ) -> str:
        return _read( self.live / "state", "stopped" )

    @contextlib.contextmanager
    def using( self, booted: dict, echo = print ):
        """`booted`: { cpus, ram, keep, data }, as `Windows.booted` says it."""
        # Said here, where somebody reads it, rather than in the keeper's log.
        accel( self.facts )
        need( self.facts, ( "qemu-system-x86_64", "qemu-img" ), qemu_hint( self.facts ) )
        from ..agents import frames as F
        conn, launcher, env = self._agent_there()
        request = { "name": self.key, "launcher": launcher,
                    "config": { "host": { "here": self.facts.root }, "name": self.name, "image": self.image,
                                "cpus": booted[ "cpus" ], "ram": booted[ "ram" ],
                                "keep": _seconds( booted[ "keep" ] ), "data": booted.get( "data" ) } }
        call = conn.open( { "op": "spawn", "keep": False, "cwd": self.facts.root, "env": env,
                            "argv": [ *launcher, "-m", "errand.vm", "use", json.dumps( request ) ] } )
        call.reply( 60 )
        try:
            self._port = self._wait_ready( call, echo )
            yield self
        finally:
            with contextlib.suppress( OSError, Exception ):
                call.send( F.EOF )             # let go: the hold over there releases the machine
                call.close()

    def _agent_there( self ):
        """-> ( a connection to the agent of the machine that runs QEMU, how errand is started
        there, the environment it needs )."""
        from .. import agents, bootstrap
        from ..agents import upstream as U
        if self.host.remote:
            conn = agents.open( U.ssh_target( self.host.ssh ) )
            said = conn.ping()
            boot = f"{said.get( 'cache' ) or said[ 'home' ] + '/' + bootstrap.BASE}/{bootstrap.boot_rel()}"
            return conn, [ said[ "python" ], boot ], { }
        from .places import cache_dir
        conn = agents.open( { "kind": "local", "dir": str( cache_dir() / "vm-agent" ), "keep_alive": U.KEEP_ALIVE } )
        # Wherever this errand was imported from is where the hold and the keeper import it from:
        # a checkout on PYTHONPATH must not be swapped for an install.
        package_parent = str( Path( __file__ ).resolve().parent.parent.parent )
        path = os.pathsep.join( p for p in ( package_parent, os.environ.get( "PYTHONPATH" ) ) if p )
        return conn, [ sys.executable ], { "PYTHONPATH": path }

    def _wait_ready( self, call, echo ) -> int:
        from ..agents import frames as F
        buf, said = b"", None
        while True:
            kind, payload = call.next()
            if kind == F.ERR:
                sys.stderr.write( payload.decode( errors = "replace" ) )
                continue
            if kind == F.EXIT:
                raise VmError( "the windows machine could not be held: its hold over there ended "
                               f"( {F.load( payload ).get( 'code' )} )" )
            if kind != F.OUT:
                continue
            buf += payload
            while b"\n" in buf:
                line, buf = buf.split( b"\n", 1 )
                line = line.decode( errors = "replace" ).strip()
                if not line.startswith( "errand-vm " ):
                    continue
                m = json.loads( line[ len( "errand-vm " ) : ] )
                if "ready" in m:
                    return int( m[ "ready" ] )
                if "failed" in m:
                    raise VmError( f"the windows machine did not come up:\n{m[ 'failed' ]}" )
                state = m.get( "state" )
                if state and state != said:
                    echo( { "starting": "  starting the windows machine",
                            "waiting" : "  another command uses the windows machine: waiting for it",
                            "queued"  : "  waiting for the machine to have room for it ( errand queue )",
                            "booting" : f"  booting windows {self.facts.where}" }.get( state, f"  windows: {state}" ) )
                    said = state
