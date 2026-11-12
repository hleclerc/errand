"""Frames: what crosses between a client, the hub and an agent, over any byte stream.

    [ channel: u32 ][ type: u8 ][ length: u32 ][ payload ]

A channel is one conversation: one request and what follows from it ( a
process's output, its exit ). Its number is chosen by whoever opens it, and is
only meaningful on that one connection: the hub renumbers when it relays.

    OPEN    -> agent    a request, JSON: { "op": "spawn" | "attach" | "list" | "ping", ... }
    REPLY   <- agent    the answer to OPEN, JSON: { "ok": true, ... } or { "error": "..." }
    OUT     <- agent    stdout bytes
    ERR     <- agent    stderr bytes
    IN      -> agent    stdin bytes
    EOF     -> agent    stdin is closed
    SIGNAL  -> agent    JSON: { "sig": n }
    CLOSE   -> agent    the client lets go of the channel; the process lives on if it may
    EXIT    <- agent    JSON: { "code": n }; the channel is over

Payloads are bytes as they are; JSON ones are UTF-8.
"""
from __future__ import annotations

import json
import struct
import threading


OPEN, REPLY, OUT, ERR, IN, EOF, SIGNAL, CLOSE, EXIT = range( 1, 10 )
NAMES = { OPEN: "open", REPLY: "reply", OUT: "out", ERR: "err", IN: "in", EOF: "eof",
          SIGNAL: "signal", CLOSE: "close", EXIT: "exit" }

HEADER = struct.Struct( ">IBI" )
MAX = 1 << 24                       # a frame bigger than this is a broken stream, not data


class Broken( EOFError ):
    """The other end is gone, or sent something that is not a frame."""


def _exactly( read, n: int ) -> bytes:
    out = b""
    while len( out ) < n:
        got = read( n - len( out ) )
        if not got:
            raise Broken( "stream closed" )
        out += got
    return out


def read_frame( read ):
    """`read( n )` -> up to n bytes ( a file's `read`, a socket's `recv` ). -> ( channel, type, payload )."""
    channel, kind, length = HEADER.unpack( _exactly( read, HEADER.size ) )
    if length > MAX or kind not in NAMES:
        raise Broken( f"not a frame ( type {kind}, length {length} )" )
    return channel, kind, _exactly( read, length ) if length else b""


def pack( channel: int, kind: int, payload = b"" ) -> bytes:
    if not isinstance( payload, ( bytes, bytearray ) ):
        payload = json.dumps( payload ).encode()
    return HEADER.pack( channel, kind, len( payload ) ) + payload


def load( payload: bytes ) -> dict:
    return json.loads( payload.decode() ) if payload else { }


class Writer:
    """Frames out of several threads, never interleaved. `write( b )` sends all of b."""

    def __init__( self, write ):
        self._write = write
        self._lock  = threading.Lock()

    def send( self, channel: int, kind: int, payload = b"" ):
        data = pack( channel, kind, payload )
        with self._lock:
            self._write( data )
