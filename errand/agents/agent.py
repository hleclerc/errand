"""An agent: a process that stays, starts processes when asked, and outlives its clients.

It listens on a unix socket in its directory. Clients come and go, through the
`connect` bridge ( `daemon.py` ) or directly; what it started keeps running and
keeps writing to disk whoever is listening ( `procs.py` ). With no client and
nothing running for `keep_alive` seconds, it goes, and takes its socket with it.

One agent per directory: a lock held for its whole life says so.
"""
from __future__ import annotations

import fcntl
import os
import socket
import threading
import time
from pathlib import Path

from . import frames as F
from .procs import finished, Proc, sweep


class Agent:
    def __init__( self, root: Path, keep_alive: float ):
        self.root       = Path( root )
        self.keep_alive = keep_alive
        self.procs      : dict = { }        # id -> Proc
        self.clients    = 0
        self.idle_since = time.monotonic()
        self.lock       = threading.Lock()

    # -- one client -----------------------------------------------------------

    def serve_client( self, conn: socket.socket ):
        writer = F.Writer( conn.sendall )
        channels : dict = { }               # channel -> Proc, on this connection
        try:
            while True:
                channel, kind, payload = F.read_frame( conn.recv )
                if kind == F.OPEN:
                    self.open( writer, channels, channel, F.load( payload ) )
                    continue
                proc = channels.get( channel )
                if proc is None:
                    continue
                if kind == F.IN:
                    proc.write( payload )
                elif kind == F.EOF:
                    proc.close_input()
                elif kind == F.SIGNAL:
                    proc.signal( int( F.load( payload ).get( "sig", 15 ) ) )
                elif kind == F.CLOSE:
                    channels.pop( channel, None )
                    with proc.lock:
                        proc.listeners = [ l for l in proc.listeners if l != ( writer, channel ) ]
        except ( F.Broken, OSError ):
            pass
        finally:
            for proc in set( channels.values() ):
                proc.detach( writer )
            with self.lock:
                self.clients -= 1
                self.idle_since = time.monotonic()
            conn.close()

    def open( self, writer, channels, channel, req ):
        op = req.get( "op" )
        try:
            if op == "ping":
                writer.send( channel, F.REPLY, { "ok": True, "pid": os.getpid(), "root": str( self.root ) } )
            elif op == "spawn":
                proc = Proc( self.root, req[ "argv" ], req.get( "env" ), req.get( "cwd" ), bool( req.get( "keep" ) ) )
                with self.lock:
                    self.procs[ proc.id ] = proc
                channels[ channel ] = proc
                writer.send( channel, F.REPLY, { "ok": True, "id": proc.id } )
                proc.attach( writer, channel )
            elif op == "attach":
                proc = self.procs.get( req[ "id" ] )
                if proc is None:
                    self.replay( writer, channel, req )
                else:
                    channels[ channel ] = proc
                    writer.send( channel, F.REPLY, { "ok": True, "id": proc.id } )
                    proc.attach( writer, channel, req.get( "out", 0 ), req.get( "err", 0 ) )
            elif op == "list":
                writer.send( channel, F.REPLY, { "ok": True, "procs": finished( self.root ) } )
            else:
                writer.send( channel, F.REPLY, { "error": f"unknown request {op!r}" } )
        except Exception as err:          # said to the client, not fatal to the agent
            writer.send( channel, F.REPLY, { "error": f"{type( err ).__name__}: {err}" } )

    def replay( self, writer, channel, req ):
        """A process of an earlier life of this agent: what it left on disk."""
        d = self.root / "proc" / str( req[ "id" ] )
        if not ( d / "meta.json" ).exists():
            writer.send( channel, F.REPLY, { "error": f"no process {req[ 'id' ]} here" } )
            return
        writer.send( channel, F.REPLY, { "ok": True, "id": req[ "id" ] } )
        for name, kind in ( ( "out", F.OUT ), ( "err", F.ERR ) ):
            if ( d / name ).exists():
                with open( d / name, "rb" ) as f:
                    f.seek( req.get( name, 0 ) )
                    writer.send( channel, kind, f.read() )
        code = ( d / "exit" ).read_text().strip() if ( d / "exit" ).exists() else ""
        # Started by an agent that is gone, and not finished: nobody can say how it ends.
        writer.send( channel, F.EXIT, { "code": int( code ) if code else -1, "lost": not code } )

    # -- the life of it -------------------------------------------------------

    def idle( self ) -> bool:
        with self.lock:
            running = any( p.code is None for p in self.procs.values() )
            if self.clients or running:
                self.idle_since = time.monotonic()
                return False
            return time.monotonic() - self.idle_since > self.keep_alive

    def run( self ):
        self.root.mkdir( parents = True, exist_ok = True )
        held = open( self.root / "lock", "w" )
        try:
            fcntl.flock( held, fcntl.LOCK_EX | fcntl.LOCK_NB )
        except OSError:
            return 0                       # another agent has this directory: it answers
        sweep( self.root )
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
                    self.clients += 1          # counted before `idle` can look again
                threading.Thread( target = self.serve_client, args = ( conn, ), daemon = True ).start()
        finally:
            server.close()
            if path.exists():
                path.unlink()
        return 0
