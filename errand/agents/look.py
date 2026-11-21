"""What a machine answers about itself, for whoever watches it ( `errand tui` ): the agent's ops

    table   what runs here, VMs and guests included ( `table.scan` )
    seen    the runs done here whose directory is still there ( `seen.runs` )
    ls      the files of a directory ( a run's leaf )
    tail    a file, from an offset
    kill    a process group: INT, TERM after 2 s, KILL after 5 s, then its `cancel` line ( ADR 0008/0009 )
    caches  the library caches this machine holds, and its VM guests' ( `caches.report`, ADR 0022 )
    caches_remove   entries of one of them removed, by key or by rule ( `caches.remove_in` ), here or in a guest
    caches_hold     this machine holds one of them ( or all ): its host agent purges it ( `caches.hold` )
    watch   a subscription ( `Watch` ): events on the channel as things change, instead of asking again

`answer( req )` is the one entry for the questions: the agent calls it for a remote watcher, the watcher calls it
directly for this machine. The files read are the user's own, through their own agent.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import threading
import time
from pathlib import Path

OPS   = ( "table", "seen", "ls", "tail", "kill", "caches", "caches_remove", "caches_hold", "runs_remove" )
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
        if op in ( "caches", "caches_remove", "caches_hold" ):
            return caches( req )
        if op == "runs_remove":
            return runs_remove( req )
    except Exception as err:
        return { "error": f"{type( err ).__name__}: {err}" }
    return { "error": f"unknown request {op!r}" }


def runs_remove( req: dict ) -> dict:
    """`runs_remove`: { leaves: [ paths ], rels: [ paths under `runs/` ], nodes: [ tree ids ], how, dry } -> { leaves: [ what it would remove ],
    sizes: { leaf: bytes } } with `dry`, else { removed: [ leaves ], kept: [ [ leaf, why ] ], freed }. `nodes`: rows of
    the runs' tree ( `runtree` ids ), resolved here over every run this machine noted -- not only the latest a history
    says --, all of them, or all but the latest of each set and env ( `how`: "latest" ). Removed for good ( ADR 0023 ):
    only a run's directory this machine's `seen` noted ( never anything else ), never one whose run runs or waits; its
    link goes with it, and `latest` when it named it."""
    import shutil
    from . import seen as S
    from .table import scan
    d = S._dir()
    noted = { rec.get( "leaf" ): p for p, rec in ( S._records( d ) if d.is_dir() else [ ] ) }
    busy = { p.get( "leaf" ) for p in scan( guests = False ).get( "procs", [ ] ) if p.get( "leaf" ) }

    def size( path: Path ) -> int:
        total = 0
        for f in path.rglob( "*" ):
            try:
                if f.is_file() and not f.is_symlink():
                    total += f.stat().st_size
            except OSError:
                pass
        return total

    leaves = list( dict.fromkeys( [ str( x ) for x in req.get( "leaves" ) or [ ] ] + _selected( req, busy ) + _by_rel( req, noted ) ) )
    if req.get( "dry" ):
        mine = [ l for l in leaves if l in noted and l not in busy and Path( l ).is_dir() ]
        return { "ok": True, "leaves": mine, "sizes": _sizes( mine, size ) }
    removed, kept, freed = [ ], [ ], 0
    for l in leaves:
        path = Path( l )
        if l not in noted:
            kept.append( [ l, "not a run of this machine" ] )
            continue
        if l in busy:
            kept.append( [ l, "it runs" ] )
            continue
        if path.is_dir():
            freed += size( path )
            latest = path.parent / "latest"
            try:
                if latest.is_symlink() and latest.resolve() == path.resolve():
                    latest.unlink()
            except OSError:
                pass
            shutil.rmtree( path, ignore_errors = True )
        if path.exists():
            kept.append( [ l, "could not be removed" ] )
            continue
        noted[ l ].unlink( missing_ok = True )
        removed.append( l )
    if removed:
        nudge()                                         # its watchers see the history change now
        ring()                                          # ( asked by another process: the host agents too )
    return { "ok": True, "removed": removed, "kept": kept, "freed": freed }


def _by_rel( req: dict, noted: dict ) -> list:
    """the runs this machine noted whose path under `runs/` is one of `req[ "rels" ]` ( ADR 0025: a run of the record
    of the machine it was started from, its directory here found by the path both share )"""
    rels = { str( r ).strip( "/" ) for r in req.get( "rels" ) or [ ] }
    if not rels:
        return [ ]
    out = [ ]
    for leaf in noted:
        i = str( leaf ).find( "/runs/" )
        while i >= 0:
            if str( leaf )[ i + 6 : ] in rels:
                out.append( leaf )
                break
            i = str( leaf ).find( "/runs/", i + 1 )
    return out


def _selected( req: dict, busy: set ) -> list:
    """the leaves under the tree nodes `req[ "nodes" ]`, among every run this machine noted"""
    nodes = [ str( n ) for n in req.get( "nodes" ) or [ ] ]
    if not nodes:
        return [ ]
    from ..tui import runtree as T
    from . import seen as S
    runs = S.runs( 1 << 30 ).get( "runs", [ ] )
    tree = T.build( [ ( "", r, r.get( "leaf" ) in busy ) for r in runs ] )
    under, seen_ = [ ], set()
    for n in nodes:
        node = T.find( tree, n )
        for x in T.all_runs( node ) if node is not None else [ ]:
            if x[ 1 ].get( "leaf" ) not in seen_:
                seen_.add( x[ 1 ].get( "leaf" ) )
                under.append( x )
    going = T.keep_latest( under ) if req.get( "how" ) == "latest" else [ x for x in under if not x[ 2 ] ]
    return [ x[ 1 ][ "leaf" ] for x in going ]


def _sizes( leaves: list, slow ) -> dict:
    """bytes under each leaf: `du -sk` for all of them at once where there is one ( a walk in Python is ten times
    slower on runs of many files ), the walk otherwise"""
    import shutil as _sh
    import subprocess
    out = { }
    du = _sh.which( "du" )
    for at in range( 0, len( leaves ), 200 ):
        chunk = leaves[ at : at + 200 ]
        if du:
            try:
                got = subprocess.run( [ du, "-sk", *chunk ], capture_output = True, text = True, timeout = 120 ).stdout
                for line in got.splitlines():
                    kb, _, path = line.partition( "\t" )
                    if path in chunk:
                        out[ path ] = int( kb ) * 1024
                continue
            except ( OSError, ValueError, subprocess.SubprocessError ):
                pass
        out.update( { l: slow( Path( l ) ) for l in chunk } )
    return out


def caches( req: dict ) -> dict:
    """`caches`: { days, entries: [ names ], purge: { dry_run, unused_days }, guests } -> { host, dirs, guests }.
    `caches_remove`: { id, cache, keys | rule, days, guest } -> { removed, freed, entries, size }. A `guest` ( a VM
    of this machine ) is asked over its ssh, as `table` asks it."""
    from .. import caches as C
    if req.get( "guest" ):
        from .table import guest_caches, vms
        vm = next( ( v for v in vms( _cache() ) if v[ "name" ] == req[ "guest" ] ), None )
        if vm is None:
            return { "error": f"no VM {req[ 'guest' ]!r} here" }
        return guest_caches( vm, { k: v for k, v in req.items() if k != "guest" } )
    if req.get( "op" ) == "caches_hold":
        return { "ok": True, "held": [ list( h ) for h in C.hold( req.get( "id" ) ) ], "host": socket.gethostname() }
    if req.get( "op" ) == "caches_remove":
        how = { "keys": req.get( "keys" ), "rule": req.get( "rule" ), "dry_run": bool( req.get( "dry_run" ) ) }
        if req.get( "days" ) is not None:
            how[ "days" ] = float( req[ "days" ] )
        return { "ok": True, **C.remove_in( str( req.get( "id" ) or "" ), str( req.get( "cache" ) or "" ), **how ) }
    got = C.report( days = float( req.get( "days" ) or C.UNUSED_DAYS ), entries = req.get( "entries" ) or ( ),
                    purge_with = req.get( "purge" ) )
    guests = [ ]
    if req.get( "guests", True ):
        from .table import guest_caches, vms
        for vm in vms( _cache() ):
            if vm[ "state" ] == "ready" and vm.get( "port" ) and vm.get( "image" ):
                guests.append( { "vm": vm[ "name" ], **guest_caches( vm, { **req, "guests": False } ) } )
    return { "ok": True, **got, "guests": guests }


def _cache( ) -> Path:
    from .. import bootstrap
    return bootstrap.local_cache()


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
    The escalation goes on in a thread: the answer is that it started. With `wait` ( `errand stop`: a
    command that leaves, with no agent's thread to finish it ), it is done first: `gone` says it ended."""
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

    if req.get( "wait" ):
        escalate()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and P._killpg( pgid, 0 ):
            time.sleep( 0.05 )
        return { "ok": True, "pid": os.getpid(), "gone": not P._killpg( pgid, 0 ) }
    threading.Thread( target = escalate, daemon = True ).start()
    return { "ok": True, "pid": os.getpid() }


