"""What a machine answers about itself, for whoever watches it ( `errand tui` ): the agent's ops

    table   what runs here, VMs and guests included ( `table.scan` )
    seen    the runs done here whose directory is still there ( `seen.runs` )
    ls      the files of a directory ( a run's leaf )
    tail    a file, from an offset
    kill    a process group: INT, TERM after 2 s, KILL after 5 s, then its `cancel` line ( ADR 0008/0009 )

`answer( req )` is the one entry: the agent calls it for a remote watcher, the watcher calls it
directly for this machine. The files read are the user's own, through their own agent.
"""
from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

OPS   = ( "table", "seen", "ls", "tail", "kill" )
CHUNK = 1 << 20          # what `tail` sends at most at once


def answer( req: dict ) -> dict:
    op = req.get( "op" )
    try:
        if op == "table":
            from .table import scan
            return { "ok": True, **scan( guests = bool( req.get( "guests", True ) ) ) }
        if op == "seen":
            from .seen import runs
            return { "ok": True, **runs( int( req.get( "limit" ) or 50 ) ) }
        if op == "ls":
            return { "ok": True, "files": ls( Path( req[ "path" ] ) ) }
        if op == "tail":
            return { "ok": True, **tail( Path( req[ "path" ] ), req.get( "offset" ), int( req.get( "size" ) or CHUNK ) ) }
        if op == "kill":
            return kill( req )
    except Exception as err:
        return { "error": f"{type( err ).__name__}: {err}" }
    return { "error": f"unknown request {op!r}" }


def ls( d: Path ) -> list:
    """Files under `d` ( two levels down ), newest first: { name, size, mtime }."""
    out = [ ]
    for p in [ *d.glob( "*" ), *d.glob( "*/*" ) ]:
        try:
            st = p.stat()
        except OSError:
            continue
        if p.is_file():
            out.append( { "name": str( p.relative_to( d ) ), "size": st.st_size, "mtime": st.st_mtime } )
    return sorted( out, key = lambda f: -f[ "mtime" ] )[ : 200 ]


def tail( path: Path, offset, size = CHUNK ) -> dict:
    """At most `size` bytes of `path` from `offset`; `offset` None: its last `size` bytes.
    -> { data, offset ( where `data` starts ), end ( where it stops ), size ( of the file ) }"""
    try:
        total = path.stat().st_size
    except OSError:
        return { "data": "", "offset": 0, "size": 0, "missing": True }
    start = max( 0, total - size ) if offset is None else min( int( offset ), total )
    with open( path, "rb" ) as f:
        f.seek( start )
        data = f.read( size )
    return { "data": data.decode( "utf-8", "replace" ), "offset": start, "end": start + len( data ), "size": total }


def kill( req: dict ) -> dict:
    """A process group stopped by its owner's rules, from anywhere on its machine: `pgid` ( and its
    `since`, so that a group of a reused pid is left alone ), `mark`: its marker, for `cancel`.
    The escalation goes on in a thread: the answer is that it started."""
    from . import procs as P
    if P.WINDOWS:
        return { "error": "stopping from here is not done on Windows yet: stop it from its command" }
    pgid, since = int( req[ "pgid" ] ), req.get( "since" )
    if not P.ours( pgid, since ):
        return { "error": f"group {pgid} is not running any more" }

    def escalate():
        for sig, after in ( ( signal.SIGINT, P.GRACE[ 0 ] ), ( signal.SIGTERM, P.GRACE[ 1 ] - P.GRACE[ 0 ] ) ):
            P._killpg( pgid, sig )
            deadline = time.monotonic() + after
            while time.monotonic() < deadline and P._killpg( pgid, 0 ):
                time.sleep( 0.1 )
            if not P._killpg( pgid, 0 ):
                break
        if req.get( "mark" ):
            P.cancel( Path( req[ "mark" ] ) )
        P._killpg( pgid, P.SIGKILL )

    threading.Thread( target = escalate, daemon = True ).start()
    return { "ok": True, "pid": os.getpid() }
