"""A push by manifest, through the agent that holds the copy ( ADR 0006 ): both sides of it.

    push( conn, local_root, remote_root, sel )   here: the local side decides
    Session                                      over there: the agent applies, on one channel

The local side opens `{ "op": "sync", "root", "sel", "codecs" }`. Then messages cross on the channel,
each one frame ( IN toward the agent, OUT back ): `J` and JSON, or `C` and a chunk of a file
( `sync.pack` ).

    <- { "dst": manifest, "findings", "ci" }       what the copy holds, what changed there, its case
    -> { "hash": [ keys ] }                        <- { "digests": { key: digest } }
    -> { "apply": { "delete", "dirs", "links" } }  <- { "deleted", "kept": [ [ key, zone ] ] }
    -> { "file": key }, C..., { "end": entry, "stable" }   ( { "restart" } if read again )
    -> { "touch": [ [ key, entry ] ] }
    -> { "done" }                                  <- { "saved" }, then EXIT

The copy's trusted manifest lives IN the copy ( `.errand-copy` ), not in the agent's directory:
two machines that see the same file system reach the same copy, and know it. Whoever wrote the
manifest last was errand, from here or from there: it is trusted alike. A lock beside it
( `.errand-copy.lock` ) keeps two pushes from writing the copy at once.

The agent walks a copy in full the first time it syncs it in its life, and once more when it goes
( `closing` ): the check of ADR 0006. In between, it trusts the manifest.
"""
from __future__ import annotations

import errno
import json
import os
import queue
import threading
import time
from pathlib import Path

from .. import sync as S
from . import frames as F


TRUSTED = S.COPY_STATE                 # in the copy's root
LOCK    = S.COPY_STATE + ".lock"
STALE_LOCK = 1800.0                    # a lock older than this was left by a push that died

_held : dict = { }                     # root -> ( generation, Selection ): what this agent has synced in its life
_held_lock = threading.Lock()


def selection_to_wire( sel: S.Selection ) -> dict:
    return { "excludes": list( sel.excludes ), "follow_links": sel.follow_links,
             "zones": [ list( z ) for z in sel.zones ] }


def selection_from_wire( d: dict ) -> S.Selection:
    return S.Selection( list( d.get( "excludes", [ ] ) ), bool( d.get( "follow_links" ) ),
                        [ S.Zone( *z ) for z in d.get( "zones", [ ] ) ] )


def _root( path: str ) -> Path:
    p = Path( os.path.expanduser( path ) )
    p = p if p.is_absolute() else Path.home() / p           # as ssh's `cd` reads it: from the home folder
    if os.name == "nt" and not str( p ).startswith( "\\\\" ):
        # Extended-length: what a run writes deep in a copy ( a run directory named after a test ) is often past
        # Windows' 260 characters, which every call under this root then gets past too.
        p = Path( "\\\\?\\" + os.path.abspath( str( p ) ) )
    return p


# -- over there -----------------------------------------------------------------

class _Locked:
    def __init__( self, root: Path ):
        self.path = root / LOCK

    def __enter__( self ):
        waited = time.monotonic()
        while True:
            try:
                os.mkdir( self.path )          # atomic, NFS and Lustre included
                return self
            except OSError as err:
                if err.errno != errno.EEXIST:
                    raise
            try:
                if time.time() - self.path.stat().st_mtime > STALE_LOCK:
                    os.rmdir( self.path )
                    continue
            except OSError:
                continue
            if time.monotonic() - waited > STALE_LOCK:
                raise S.SyncError( f"{self.path} is held by another push" )
            time.sleep( 0.2 )

    def __exit__( self, *_ ):
        try:
            os.rmdir( self.path )
        except OSError:
            pass


