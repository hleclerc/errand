"""What a machine answers about itself, for whoever watches it ( `errand tui` ): the agent's ops

    table   what runs here, VMs and guests included ( `table.scan` )
    seen    the runs done here whose directory is still there ( `seen.runs` )
    ls      the files of a directory ( a run's leaf )
    tail    a file, from an offset
    kill    a process group: INT, TERM after 2 s, KILL after 5 s, then its `cancel` line ( ADR 0008/0009 )
    watch   a subscription ( `Watch` ): events on the channel as things change, instead of asking again

`answer( req )` is the one entry for the questions: the agent calls it for a remote watcher, the watcher calls it
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
            if req.get( "dirs" ):
                return { "ok": True, "entries": entries( Path( req[ "path" ] ) ) }
            return { "ok": True, "files": ls( Path( req[ "path" ] ) ) }
        if op == "tail":
            return { "ok": True, **tail( Path( req[ "path" ] ), req.get( "offset" ), int( req.get( "size" ) or CHUNK ),
                                         raw = bool( req.get( "raw" ) ) ) }
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


def entries( d: Path ) -> list:
    """What is in `d`, one level: { name, dir, size, mtime }, directories first ( `errand web` ). At most 2000."""
    out = [ ]
    try:
        children = list( d.iterdir() )
    except OSError as err:
        raise FileNotFoundError( f"{d}: {err.strerror or err}" )
    for p in children[ : 2000 ]:
        try:
            st = p.stat()
        except OSError:
            continue
        out.append( { "name": p.name, "dir": p.is_dir(), "size": st.st_size, "mtime": st.st_mtime } )
    return sorted( out, key = lambda e: ( not e[ "dir" ], e[ "name" ].lower() ) )


def tail( path: Path, offset, size = CHUNK, raw = False ) -> dict:
    """At most `size` bytes of `path` from `offset`; `offset` None: its last `size` bytes.
    -> { data, offset ( where `data` starts ), end ( where it stops ), size ( of the file ) }.
    `raw`: the bytes as they are, in base64 ( `b64` ), not read as text -- an image, a PDF."""
    try:
        total = path.stat().st_size
    except OSError:
        return { "data": "", "offset": 0, "size": 0, "missing": True }
    start = max( 0, total - size ) if offset is None else min( int( offset ), total )
    with open( path, "rb" ) as f:
        f.seek( start )
        data = f.read( size )
    if raw:
        import base64
        return { "b64": base64.b64encode( data ).decode(), "offset": start, "end": start + len( data ), "size": total }
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


# ── a subscription ───────────────────────────────────────────────────────────

import json as _json

QUICK     = 0.5          # seconds between two looks at what says something changed ( directory dates )
FULL      = 2.0          # seconds between two full tables, sent only when they differ
MEASURE   = 5.0          # seconds between two measures of the resources, sent when they moved
SEEN      = 5.0          # seconds between two looks at the history
HEARTBEAT = 10.0         # an event at least this often: the watcher knows the agent is there

_watching: set = set()               # the subscriptions of this agent, each with its own wake


def nudge( ):
    """Something changed here that this agent knows of ( a process it started, or that ended ): every
    watcher looks now, not at its next turn."""
    for w in list( _watching ):
        w.poke.set()


def _marks( ) -> tuple:
    """What moves when a process starts or ends anywhere on this machine, a VM comes or goes, a run is
    recorded: the dates of the agents' `proc` directories, of the VMs', of the history's. A `stat` each."""
    from .. import bootstrap
    from . import table
    out = [ ]
    cache = bootstrap.local_cache()
    for d in [ *table.agent_dirs( table.roots() ), cache / "vm", cache / "seen", cache / "alloc" ]:
        for p in ( d / "proc", d ):
            try:
                out.append( ( str( p ), p.stat().st_mtime_ns ) )
                break
            except OSError:
                continue
    return tuple( out )


def _shape( table: dict ) -> str:
    """A table, as compared: everything but when it was read and the resources, which have their events."""
    return _json.dumps( { k: v for k, v in table.items() if k not in ( "time", "resources" ) }, sort_keys = True, default = str )


def _rounded( res: dict | None ) -> str:
    """Resources as compared: a change of a few points is no event."""
    if not res:
        return ""
    ram = res.get( "ram" ) or { }
    return _json.dumps( [ round( ( res.get( "busy" ) or 0 ) * 20 ), round( 100 * ram.get( "used", 0 ) / ( ram.get( "total" ) or 1 ) ),
                          [ ( round( ( g.get( "util" ) or 0 ) / 5 ), round( g.get( "used", 0 ) / 512 ) ) for g in res.get( "gpus" ) or [ ] ],
                          res.get( "held" ) ], default = str )


class Watch:
    """A watcher's subscription ( `op: watch` ), on its channel: `{"table": …}` when what runs changes,
    `{"resources": …}` when they move by more than a few points, `{"seen": …}` when the history does, and
    at least one event every `HEARTBEAT` seconds. Over when the watcher closes the channel or goes
    ( `detach`, as a process's listener would )."""

    def __init__( self, writer, channel, req: dict ):
        self.writer, self.channel, self.req = writer, channel, req
        self.stopped = threading.Event()
        self.poke = threading.Event()
        self.thread = threading.Thread( target = self._run, daemon = True )

    def start( self ):
        _watching.add( self )
        self.thread.start()
        return self

    def _send( self, event: dict ) -> bool:
        from . import frames as F
        try:
            self.writer.send( self.channel, F.OUT, _json.dumps( event, default = str ).encode() )
            return True
        except OSError:
            self.stopped.set()             # the watcher is gone
            return False

    def _run( self ):
        from . import resources, seen, table as T
        guests = bool( self.req.get( "guests", True ) )
        limit = int( self.req.get( "limit" ) or 200 )
        shape = res = runs = marks = None
        measured = None
        full_at = seen_at = sent_at = measured_at = 0.0
        while not self.stopped.is_set():
            now = time.time()
            if now - measured_at >= MEASURE:
                measured_at, measured = now, T._resources()
                if shape is not None and _rounded( measured ) != res:      # the table says them when it goes
                    res = _rounded( measured )
                    if not self._send( { "resources": measured, "time": now } ):
                        return
                    sent_at = now
            m = _marks()
            if m != marks or now - full_at >= FULL:
                marks, full_at = m, now
                got = T.scan( guests = guests, resources = False )
                if _shape( got ) != shape:
                    shape, res = _shape( got ), _rounded( measured )
                    if not self._send( { "table": { **got, "resources": measured } } ):
                        return
                    sent_at = now
            if now - seen_at >= SEEN:
                seen_at = now
                got = seen.runs( limit )
                key = _json.dumps( got, sort_keys = True, default = str )
                if key != runs:
                    runs = key
                    if not self._send( { "seen": got } ):
                        return
                    sent_at = now
            if now - sent_at >= HEARTBEAT:
                if not self._send( { "alive": now } ):
                    return
                sent_at = now
            if self.poke.wait( QUICK ):
                self.poke.clear()
                marks = None                # looked at now: something this agent knows of changed
        _watching.discard( self )

    # what an agent asks of what holds a channel ( `Proc`'s ), for a subscription
    def detach( self, writer = None, channel = None ):
        self.stopped.set()
        self.poke.set()
        _watching.discard( self )

    def write( self, data ): pass
    def close_input( self ): pass
    def stop( self ): self.detach()
    def signal( self, sig ): pass
    def resize( self, cols, rows ): pass
