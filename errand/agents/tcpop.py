"""The agent's `tcp` operation ( ADR 0018 step 6, `forward` ): a channel that IS a connection to a service of this machine.

    OPEN  { "op": "tcp", "service": NAME [, "port": PORT_NAME ] }
    REPLY { "ok": true, "address": "127.0.0.1:P" }  once the service answers ( ensured first, under the queue, as
                                                     `errand serve` does ), or { "error": ... }
    IN / EOF -> the connection's bytes, its write side shut
    OUT      <- what the service sends
    EXIT     <- { "code": 0 } when the service closes it ( 1 on an error )
    CLOSE    -> the client lets go: the connection is closed

Only a DECLARED service can be reached ( `serve.declared`, from the agent's home: never a project's files ), never a port
named by the client: what the agent's socket lets in is its own user already, and a service is what that user said to run.
The connection goes through the announced port, so the keeper counts it as a use.
"""
from __future__ import annotations

import socket
import threading

from . import frames as F

_declared = threading.Lock()                    # ( `serve.declared` refills one global table: one reader at a time )


class TcpChannel:
    """what `Agent.serve_client` calls on a channel ( as on a `Proc` ): write, close_input, stop, signal, resize, detach"""

    def __init__( self, writer, channel ):
        self.writer, self.channel = writer, channel
        self.sock = None
        self.pending = [ ]                       # IN before the connection is made
        self.eof = False
        self.lock = threading.Lock()

    def start( self, req: dict ):
        threading.Thread( target = self._run, args = ( req, ), daemon = True ).start()

    def _run( self, req ):
        from .. import serve as S
        name = str( req.get( "service" ) or "" )
        try:
            with _declared:
                found = S.declared( cwd = str( S.home() ) )
            if name not in found:
                raise LookupError( f"no service {name!r} is declared here" )
            st = S.ensure( name, cwd = str( S.home() ) )
            host, port = S.address( st, req.get( "port" ) ).rsplit( ":", 1 )
            sock = socket.create_connection( ( host, int( port ) ), timeout = 30 )
            sock.settimeout( None )
        except Exception as err:
            self.writer.send( self.channel, F.REPLY, { "error": f"{type( err ).__name__}: {err}" } )
            return
        with self.lock:
            self.sock = sock
            for chunk in self.pending:
                sock.sendall( chunk )
            self.pending = [ ]
            if self.eof:
                _shut( sock, socket.SHUT_WR )
        self.writer.send( self.channel, F.REPLY, { "ok": True, "address": f"{host}:{port}" } )
        code = 0
        try:
            for chunk in iter( lambda: sock.recv( 65536 ), b"" ):
                self.writer.send( self.channel, F.OUT, chunk )
        except OSError:
            code = 1
        finally:
            _close( sock )
        try:
            self.writer.send( self.channel, F.EXIT, { "code": code } )
        except OSError:
            pass

    def write( self, data: bytes ):
        with self.lock:
            if self.sock is None:
                self.pending.append( data )
                return
        try:
            self.sock.sendall( data )
        except OSError:
            pass

    def close_input( self ):
        with self.lock:
            self.eof = True
            if self.sock is not None:
                _shut( self.sock, socket.SHUT_WR )

    def stop( self ):
        self.detach( None )

    def signal( self, sig ):
        self.detach( None )

    def resize( self, cols, rows ):
        pass

    def detach( self, writer = None, channel = None ):
        with self.lock:
            if self.sock is not None:
                _close( self.sock )


def _shut( sock, how ):
    try:
        sock.shutdown( how )
    except OSError:
        pass


def _close( sock ):
    _shut( sock, socket.SHUT_RDWR )
    try:
        sock.close()
    except OSError:
        pass
