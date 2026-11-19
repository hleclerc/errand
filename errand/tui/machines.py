"""The machines watched: this one, and every machine of the ledger, each asked by a thread of its own.

Each is asked through its agent ( `look`: `table`, `seen`, `ls`, `tail`, `kill` ), this one directly.
What it answered last stays shown when it stops answering, with the error beside it.
"""
from __future__ import annotations

import json
import socket
import threading
import time



class Machine:
    def __init__( self, name: str, target: dict | None = None, last: float | None = None, names = ( ),
                  watch = None ):
        self.name, self.target = name, target          # target None: this machine
        self.names   = list( names ) or [ name ]       # every name it is reached by ( `ledger.groups` )
        self.last    = last                            # when work was last sent there ( the ledger's )
        self.watch_set = watch                         # True / False when set with `a`, None: as its work says
        # not contacted: switched off ( `a` ), or no work there for a day: no agent started for nothing
        idle = target is not None and last is not None and time.time() - last > _dormant_after()
        self.dormant = target is not None and ( watch is False or ( watch is None and idle ) )
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
        call = agents.open( self.target, noted = False ).open( req )   # looking is no work sent there
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
        if self.dormant:
            return
        threading.Thread( target = self._loop, daemon = True ).start()

    def activate( self ):
        """Contacted from now on."""
        if self.dormant:
            self.dormant, self.stopped = False, False
            self.watch()

    def deactivate( self ):
        """Not contacted any more: its subscription ends, what it said is put away."""
        self.dormant, self.stopped = True, True
        self.wake.set()
        self.table, self.error = None, None

    def _loop( self ):
        """Subscribed to ( `look.Watch`, ADR 0024 ): its agent says what changes as it changes -- this machine as well.
        Gone, subscribed again a moment later. An agent that does not know `watch` ( an older errand ) is said so: it
        is to be stopped ( `errand agents stop --force` ), not asked."""
        while not self.stopped:
            try:
                if not self._subscribed():
                    self.error = "an older agent, that says nothing: `errand agents stop --force`, then again"
            except Exception as err:
                self.error = brief( err )
            if not self.stopped:
                self.wake.wait( 3.0 )
                self.wake.clear()

    def want_resources( self, on: bool ):
        """its resources measured and said while something shows them ( the machines tab ), not otherwise"""
        on = bool( on )
        if on == getattr( self, "_resources", False ):
            return
        self._resources = on
        call = getattr( self, "_call", None )
        if call is not None:
            from ..agents import frames as F
            try:
                call.send( F.IN, json.dumps( { "resources": on } ).encode() )
            except Exception:
                pass

    def _subscribed( self ) -> bool:
        """Events until the subscription ends. -> False when the agent does not know `watch`."""
        from .. import agents
        from ..agents import frames as F
        req = { "op": "watch", "limit": 1000, "resources": getattr( self, "_resources", False ) }
        if self.here:                                # this machine: through its host agent, which hears its bell
            from ..agents import upstream as U
            from ..web import host_agent_dir
            conn = U.direct( { "kind": "local", "dir": str( host_agent_dir() ), "keep_alive": U.KEEP_ALIVE } )
            call = conn.open( req )
        else:
            conn, call = None, agents.open( self.target, noted = False ).open( req )
        try:
            try:
                call.reply( 90 )
            except RuntimeError as err:
                if "unknown" in str( err ):
                    return False
                raise
            self._call = call
            while not self.stopped:
                try:
                    kind, payload = call.next( timeout = 1.0 )
                except TimeoutError:
                    if self.wake.is_set():           # `r`: asked to read again, from scratch
                        self.wake.clear()
                        return True
                    continue
                if kind == F.EXIT:
                    return True
                if kind != F.OUT:
                    continue
                self.event( json.loads( payload ) )
            return True
        finally:
            self._call = None
            call.close()
            if conn is not None:
                conn.close()

    def event( self, e: dict ):
        """One event of the subscription, into what is shown."""
        now = time.time()
        if "table" in e:
            self.table, self.error = e[ "table" ], None
            if e[ "table" ].get( "host" ) and e[ "table" ][ "host" ] != getattr( self, "_host", None ):
                self._host = e[ "table" ][ "host" ]
                try:                                     # two names that answer alike: one machine, next time
                    from ..agents import ledger
                    for n in self.names:
                        ledger.learn( n, self._host )
                except Exception:
                    pass
        if "resources" in e and self.table is not None:
            self.table = { **self.table, "resources": e[ "resources" ], "time": e.get( "time", self.table.get( "time" ) ) }
        if "seen" in e:
            self.history, self.history_at = e[ "seen" ], now
        if "runs" in e:                                  # the history's delta: runs put ( new, changed ), dropped
            d = e[ "runs" ]
            put = { r[ "leaf" ]: r for r in d.get( "put" ) or [ ] }
            drop = set( d.get( "drop" ) or [ ] ) | set( put )
            old = [ r for r in ( self.history or { } ).get( "runs", [ ] ) if r.get( "leaf" ) not in drop ]
            runs = sorted( old + list( put.values() ), key = lambda r: -( r.get( "started" ) or 0 ) )
            self.history, self.history_at = { "runs": runs, "more": d.get( "more", 0 ) }, now
        self.read_at = now
        for listen in list( LISTENERS ):
            try:
                listen( self, e )
            except Exception:
                pass


LISTENERS: list = [ ]         # `f( machine, event )` after each event of each machine: `errand web`, the TUI ( ADR 0024 )


def brief( err: Exception ) -> str:
    """One line for a machine that did not answer. ssh that never got in says why on its first line,
    advice on the next ones; anything else says the gist last."""
    from ..layers.gateways import Unreachable
    said = str( err ).strip()
    if not said:
        return type( err ).__name__
    lines = said.splitlines()
    if isinstance( err, Unreachable ):
        return "unreachable: " + lines[ 0 ].split( ": ", 1 )[ -1 ] if lines[ 0 ].startswith( "cannot reach " ) else lines[ 0 ]
    return lines[ -1 ]


def watched( ) -> list:
    """This machine first, then the ledger's, as `errand status` asks them."""
    from ..agents import ledger
    out = [ Machine( ledger.here_name() ) ]
    for g in ledger.groups():                         # a machine once, whatever names it is reached by
        if g[ "name" ] not in ( m.name for m in out ):
            out.append( Machine( g[ "name" ], g[ "target" ], g[ "last" ], g[ "names" ], g.get( "watch" ) ) )
    return out


def _dormant_after( ) -> float:
    from ..agents.ledger import DORMANT
    return DORMANT
