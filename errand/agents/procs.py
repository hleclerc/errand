"""The processes an agent starts: their output kept on disk, streamed to whoever listens.

Each process has a directory of its own:

    meta.json   what was started, when, and whether it may outlive its client
    out, err    everything it wrote, as it wrote it
    exit        its exit code, once there is one

The files are the truth; a channel only streams them. So a client that went
away -- a laptop closed, a network dropped -- comes back and `attach`es from the
offsets it had reached, and misses nothing.

The agent's own directory is shared by every project and holds only what is
live: `proc/<id>/` while the process runs. What accumulates goes where the
client said ( `store`: the project's `errand-outputs/state/procs/` over there ), and the
marker only says where ( `where` ). The output goes once its end was delivered:
nobody needs it any more. Not delivered -- the client went -- it stays, in the
project, for `errand attach`; and a process that may not outlive its client
( `keep` false ) leaves nothing at all.
"""
from __future__ import annotations

import json
import shutil
import signal
import threading
import time
import uuid
from pathlib import Path

from . import frames as F, spawn


KEEP_DAYS = 7          # finished processes' directories are removed after this


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
        meta = json.dumps( { "argv": list( argv ), "cwd": cwd, "keep": keep, "tty": bool( tty ),
                             "started": time.time() } )
        for d in { self.mark, self.dir }:
            d.mkdir( parents = True, exist_ok = True )
            ( d / "meta.json" ).write_text( meta )
        if self.dir != self.mark:
            ( self.mark / "where" ).write_text( str( self.dir ) )
        self.child = spawn.start( argv, env, cwd, tty )
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

    def _tell( self, kind, payload ):
        for writer, channel in list( self.listeners ):
            try:
                writer.send( channel, kind, payload )
            except OSError:
                self.listeners.remove( ( writer, channel ) )

    def _wait( self ):
        code = self.child.wait()
        for t in self._readers:
            t.join()
        with self.lock:
            self.code = code
            ( self.dir / "exit" ).write_text( str( code ) )
            self._tell( F.EXIT, { "code": code } )
            delivered = bool( self.listeners )
            self.listeners.clear()
            if delivered or not self.keep:
                shutil.rmtree( self.dir, ignore_errors = True )
            shutil.rmtree( self.mark, ignore_errors = True )

    def attach( self, writer, channel, out = 0, err = 0 ):
        """Send what was written from these offsets on, then follow."""
        with self.lock:
            for name, kind, offset in ( ( "out", F.OUT, out ), ( "err", F.ERR, err ) ):
                path = self.dir / name
                if path.exists() and path.stat().st_size > offset:
                    with open( path, "rb" ) as f:
                        f.seek( offset )
                        writer.send( channel, kind, f.read() )
            if self.code is not None:
                writer.send( channel, F.EXIT, { "code": self.code } )
            else:
                self.listeners.append( ( writer, channel ) )

    def detach( self, writer, channel = None ):
        """A client is gone -- or, with `channel`, closed that channel only ( through a hub, the stream
        stays ). A process that may not outlive it goes with it: left running, an `rsync --server`
        whose client went would wait for its input forever, and keep its agent from ever going."""
        with self.lock:
            self.listeners = [ l for l in self.listeners
                               if not ( l[ 0 ] is writer and ( channel is None or l[ 1 ] == channel ) ) ]
            orphan = not self.listeners
        if orphan and not self.keep and self.code is None:
            self.signal( signal.SIGTERM )
            threading.Timer( 5.0, lambda: self.code is None and self.signal( signal.SIGKILL ) ).start()

    # -- input and signals ----------------------------------------------------

    def write( self, data: bytes ):
        self.child.write( data )

    def close_input( self ):
        self.child.close_input()

    def resize( self, cols: int, rows: int ):
        self.child.resize( cols, rows )

    def signal( self, sig: int ):
        self.child.signal( sig )


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
    """At the start of an agent, the markers of an earlier life: nothing of theirs runs any more.
    What a client stored elsewhere stays there; what nobody may come back for goes now; a process
    kept for its client, with its output here, goes once finished long ago."""
    limit = time.time() - KEEP_DAYS * 86400
    for d in ( root / "proc" ).glob( "*" ) if ( root / "proc" ).is_dir() else [ ]:
        try:
            keep = json.loads( ( d / "meta.json" ).read_text() ).get( "keep" )
        except ( OSError, ValueError ):
            keep = False
        old = ( d / "exit" ).exists() and ( d / "exit" ).stat().st_mtime < limit
        if ( d / "where" ).exists() or not keep or old:
            shutil.rmtree( d, ignore_errors = True )
