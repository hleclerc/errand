"""The machines watched: this one, and every machine of the ledger, each asked by a thread of its own.

Each is asked through its agent ( `look`: `table`, `seen`, `ls`, `tail`, `kill` ), this one directly.
What it answered last stays shown when it stops answering, with the error beside it.
"""
from __future__ import annotations

import socket
import threading
import time

EVERY   = { "here": 2.0, "remote": 3.0 }      # seconds between tables
HISTORY = 15.0                                 # seconds between histories


class Machine:
    def __init__( self, name: str, target: dict | None = None ):
        self.name, self.target = name, target          # target None: this machine
        self.table   : dict | None = None
        self.history : dict | None = None
        self.error   : str | None = None
        self.read_at = 0.0                             # time.time() of the last table
        self.wake    = threading.Event()
        self.stopped = False
        self.history_at = 0.0

    @property
    def here( self ):
        return self.target is None

    def ask( self, req: dict, timeout = 60.0 ) -> dict:
        """One question to this machine's agent -> its answer; raises what went wrong, said plainly."""
        from ..agents import look
        if self.here:
            got = look.answer( req )
            if got.get( "error" ):
                raise RuntimeError( got[ "error" ] )
            return got
        from .. import agents
        call = agents.open( self.target ).open( req )
        try:
            return call.reply( timeout )
        finally:
            call.close()

    def now( self ) -> float:
        """This machine's clock now, as well as its last table says it: ages are its own, not ours."""
        if not self.table:
            return time.time()
        return self.table.get( "time", self.read_at ) + ( time.time() - self.read_at )

    def watch( self ):
        threading.Thread( target = self._loop, daemon = True ).start()

    def _loop( self ):
        while not self.stopped:
            try:
                got = self.ask( { "op": "table" }, timeout = 90 )
                self.table, self.read_at, self.error = got, time.time(), None
                if time.time() - self.history_at > HISTORY:
                    self.history, self.history_at = self.ask( { "op": "seen", "limit": 200 } ), time.time()
            except Exception as err:
                said = str( err ).strip()
                self.error = said.splitlines()[ -1 ] if said else type( err ).__name__
            self.wake.wait( EVERY[ "here" if self.here else "remote" ] )
            self.wake.clear()


def watched( ) -> list:
    """This machine first, then the ledger's, as `errand status` asks them."""
    from ..agents import ledger
    here = socket.gethostname().split( "." )[ 0 ]
    out = [ Machine( here ) ]
    for rec in ledger.machines():
        if rec[ "name" ] not in ( m.name for m in out ):
            out.append( Machine( rec[ "name" ], rec[ "target" ] ) )
    return out
