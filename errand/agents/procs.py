"""The processes an agent starts: their output kept on disk, streamed to whoever listens.

Each process has a directory of its own, `<agent dir>/proc/<id>/`:

    meta.json   what was started, when, and whether it may outlive its client
    out, err    everything it wrote, as it wrote it
    exit        its exit code, once there is one

The files are the truth; a channel only streams them. So a client that went
away -- a laptop closed, a network dropped -- comes back and `attach`es from the
offsets it had reached, and misses nothing.
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
    def __init__( self, root: Path, argv, env = None, cwd = None, keep = False, pid = None, tty = None ):
        self.id   = pid or uuid.uuid4().hex[ : 16 ]
        self.dir  = root / "proc" / self.id
        self.keep = keep
        self.listeners = [ ]            # ( Writer, channel )
        self.lock = threading.Lock()
        self.code = None
        self.dir.mkdir( parents = True, exist_ok = True )
        ( self.dir / "meta.json" ).write_text( json.dumps(
            { "argv": list( argv ), "cwd": cwd, "keep": keep, "tty": bool( tty ), "started": time.time() } ) )
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
            self.listeners.clear()

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


def finished( root: Path ) -> list:
    """The processes of an earlier life of this agent, from their directories: what `list` adds."""
    out = [ ]
    for d in sorted( ( root / "proc" ).glob( "*" ) ) if ( root / "proc" ).is_dir() else [ ]:
        try:
            meta = json.loads( ( d / "meta.json" ).read_text() )
        except ( OSError, ValueError ):
            continue
        code = ( d / "exit" ).read_text().strip() if ( d / "exit" ).exists() else None
        out.append( { "id": d.name, "argv": meta.get( "argv" ), "started": meta.get( "started" ),
                      "code": int( code ) if code not in ( None, "" ) else None } )
    return out


def sweep( root: Path ):
    """Directories of processes long finished go."""
    limit = time.time() - KEEP_DAYS * 86400
    for d in ( root / "proc" ).glob( "*" ) if ( root / "proc" ).is_dir() else [ ]:
        if ( d / "exit" ).exists() and ( d / "exit" ).stat().st_mtime < limit:
            shutil.rmtree( d, ignore_errors = True )