class _Channel:
    """The agent's side of one transfer: in the agent's process, on the channel it was opened on.
    It looks to the agent like a process ( `Agent.serve_client` hands it what comes on its channel )."""

    code = None

    def __init__( self, writer, channel: int, req: dict ):
        self.writer, self.channel, self.req = writer, channel, req
        self.inbox = queue.Queue( maxsize = 64 )        # a full one holds the stream back: the disk sets the pace
        threading.Thread( target = self._run, daemon = True ).start()

    # what the agent hands it
    def write( self, payload: bytes ):
        self.inbox.put( payload )

    def close_input( self ):
        self.inbox.put( None )

    def detach( self, writer = None, channel = None ):
        self.inbox.put( None )

    def stop( self, *_ , **__ ):
        self.inbox.put( None )

    signal = stop

    def resize( self, *_ ):
        pass

    # the conversation
    def say( self, what: dict ):
        self.writer.send( self.channel, F.OUT, b"J" + json.dumps( what ).encode() )

    def get( self ):
        got = self.inbox.get()
        if got is None:
            raise S.SyncError( "the local side went away" )
        return got

    def get_json( self ) -> dict:
        got = self.get()
        if got[ : 1 ] != b"J":
            raise S.SyncError( "expected a message, got a chunk" )
        return json.loads( got[ 1 : ] )

    def _run( self ):
        code = 0
        try:
            self.writer.send( self.channel, F.REPLY, { "ok": True, "codecs": S.codecs() } )
            self._sync()
        except Exception as err:
            code = 1
            try:
                self.say( { "error": f"{type( err ).__name__}: {err}" } )
            except OSError:
                pass
        try:
            self.writer.send( self.channel, F.EXIT, { "code": code } )
        except OSError:
            pass

    def _sync( self ):
        raise NotImplementedError


class Session( _Channel ):
    """A push: the copy here brought in line with the project over there."""

    def _sync( self ):
        root = _root( self.req[ "root" ] )
        sel = selection_from_wire( self.req.get( "sel" ) or { } )
        root.mkdir( parents = True, exist_ok = True )
        with _Locked( root ):
            known = S.load( root / TRUSTED )
            with _held_lock:
                first = str( root ) not in _held
            dst, findings = _seen( root, sel, known, check = first or bool( self.req.get( "check" ) ) )
            self.say( { "dst": { k: list( e ) for k, e in dst.items() },
                        "findings": [ list( f ) for f in findings ], "ci": S.case_insensitive( root ) } )
            w = S.Writer( root, dst )
            written = S.Manifest( dst )
            written.real = dict( dst.real )
            handle = None
            while True:
                got = self.get()
                if got[ : 1 ] == b"C":
                    w.write( handle, S.unpack( got[ 1 : ] ) )
                    continue
                msg = json.loads( got[ 1 : ] )
                if "hash" in msg:
                    out = { }
                    for key in msg[ "hash" ]:
                        try:
                            out[ key ] = S.hash_file( w.path( key ) )
                        except OSError:
                            out[ key ] = ""
                    self.say( { "digests": out } )
                elif "apply" in msg:
                    a = msg[ "apply" ]
                    deleted, kept = [ ], [ ]
                    for key in a[ "delete" ]:
                        if w.delete( key ):
                            deleted.append( key )
                            written.pop( key, None )
                            written.real.pop( key, None )
                        else:
                            held = S._held( sel, key, w.path( key ) )
                            kept.append( [ key, str( held ) if held is not None and held.kind != "errand" else "" ] )
                    for key in a[ "dirs" ]:
                        w.mkdir( key )
                        written[ key ] = S.Entry( "d" )
                    for key, target in a[ "links" ]:
                        w.link( key, target )
                        written[ key ] = S.Entry( "l", target = target )
                    self.say( { "deleted": deleted, "kept": kept } )
                elif "file" in msg:
                    key = msg[ "file" ]
                    handle = w.begin( key )
                elif "restart" in msg:
                    w.restart( handle )
                elif "end" in msg:
                    entry = S.Entry( *msg[ "end" ] )
                    w.commit( handle, entry )
                    written[ msg[ "key" ] ] = entry
                    handle = None
                elif "touch" in msg:
                    for key, e in msg[ "touch" ]:
                        entry = S.Entry( *e )
                        w.touch( key, entry )
                        written[ key ] = entry
                elif "done" in msg:
                    break
            if handle is not None:
                w.abort( handle )
            written.generation = os.urandom( 8 ).hex()
            S.save( root / TRUSTED, written )
            with _held_lock:
                _held[ str( root ) ] = sel
            self.say( { "saved": True } )


