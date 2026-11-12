"""The hub: one process here, per user, that keeps the streams to the agents open between commands.

An `errand` command connects to the hub's socket, names the agent it wants
( a target, `upstream.py` ) with a `route` request on channel 0, and from then
on speaks to that agent as if directly: the hub relays every frame, renumbering
channels so that several commands share one stream. The first command to want
an agent pays for reaching it; the next ones do not.

A stream that breaks ( a network drop ) ends the calls that were on it with a
`lost` EXIT, and the next route opens a new one -- the agent over there did not
notice, and what it runs goes on. With no command connected for `keep_alive`
seconds, the hub closes its streams and goes.
"""
from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

from . import frames as F, upstream as U
from . import endpoint


class Upstream:
    """One stream to one agent, shared by every command routed to it."""

    def __init__( self, hub: "Hub", target: dict ):
        self.hub, self.target = hub, target
        log = open( hub.root / "log", "ab" )
        self.proc   = U.spawn( target, stderr = log )
        self.out    = self.proc.stdout.fileno()
        self.writer = F.Writer( self._write )
        self.routes : dict = { }        # upstream channel -> ( client writer, client channel )
        self.used   = time.monotonic()  # the last frame either way: a stream unused for its target's
        self.keep   = float( target.get( "keep_alive" ) or U.KEEP_ALIVE )   # keep_alive is closed
        self.lock   = threading.Lock()
        self.next   = 1
        self.alive  = True
        self._skip()
        threading.Thread( target = self._pump, daemon = True ).start()

    def _write( self, data ):
        self.used = time.monotonic()
        self.proc.stdin.write( data )
        self.proc.stdin.flush()

    def _skip( self ):
        from .client import MARKER, Lost
        seen = b""
        while not seen.endswith( MARKER ):
            got = os.read( self.out, 1 )
            if not got:
                raise Lost( "the bridge to the agent did not start" )
            seen = ( seen + got )[ -4096 : ]

    def _pump( self ):
        try:
            while True:
                channel, kind, payload = F.read_frame( lambda n: os.read( self.out, n ) )
                self.used = time.monotonic()
                with self.lock:
                    route = self.routes.get( channel )
                    if kind == F.EXIT:
                        self.routes.pop( channel, None )
                if route:
                    try:
                        route[ 0 ].send( route[ 1 ], kind, payload )
                    except OSError:
                        pass
        except ( F.Broken, OSError ):
            pass
        self.alive = False
        with self.lock:
            routes, self.routes = list( self.routes.values() ), { }
        for writer, channel in routes:
            try:
                writer.send( channel, F.EXIT, { "code": -1, "lost": True } )
            except OSError:
                pass
        self.hub.forget( self )

    def open( self, writer, channel ) -> int:
        with self.lock:
            mine = self.next
            self.next += 1
            self.routes[ mine ] = ( writer, channel )
        return mine

    def close( self ):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.terminate()


class Hub:
    def __init__( self, root: Path, keep_alive: float ):
        self.root, self.keep_alive = Path( root ), keep_alive
        self.upstreams : dict = { }     # identity of target -> Upstream
        self.making    : dict = { }     # identity of target -> the lock of whoever is making it
        self.clients = 0
        self.idle_since = time.monotonic()
        self.lock = threading.Lock()

    def upstream( self, target: dict ) -> Upstream:
        key = U.identity( target )
        with self.lock:
            up = self.upstreams.get( key )
            if up is not None and up.alive:
                return up
            making = self.making.setdefault( key, threading.Lock() )
        # Not under the hub's lock: reaching an environment goes through `rsh`, which comes back
        # here for the host's stream while this one is still being made.
        with making:
            with self.lock:
                up = self.upstreams.get( key )
            if up is None or not up.alive:
                up = Upstream( self, target )
                with self.lock:
                    self.upstreams[ key ] = up
            return up

    def forget( self, up: Upstream ):
        with self.lock:
            for k, v in list( self.upstreams.items() ):
                if v is up:
                    del self.upstreams[ k ]

    def serve_client( self, conn: socket.socket ):
        writer = F.Writer( conn.sendall )
        mine : dict = { }               # client channel -> upstream channel
        up = None
        try:
            channel, kind, payload = F.read_frame( conn.recv )
            req = F.load( payload )
            if kind != F.OPEN or req.get( "op" ) != "route":
                writer.send( channel, F.REPLY, { "error": "route first" } )
                return
            try:
                up = self.upstream( req[ "target" ] )
            except Exception as err:
                writer.send( channel, F.REPLY, { "error": f"cannot reach the agent: {err}" } )
                return
            writer.send( channel, F.REPLY, { "ok": True } )
            while True:
                channel, kind, payload = F.read_frame( conn.recv )
                if kind == F.OPEN:
                    mine[ channel ] = up.open( writer, channel )
                if channel in mine:
                    up.writer.send( mine[ channel ], kind, payload )
                if kind == F.CLOSE and channel in mine:
                    with up.lock:
                        up.routes.pop( mine.pop( channel ), None )
        except ( F.Broken, OSError ):
            pass
        finally:
            if up is not None:
                for theirs in mine.values():
                    try:
                        up.writer.send( theirs, F.CLOSE )
                    except OSError:
                        pass
                    with up.lock:
                        up.routes.pop( theirs, None )
            with self.lock:
                self.clients -= 1
                self.idle_since = time.monotonic()
            conn.close()

    def idle( self ) -> bool:
        # A stream nobody used for its target's keep_alive goes: what it holds over there ( an
        # allocation's node, a machine ) is let go of, and the next command reaches it again.
        now = time.monotonic()
        with self.lock:
            stale = [ ( k, up ) for k, up in self.upstreams.items() if not up.routes and now - up.used > up.keep ]
            for k, _ in stale:
                del self.upstreams[ k ]
        for _, up in stale:
            up.close()
        with self.lock:
            if self.clients:
                self.idle_since = time.monotonic()
                return False
            return time.monotonic() - self.idle_since > self.keep_alive

    def run( self ) -> int:
        def client( conn, threading ):
            with self.lock:
                self.clients += 1
            threading.Thread( target = self.serve_client, args = ( conn, ), daemon = True ).start()

        def closing():
            for up in list( self.upstreams.values() ):
                up.close()

        return endpoint.serve( self.root, self.idle, client, closing )
        path = self.root / "sock"
        if path.exists():
            path.unlink()
        server = socket.socket( socket.AF_UNIX, socket.SOCK_STREAM )
        server.bind( str( path ) )
        os.chmod( path, 0o600 )
        server.listen( 16 )
        server.settimeout( 1.0 )
        try:
            while not self.idle():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                conn.settimeout( None )
                with self.lock:
                    self.clients += 1
                threading.Thread( target = self.serve_client, args = ( conn, ), daemon = True ).start()
        finally:
            server.close()
            if path.exists():
                path.unlink()
            for up in list( self.upstreams.values() ):
                up.close()
        return 0
