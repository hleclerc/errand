"""The claim a kept machine holds, on the machine that runs QEMU -- here, or the one `Ssh` leads to.

Its cores and its memory are that machine's, so that is the queue they are
counted in: here, a claim of this process; over there, `python -m errand.queue
hold`, started by that machine's agent, which holds the claim for as long as
its stream is open. Either way the keeper can say the machine is only kept
warm ( `preemptible` ), and hear that somebody needs the room ( `evicted` ).
"""
from __future__ import annotations

import contextlib
import json
import queue as Q
import sys
import threading

from .. import queue


class _Remote:
    def __init__( self, call ):
        self.call, self.devices = call, [ ]
        self._evicted, self._lines = False, Q.Queue()
        threading.Thread( target = self._read, daemon = True ).start()

    def _read( self ):
        from ..agents import frames as F
        buf = b""
        try:
            while True:
                kind, payload = self.call.next()
                if kind == F.ERR:
                    sys.stderr.write( payload.decode( errors = "replace" ) )
                elif kind == F.OUT:
                    buf += payload
                    while b"\n" in buf:
                        line, buf = buf.split( b"\n", 1 )
                        line = line.decode( errors = "replace" ).strip()
                        if line == "evict":
                            self._evicted = True
                        self._lines.put( line )
                elif kind == F.EXIT:
                    break
        except Exception:
            pass
        self._lines.put( None )

    def granted( self ) -> bool:
        while True:
            line = self._lines.get()
            if line is None:
                return False
            if line.startswith( "granted" ):
                self.devices = [ int( d ) for d in line.split( " ", 1 )[ -1 ].split( "," ) if d.strip().isdigit() ]
                return True

    def preemptible( self, flag = True ):
        from ..agents import frames as F
        self._evicted = self._evicted and flag
        self.call.send( F.IN, b"warm\n" if flag else b"busy\n" )

    def evicted( self ) -> bool:
        return self._evicted


class _Nothing:
    devices = [ ]

    def preemptible( self, flag = True ):
        pass

    def evicted( self ) -> bool:
        return False


@contextlib.contextmanager
def held( host, needs: dict, label: str ):
    if not host.remote:
        with queue.claim( needs, label = label ) as granted:
            yield granted
        return
    from .. import agents, bootstrap
    from ..agents import frames as F, upstream as U
    try:
        conn = agents.open( U.ssh_target( host.ssh ) )
        said = conn.ping()
        boot = f"{said.get( 'cache' ) or said[ 'home' ] + '/' + bootstrap.BASE}/{bootstrap.boot_rel()}"
        call = conn.open( { "op": "spawn", "keep": False, "argv": [
            said[ "python" ], boot, "-m", "errand.queue", "hold",
            json.dumps( { "needs": needs, "label": label } ) ] } )
        call.reply()
    except Exception as err:
        print( f"  ( the machine that runs it cannot count it in its queue: {err} )", file = sys.stderr )
        yield _Nothing()
        return
    remote = _Remote( call )
    try:
        if not remote.granted():
            print( "  ( the claim over there could not be held: running uncounted )", file = sys.stderr )
            yield _Nothing()
        else:
            yield remote
    finally:
        try:
            call.send( F.EOF )
            call.close()
        except OSError:
            pass