class Pull( _Channel ):
    """A pull: what is under some paths of the copy, toward the project over there. It deletes
    nothing there: what the local side has and this one has not stays."""

    def _sync( self ):
        root = _root( self.req[ "root" ] )
        sel = selection_from_wire( self.req.get( "sel" ) or { } )
        src, missing = _under( root, self.req[ "paths" ], sel )
        self.say( { "src": { k: list( e ) for k, e in src.items() }, "missing": missing } )
        accepted = [ c for c in self.req.get( "codecs", [ "-" ] ) if c in S.codecs() ]
        while True:
            msg = self.get_json()
            if "hash" in msg:
                out = { }
                for key in msg[ "hash" ]:
                    try:
                        out[ key ] = S.hash_file( root / src.on_disk( key ) )
                    except OSError:
                        out[ key ] = ""
                self.say( { "digests": out } )
            elif "want" in msg:
                for key in msg[ "want" ]:
                    self.say( { "file": key } )
                    try:
                        entry, stable = S.read_into(
                            root, src, key,
                            lambda b: self.writer.send( self.channel, F.OUT, b"C" + S.pack( b, accepted ) ),
                            lambda: self.say( { "restart": True } ) )
                    except FileNotFoundError:
                        self.say( { "gone": key } )        # removed by the run since it was listed
                        continue
                    self.say( { "end": list( entry ), "key": key, "stable": stable } )
                self.say( { "done": True } )
                return


def _under( root: Path, paths, sel: S.Selection ):
    """The manifest of what is under each of `paths` in `root`, keyed from `root`; the paths that
    are not there."""
    out, missing = S.Manifest(), [ ]
    for path in paths:
        path = path.strip( "/" )
        here = root / path
        if not here.exists() and not here.is_symlink():
            missing.append( path )
            continue
        if not here.is_dir() or here.is_symlink():
            st = here.lstat()
            out[ path ] = S.Entry( "l", target = os.readlink( here ) ) if here.is_symlink() else \
                          S.Entry( "f", st.st_size, st.st_mtime_ns, bool( st.st_mode & 0o100 ) )
            continue
        parts = path.split( "/" )
        for i in range( 1, len( parts ) + 1 ):                # the directories that lead there
            out[ "/".join( parts[ : i ] ) ] = S.Entry( "d" )
        sub = S.scan( here, sel, hashing = False )
        for k, e in sub.items():
            out[ f"{path}/{k}" ] = e
        out.real.update( { f"{path}/{k}": f"{path}/{v}" for k, v in sub.real.items() } )
    return out, missing


def _seen( root: Path, sel: S.Selection, known, check: bool ):
    """What the copy holds -- walked, or as the trusted manifest and its pending findings say -- and
    what changed there behind errand's back."""
    if known is None or check:
        dst = S.scan( root, sel, known, hashing = False )
        if known is None:
            return dst, [ ]
        first = { f.key: f for f, _ in known.found }        # a check saw it first: its time is the one
        return dst, [ first.get( f.key, f ) for f in S.compare( known, dst ) ]
    dst = S.Manifest( known )
    dst.real = dict( known.real )
    for f, e in known.found:
        if e is None:
            dst.pop( f.key, None )
        else:
            dst[ f.key ] = e._replace( digest = "" ) if e.kind == "f" else e
    return dst, [ f for f, _ in known.found ]