# ── a subscription ───────────────────────────────────────────────────────────

import json as _json

SWEEP     = 60.0         # seconds between two looks at everything, whatever was said ( ADR 0024 )
MEASURE   = 5.0          # seconds between two measures of the resources, while a watcher asks for them
HEARTBEAT = 30.0         # an event at least this often: the watcher knows the agent is there
QUICK     = 0.5          # where there is no bell ( Windows ): seconds between two looks at the directories' dates
OUTPUT    = 0.5          # at most one output notice a process this often
BELL      = "bell"       # a named pipe in a host agent's directory: what changes rings it ( `ring` )

_watching: set = set()               # the subscriptions of this agent, each with its own wake
_bell_reader = [ None ]


def nudge( outputs = ( ) ):
    """Something changed here that this agent knows of ( a process it started, or that ended; a run that noted itself;
    `outputs`: the processes that wrote ): every watcher looks now. And the host agents of this machine, which other
    processes are: their bell is rung ( `ring` )."""
    for w in list( _watching ):
        w.outputs.update( outputs )
        w.poke.set()


def ring( outputs = ( ) ):
    """Every host agent's bell on this machine rung: a byte, or `o <id>` a process that wrote. Never waits, never fails:
    a bell nobody listens to ( no agent, an older one, Windows ) is no bell."""
    from .. import bootstrap
    if not hasattr( os, "mkfifo" ):
        return
    data = "".join( f"o {o}\n" for o in outputs ).encode() or b".\n"
    for d in ( bootstrap.local_cache() / "agents" ).glob( "host-*" ):
        try:
            fd = os.open( str( d / BELL ), os.O_WRONLY | os.O_NONBLOCK )
        except OSError:
            continue
        try:
            os.write( fd, data )
        except OSError:
            pass
        finally:
            os.close( fd )


