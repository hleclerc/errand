"""The processes an agent starts: their output kept on disk, streamed to whoever listens.

Each process has a directory of its own:

    meta.json   what was started, when, and whether it may outlive its client; its process
                group and the start time of its leader ( `owned` ), once it runs
    out, err    everything it wrote, as it wrote it
    exit        its exit code, once there is one

The files are the truth; a channel only streams them. So a client that went
away -- a laptop closed, a network dropped -- comes back and `attach`es from the
offsets it had reached, and misses nothing.

The agent's own directory is shared by every project and holds only what is
live: `proc/<id>/` while the process runs. A marker whose group still runs while no agent
serves the directory is an orphan: the agent died ( SIGKILL, the OOM killer ). Whoever finds it
next kills it ( `kill_orphans`, ADR 0008 ): its output went through the dead agent's pipes, so
nobody can follow it any more, and nothing errand started runs unowned. What accumulates goes where the
client said ( `store`: the project's `errand-outputs/state/procs/` over there ), and the
marker only says where ( `where` ). The output goes once its end was delivered:
nobody needs it any more. Not delivered -- the client went -- it stays, in the
project, for `errand attach`; and a process that may not outlive its client
( `keep` false ) leaves nothing at all.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import signal
import threading
import time
import uuid
from pathlib import Path

from . import frames as F, spawn
from .frames import GRACE


KEEP_DAYS = 7          # finished processes' directories are removed after this
WINDOWS   = sys.platform == "win32"
SIGKILL   = getattr( signal, "SIGKILL", 9 )   # not in `signal` on Windows: there, any stop but Ctrl-C ends the job


class Proc:
    def __init__( self, root: Path, argv, env = None, cwd = None, keep = False, pid = None, tty = None,
                  store = None ):
        self.id   = pid or uuid.uuid4().hex[ : 16 ]
        self.mark = root / "proc" / self.id                      # live: here while it runs
        self.dir  = Path( store ) / self.id if store else self.mark
        self.keep = keep
        self.listeners = [ ]            # ( Writer, channel )
        self.lock = threading.Lock()
        self.code = None
        self.stopping = False
        meta = { "argv": list( argv ), "cwd": cwd, "keep": keep, "tty": bool( tty ), "started": time.time() }
        for d in { self.mark, self.dir }:
            d.mkdir( parents = True, exist_ok = True )
            ( d / "meta.json" ).write_text( json.dumps( meta ) )
        if self.dir != self.mark:
            ( self.mark / "where" ).write_text( str( self.dir ) )
        # Where it can leave its owner a word ( ADR 0009 ): `cancel`, a shell line run when it is
        # stopped ( a job that a kill of its process group would not reach ), and `waiting`, what
        # it waits for ( `arrival` ).
        env = { **( env or { } ), "ERRAND_PROC_DIR": str( self.mark ) }
        self.child = spawn.start( argv, env, cwd, tty )
        # Who it is, for whoever finds the marker once this agent is gone: the group it leads
        # ( a session of its own, `spawn` ), and when it started -- a pid reused is not it.
        # Its pid everywhere ( `table` says whether it still runs ); its project's records, when given.
        meta.update( pid = self.child.pid, store = str( store ) if store else None )
        if not WINDOWS:
            meta.update( pgid = self.child.pid, since = started( self.child.pid ) )
        for d in { self.mark, self.dir }:
            ( d / "meta.json" ).write_text( json.dumps( meta ) )
        # Attached at least once: a process that ends before its client is attached ( `spawn` replies,
        # then attaches ) keeps its output for that client, rather than the client getting an exit alone.
        self.seen = False
        self._readers = [ threading.Thread( target = self._pump, args = ( read, name, F.OUT if name == "out" else F.ERR ),
                                            daemon = True ) for read, name in self.child.streams ]
        for t in self._readers:
            t.start()
        threading.Thread( target = self._wait, daemon = True ).start()

    # -- output -------------------------------------------------------------

    def _pump( self, read, name, kind ):
        with open( self.dir / name, "ab" ) as log:
            for chunk in iter( lambda: read( 65536 ), b"" ):
                with self.lock:
                    log.write( chunk )
                    log.flush()
                    self._tell( kind, chunk )
                self._wrote()

    def _wrote( self ):
        """it wrote: its watchers told ( `look`, ADR 0024 ), at most every `OUTPUT` seconds; what comes inside that
        window is told at its end"""
        from . import look
        now = time.monotonic()
        told = getattr( self, "_told_at", 0.0 )
        if now - told >= look.OUTPUT:
            self._told_at = now
            try:
                look.nudge( [ self.id ] )
                look.ring( [ self.id ] )
            except Exception:
                pass
        elif not getattr( self, "_later", False ):
            self._later = True

            def later():
                self._later = False
                self._wrote()
            threading.Timer( look.OUTPUT - ( now - told ) + 0.01, later ).start()

    def _tell( self, kind, payload ):
        for writer, channel in list( self.listeners ):
            try:
                writer.send( channel, kind, payload )
            except OSError:
                self.listeners.remove( ( writer, channel ) )

    def _wait( self ):
        code = self.child.wait()
        if self.stopping:
            cancel( self.mark )
            # Stopped, not ended: what the leader started and left behind in its group ( its job, on
            # Windows ) goes with it. Only then -- a leader that ends by itself may leave work it meant
            # to ( `nohup … &` ).
            self.child.end_tree()
        for t in self._readers:
            t.join()
        with self.lock:
            self.code = code
            ( self.dir / "exit" ).write_text( str( code ) )
            self._tell( F.EXIT, { "code": code } )
            delivered = bool( self.listeners )
            self.listeners.clear()
            if delivered or ( not self.keep and self.seen ):
                shutil.rmtree( self.dir, ignore_errors = True )
            if self.mark != self.dir:          # the same directory: kept above until its client is told
                shutil.rmtree( self.mark, ignore_errors = True )
        try:
            from . import look
            look.nudge()                       # its watchers see it end now
            look.ring()                        # and those of the host agents here ( ADR 0024 )
        except Exception:
            pass

    def attach( self, writer, channel, out = 0, err = 0 ):
        """Send what was written from these offsets on, then follow."""
        with self.lock:
            self.seen = True
            for name, kind, offset in ( ( "out", F.OUT, out ), ( "err", F.ERR, err ) ):
                path = self.dir / name
                if path.exists() and path.stat().st_size > offset:
                    with open( path, "rb" ) as f:
                        f.seek( offset )
                        writer.send( channel, kind, f.read() )
            if self.code is not None:
                writer.send( channel, F.EXIT, { "code": self.code } )
                if not self.keep:
                    shutil.rmtree( self.dir, ignore_errors = True )      # ended before this attach: told now
            else:
                self.listeners.append( ( writer, channel ) )

    def detach( self, writer, channel = None ):
        """A client is gone -- or, with `channel`, closed that channel only ( through a hub, the stream
        stays ). A process that may not outlive it goes with it: left running, a command started through
        `rsh` whose client went would wait for its input forever, and keep its agent from ever going."""
        with self.lock:
            self.listeners = [ l for l in self.listeners
                               if not ( l[ 0 ] is writer and ( channel is None or l[ 1 ] == channel ) ) ]
            orphan = not self.listeners
        if orphan and not self.keep and self.code is None:
            self.stop( first = signal.SIGTERM )

    # -- input and signals ----------------------------------------------------

    def write( self, data: bytes ):
        self.child.write( data )

    def close_input( self ):
        self.child.close_input()

    def resize( self, cols: int, rows: int ):
        self.child.resize( cols, rows )

    def signal( self, sig: int ):
        if sig in ( signal.SIGTERM, SIGKILL ):
            self.stopping = True
        self.child.signal( sig )

    def stop( self, first = None ):
        """Stopped, not asked: `first` to the whole group, then SIGTERM, then SIGKILL, for whatever is
        still there. Done here, by the owner, so that it happens whether the client stays or not."""
        if self.code is not None:
            return
        first = signal.SIGINT if first is None else first
        self.stopping = True
        self.child.signal( first )
        steps = [ ( after, sig ) for after, sig in zip( GRACE, ( signal.SIGTERM, SIGKILL ) )
                  if sig != first ]
        for after, sig in steps:
            t = threading.Timer( after, lambda sig = sig: self.code is None and self._escalate( sig ) )
            t.daemon = True
            t.start()

    def _escalate( self, sig ):
        # Its `cancel` comes last, never first: INT and TERM let it end as it means to ( a srun
        # cancels its own job ), and what is cancelled then is only what is left -- a job still
        # queued, an allocation a killed salloc would leave behind. Here, or once it has exited
        # ( `_wait` ), whichever comes first; it runs once.
        if sig == SIGKILL:
            cancel( self.mark )
        self.child.signal( sig )

    def wait_gone( self, timeout: float ) -> bool:
        deadline = time.monotonic() + timeout
        while self.code is None and time.monotonic() < deadline:
            time.sleep( 0.05 )
        return self.code is not None


def locate( root: Path, pid: str, store = None ) -> Path | None:
    """The directory holding what process `pid` wrote: in the client's `store`, or where the
    marker says, or the marker itself ( a process of an older client ). None when gone."""
    pid = str( pid )
    mark = root / "proc" / pid
    # A store named before errand-outputs/ ( `.errand/procs` ), since moved there.
    moved = str( store ).replace( "/.errand/procs", "/errand-outputs/state/procs" ) if store else None
    for d in ( Path( store ) / pid if store else None, Path( moved ) / pid if moved != store else None,
               Path( ( mark / "where" ).read_text().strip() ) if ( mark / "where" ).exists() else None, mark ):
        if d is not None and ( d / "meta.json" ).exists():
            return d
    return None


def describe( d: Path ) -> dict | None:
    try:
        meta = json.loads( ( d / "meta.json" ).read_text() )
        code = ( d / "exit" ).read_text().strip() if ( d / "exit" ).exists() else None
    except ( OSError, ValueError ):
        return None
    return { "id": d.name, "argv": meta.get( "argv" ), "started": meta.get( "started" ),
             "code": int( code ) if code not in ( None, "" ) else None }


def finished( root: Path, store = None, ids = ( ) ) -> list:
    """The processes this agent knows of, from their directories: those it runs, and those of `ids`
    the client stored in `store` -- what `list` says."""
    found = { }
    for m in sorted( ( root / "proc" ).glob( "*" ) ) if ( root / "proc" ).is_dir() else [ ]:
        d = locate( root, m.name )
        got = describe( d ) if d is not None else None
        if got:
            found[ m.name ] = got
    for pid in ids or ( ):
        d = locate( root, pid, store ) if str( pid ) not in found else None
        got = describe( d ) if d is not None else None
        if got:
            found[ str( pid ) ] = got
    return list( found.values() )


def sweep( root: Path ):
    """At the start of an agent, once it holds its directory, the markers of an earlier life: what
    still runs of them is killed ( `kill_orphans` ). What a client stored elsewhere stays there; what
    nobody may come back for goes now; a process kept for its client, with its output here, goes
    once finished long ago."""
    kill_orphans( root )
    limit = time.time() - KEEP_DAYS * 86400
    for d in ( root / "proc" ).glob( "*" ) if ( root / "proc" ).is_dir() else [ ]:
        try:
            keep = json.loads( ( d / "meta.json" ).read_text() ).get( "keep" )
        except ( OSError, ValueError ):
            keep = False
        old = ( d / "exit" ).exists() and ( d / "exit" ).stat().st_mtime < limit
        if ( d / "where" ).exists() or not keep or old:
            shutil.rmtree( d, ignore_errors = True )


# -- owning: who a process is, and the end of those nobody owns any more ----------

def started( pid: int ) -> str | None:
    """When `pid` started, as a token that differs for a pid reused: None when it is not there."""
    try:
        if sys.platform.startswith( "linux" ):
            with open( f"/proc/{int( pid )}/stat" ) as f:
                return f.read().rsplit( ")", 1 )[ 1 ].split()[ 19 ]      # field 22: starttime, in ticks
        got = subprocess.run( [ "ps", "-o", "lstart=", "-p", str( int( pid ) ) ], capture_output = True,
                              text = True, timeout = 10 )
        return got.stdout.strip() or None
    except ( OSError, IndexError, subprocess.SubprocessError ):
        return None


def _killpg( pgid: int, sig: int ) -> bool:
    try:
        os.killpg( int( pgid ), sig )
        return True
    except ( ProcessLookupError, PermissionError, OSError ):
        return False


def ours( pgid: int, since ) -> bool:
    """Is group `pgid` still the one that was recorded? A pid is not reused while a group of that id
    has members, so a live group is that one -- unless its leader is a newer process that made a
    group of its own after the old one was gone, which its start time tells."""
    if WINDOWS or not pgid or not _killpg( pgid, 0 ):
        return False
    now = started( pgid )
    return now is None or since is None or now == since


def end_group( pgid: int, since, grace = GRACE ) -> bool:
    """SIGTERM, then SIGKILL, to group `pgid` if it is still the recorded one -> whether it was."""
    if not ours( pgid, since ):
        return False
    _killpg( pgid, signal.SIGTERM )
    deadline = time.monotonic() + grace[ 1 ] - grace[ 0 ]
    while time.monotonic() < deadline and _killpg( pgid, 0 ):
        time.sleep( 0.1 )
    _killpg( pgid, SIGKILL )
    return True


def _recorded( root: Path ):
    """( marker, directory, meta ) of each process recorded under `root/proc` with no exit yet."""
    for m in ( root / "proc" ).glob( "*" ) if ( root / "proc" ).is_dir() else [ ]:
        d = locate( root, m.name ) or m
        try:
            meta = json.loads( ( d / "meta.json" ).read_text() )
        except ( OSError, ValueError ):
            continue
        if not ( d / "exit" ).exists() and meta.get( "pgid" ):
            yield m, d, meta


def running( root: Path ) -> list:
    """The ids of the processes recorded under `root` whose group still runs, without a lock: a
    question, never an answer to act on alone."""
    return [ m.name for m, _, meta in _recorded( root ) if ours( meta[ "pgid" ], meta.get( "since" ) ) ]


def cancel( mark: Path ):
    """What a process said must happen when it is stopped ( `cancel` in its marker, ADR 0009 ): run once, at
    the end of the stop -- once it has exited, or before its SIGKILL --, whoever stops it: its
    agent, or the next one, for an orphan."""
    word = mark / "cancel"
    try:
        line = word.read_text().strip()
        word.unlink()
    except OSError:
        return
    if line:
        try:
            subprocess.run( line, shell = True, stdin = subprocess.DEVNULL, stdout = subprocess.DEVNULL,
                            stderr = subprocess.DEVNULL, timeout = 60 )
        except ( OSError, subprocess.SubprocessError ):
            pass


def kill_orphans( root: Path ) -> list:
    """The groups recorded under `root/proc` that still run: their agent is gone ( the caller holds
    its lock ), so they go -> the ids of those killed. Their marker says so ( `exit`: -9 ), for
    `attach`, which then reports them stopped rather than lost."""
    killed = [ ]
    for m, d, meta in _recorded( root ):
        if end_group( meta[ "pgid" ], meta.get( "since" ) ):
            cancel( m )                    # after TERM and KILL: what they left ( a queued job )
            killed.append( m.name )
            try:
                ( d / "exit" ).write_text( str( -SIGKILL ) )
            except OSError:
                pass
    return killed