def closing( ):
    """The agent goes: each copy it synced is checked once more, and what changed there since is
    kept for the next push to say ( `sync.check` )."""
    with _held_lock:
        held = dict( _held )
        _held.clear()
    for root, sel in held.items():
        try:
            with _Locked( Path( root ) ):
                S.check( root, sel, Path( root ) / TRUSTED )
        except Exception:
            pass


def serve( agent, writer, channels, channel, req ):
    """`op: sync` or `op: pull` on an agent: the session takes the channel."""
    channels[ channel ] = ( Pull if req.get( "op" ) == "pull" else Session )( writer, channel, req )


# -- here -----------------------------------------------------------------------

class _Call:
    """The local side's end of the channel: messages in, messages and chunks out."""

    def __init__( self, call ):
        self.call = call

    def send( self, what ):
        self.call.send( F.IN, b"J" + json.dumps( what ).encode() if isinstance( what, dict ) else what )

    def get( self, timeout = 600.0 ) -> dict:
        while True:
            kind, payload = self.call.next( timeout )
            if kind == F.OUT and payload[ : 1 ] == b"J":
                msg = json.loads( payload[ 1 : ] )
                if "error" in msg:
                    raise S.SyncError( f"over there: {msg[ 'error' ]}" )
                return msg
            if kind == F.EXIT:
                raise S.SyncError( "the agent ended the sync early" )

    def get_message( self, timeout = 600.0 ):
        """The next message, or a chunk's bytes."""
        kind, payload = self.call.next( timeout )
        if kind == F.EXIT:
            raise S.SyncError( "the agent ended the transfer early" )
        if kind != F.OUT:
            return None
        if payload[ : 1 ] == b"C":
            return payload[ 1 : ]
        msg = json.loads( payload[ 1 : ] )
        if "error" in msg:
            raise S.SyncError( f"over there: {msg[ 'error' ]}" )
        return msg


def push( conn, local_root, remote_root, sel: S.Selection, *, src_cache = None, where = "the copy",
          say = print, check = False ) -> S.Report:
    """`remote_root`, over there where `conn` leads, in line with `local_root` here."""
    local_root = Path( local_root )
    report = S.Report()
    call = conn.open( { "op": "sync", "root": str( remote_root ), "sel": selection_to_wire( sel ),
                        "check": check } )
    try:
        theirs = call.reply( timeout = 120.0 )
        accepted = [ c for c in theirs.get( "codecs", [ "-" ] ) if c in S.codecs() ]
        c = _Call( call )
        src = S.scan( local_root, sel, S.load( src_cache ) if src_cache else None )
        if src_cache:
            S.save( src_cache, src )
        got = c.get()
        dst = S.Manifest( ( k, S.Entry( *v ) ) for k, v in got[ "dst" ].items() )
        report.findings = [ S.Finding( *f ) for f in got[ "findings" ] ]
        S.say_findings( report.findings, where, say, sel )
        if got[ "ci" ]:
            clash = S.collisions( src )
            if clash:
                raise S.SyncError( "names that are one on " + where + " ( it does not tell case apart ): "
                                   + "; ".join( " / ".join( x ) for x in clash ) )
        ask = [ k for k, s in src.items() if s.kind == "f" and k in dst and dst[ k ].kind == "f"
                and not s.same( dst[ k ] ) and not dst[ k ].digest and dst[ k ].size == s.size ]
        digests = { }
        if ask:
            c.send( { "hash": ask } )
            digests = c.get()[ "digests" ]
        p = S.plan( src, dst, lambda k: digests.get( k, "" ) )
        c.send( { "apply": { "delete": p.delete, "dirs": p.dirs,
                             "links": [ [ k, src[ k ].target ] for k in p.links ] } } )
        applied = c.get()
        report.deleted = [ k for k in applied[ "deleted" ] if k not in src ]
        report.kept = [ k for k, _ in applied[ "kept" ] ]
        for key, zone in applied[ "kept" ]:
            if zone and key not in src:
                say( f"  {key}: left on {where}, it holds {zone}" )
        for key in p.send:
            c.send( { "file": key } )
            entry, stable = S.read_into( local_root, src, key, lambda b: c.send( b"C" + S.pack( b, accepted ) ),
                                         lambda: c.send( { "restart": True } ) )
            c.send( { "end": list( entry ), "key": key } )
            report.sent.append( key )
            report.bytes += entry.size
            if not stable:
                report.unstable.append( key )
                say( f"  {key}: changed while it was read, twice -- what was read is on {where}" )
        if p.touch:
            c.send( { "touch": [ [ k, list( src[ k ] ) ] for k in p.touch ] } )
            report.touched = list( p.touch )
        c.send( { "done": True } )
        c.get()
    finally:
        call.close()
    return report


