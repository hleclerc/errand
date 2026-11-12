"""`python -m errand.agents rsh <target> [ssh options] host command…`: a remote shell for rsync.

rsync starts its other end through a remote shell ( `-e` ), as `<shell> host
rsync --server …`. Given this one, the other end is started by the agent, over
the stream the hub already holds: no new ssh, no new login. stdin and stdout
are rsync's own protocol, relayed as they are; what the other end says on
stderr comes out on ours, and its exit code is ours.
"""
from __future__ import annotations

import base64
import json
import os
import threading

from . import frames as F


def command_of( args ) -> str:
    """rsync's arguments to its remote shell: options ( `-l user`, `-p port` ), the host, then the command."""
    i = 0
    while i < len( args ) and args[ i ].startswith( "-" ):
        i += 2 if args[ i ] in ( "-l", "-p", "-o", "-i", "-F" ) else 1
    return " ".join( args[ i + 1 : ] )


def main( code: str, args ) -> int:
    from . import open as open_agent
    # rsync's pipes are not a terminal, yet this is only ever used when there is a hub to go through.
    os.environ[ "ERRAND_AGENT" ] = "hub"
    target = json.loads( base64.urlsafe_b64decode( code.encode() ).decode() )
    conn = open_agent( target )
    call = conn.open( { "op": "spawn", "argv": [ "sh", "-c", command_of( args ) ], "keep": False } )
    call.reply()
    # rsync hands its remote shell one non-blocking socket as stdin and stdout.
    for fd in ( 0, 1 ):
        os.set_blocking( fd, True )

    def up():
        try:
            for chunk in iter( lambda: os.read( 0, 65536 ), b"" ):
                call.send( F.IN, chunk )
        except OSError:
            pass
        call.send( F.EOF )

    threading.Thread( target = up, daemon = True ).start()
    while True:
        kind, payload = call.next()
        if kind in ( F.OUT, F.ERR ):
            view = memoryview( payload )
            while view:
                view = view[ os.write( 1 if kind == F.OUT else 2, view ) : ]
        elif kind == F.EXIT:
            return int( F.load( payload ).get( "code", 1 ) )