def listen( root ) -> bool:
    """This agent's bell, made and listened to from a thread ( once ): what rings it wakes every watcher. -> whether
    there is one ( not on Windows: the directories' dates are looked at instead )."""
    if _bell_reader[ 0 ] is not None:
        return _bell_reader[ 0 ]
    if not hasattr( os, "mkfifo" ):
        _bell_reader[ 0 ] = False
        return False
    import select
    import stat
    path = Path( root ) / BELL
    try:
        if path.exists() and not stat.S_ISFIFO( path.stat().st_mode ):
            path.unlink()
        if not path.exists():
            os.mkfifo( str( path ), 0o600 )
        fd = os.open( str( path ), os.O_RDWR | os.O_NONBLOCK )       # ( read-write: never at its end, nobody writing )
    except OSError:
        _bell_reader[ 0 ] = False
        return False

    def run():
        held = b""
        while True:
            select.select( [ fd ], [ ], [ ] )
            try:
                held += os.read( fd, 65536 )
            except BlockingIOError:
                continue
            lines, _, held = held.rpartition( b"\n" )
            outs = [ l[ 2 : ].decode( errors = "replace" ) for l in lines.split( b"\n" ) if l.startswith( b"o " ) ]
            nudge( outs )
    threading.Thread( target = run, daemon = True ).start()
    _bell_reader[ 0 ] = True
    return True


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
    """A watcher's subscription ( `op: watch` ), on its channel ( ADR 0024 ): a full state first -- `{"table": …}`,
    `{"seen": …}` --, then what changes as it changes: the table when it differs, the history as a delta
    `{"runs": {"put": [ … ], "drop": [ leaves ]}}`, `{"output": [ process ids ]}` when processes wrote, `{"resources": …}`
    while the watcher asks for them ( it writes `{"resources": true}` on its channel ) and they moved. Between two
    things to say, nothing runs: it waits for its agent's pokes and bell, sweeps everything every `SWEEP` seconds, and
    says it is alive every `HEARTBEAT`. Over when the watcher closes the channel or goes."""

    def __init__( self, writer, channel, req: dict, root = None ):
        self.writer, self.channel, self.req = writer, channel, req
        self.root = root
        self.stopped = threading.Event()
        self.poke = threading.Event()
        self.outputs: set = set()
        self.resources = bool( req.get( "resources" ) )
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
        limit = int( self.req.get( "limit" ) or 1000 )
        belled = listen( self.root ) if self.root is not None else False
        shape = res = marks = None
        runs: dict | None = None            # leaf -> its record as last said
        measured = None
        swept_at = sent_at = measured_at = 0.0
        look = True
        while not self.stopped.is_set():
            now = time.time()
            if self.resources and now - measured_at >= MEASURE:
                measured_at, measured = now, T._resources()
                if _rounded( measured ) != res:
                    res = _rounded( measured )
                    if not self._send( { "resources": measured, "time": now } ):
                        return
                    sent_at = now
            if not belled:                  # no bell here: the dates of the directories say something moved
                m = _marks()
                if m != marks:
                    marks, look = m, True
            if look or now - swept_at >= SWEEP:
                if now - swept_at >= SWEEP:
                    swept_at = now
                look = False
                got = T.scan( guests = guests, resources = False )
                if _shape( got ) != shape:
                    shape = _shape( got )
                    if not self._send( { "table": { **got, "resources": measured } } ):
                        return
                    sent_at = now
                hist = seen.runs( limit )
                now_runs = { r[ "leaf" ]: r for r in hist[ "runs" ] }
                if runs is None:
                    ok = self._send( { "seen": hist } )
                else:
                    put = [ r for l, r in now_runs.items() if runs.get( l ) != r ]
                    drop = [ l for l in runs if l not in now_runs ]
                    ok = self._send( { "runs": { "put": put, "drop": drop, "more": hist.get( "more", 0 ) } } ) if put or drop else True
                    if put or drop:
                        sent_at = now
                if not ok:
                    return
                runs = now_runs
            if self.outputs:
                outs, self.outputs = sorted( self.outputs ), set()
                if not self._send( { "output": outs } ):
                    return
                sent_at = now
            if now - sent_at >= HEARTBEAT:
                if not self._send( { "alive": now } ):
                    return
                sent_at = now
            waits = [ swept_at + SWEEP - now, sent_at + HEARTBEAT - now ]
            if self.resources:
                waits.append( measured_at + MEASURE - now )
            if not belled:
                waits.append( QUICK )
            if self.poke.wait( max( 0.05, min( waits ) ) ):
                self.poke.clear()
                look = True                 # something this agent knows of changed: looked at now
        _watching.discard( self )

    def write( self, data ):
        """what the watcher says on its channel: `{"resources": true | false}`"""
        try:
            said = _json.loads( data )
        except ( ValueError, TypeError ):
            return
        if isinstance( said, dict ) and "resources" in said:
            self.resources = bool( said[ "resources" ] )
            self.poke.set()

    def detach( self, writer = None, channel = None ):
        self.stopped.set()
        self.poke.set()
        _watching.discard( self )

    def close_input( self ): pass
    def stop( self ): self.detach()
    def signal( self, sig ): pass
    def resize( self, cols, rows ): pass