def pull( conn, remote_root, local_root, paths, *, sel: S.Selection | None = None, where = "the copy",
          say = print, links = True ) -> S.Report:
    """What is under `paths` in `remote_root` over there, into `local_root` here. Nothing here is
    deleted. Without `links` ( a Windows without its developer mode ), a link is left over there."""
    local_root = Path( local_root )
    sel = sel or S.Selection()
    report = S.Report()
    call = conn.open( { "op": "pull", "root": str( remote_root ), "paths": list( paths ),
                        "sel": selection_to_wire( sel ), "codecs": S.codecs() } )
    try:
        call.reply( timeout = 120.0 )
        c = _Call( call )
        got = c.get()
        src = S.Manifest( ( k, S.Entry( *v ) ) for k, v in got[ "src" ].items() )
        if not links:
            src = S.Manifest( ( k, e ) for k, e in src.items() if e.kind != "l" )
        here, _ = _under( local_root, [ p for p in paths if p.strip( "/" ) not in got[ "missing" ] ], sel )
        same_size = [ k for k, s in src.items() if s.kind == "f" and k in here and here[ k ].kind == "f"
                      and not s.same( here[ k ] ) and here[ k ].size == s.size ]
        theirs = { }
        if same_size:
            c.send( { "hash": same_size } )
            theirs = c.get()[ "digests" ]
        w = S.Writer( local_root, here )
        p = S.plan( S.Manifest( ( k, e._replace( digest = theirs.get( k, "" ) ) ) for k, e in src.items() ),
                    here, lambda k: S.hash_file( w.path( k ) ) if k in theirs else "" )
        for key in p.delete:                       # only what changed kind: nothing here is removed
            if key in src and not w.delete( key ):
                say( f"  {key}: a directory here, something else over there -- left as it is" )
                src.pop( key, None )
                p.send = [ k for k in p.send if k != key ]
        for key in p.dirs:
            if key in src:
                w.mkdir( key )
        for key in p.links:
            w.link( key, src[ key ].target )
        for key in p.touch:
            w.touch( key, src[ key ] )
            report.touched.append( key )
        c.send( { "want": p.send } )
        handle = None
        while True:
            msg = c.get_message()
            if msg is None:
                continue
            if isinstance( msg, bytes ):
                w.write( handle, S.unpack( msg ) )
            elif "file" in msg:
                handle = w.begin( msg[ "file" ] )
            elif "restart" in msg:
                w.restart( handle )
            elif "gone" in msg:
                w.abort( handle )
                handle = None
            elif "end" in msg:
                entry = S.Entry( *msg[ "end" ] )
                w.commit( handle, entry )
                handle = None
                report.sent.append( msg[ "key" ] )
                report.bytes += entry.size
                if not msg[ "stable" ]:
                    report.unstable.append( msg[ "key" ] )
                    say( f"  {msg[ 'key' ]}: still being written on {where} -- what was read is here" )
            elif "done" in msg:
                break
        if handle is not None:
            w.abort( handle )
    finally:
        call.close()
    return report
