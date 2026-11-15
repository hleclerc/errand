"""Bringing a tree in line with another, by manifest ( ADR 0006 ): what the agents do instead of rsync.

Each step works on one side, so that over the protocol each agent does its own:

    scan( root, sel, cache )            the side's manifest: path -> Entry, hashes kept while size and mtime hold
    compare( trusted, found )           what changed on a side since the manifest it trusts was made
    plan( src, dst, hash_dst )          what the destination lacks, holds in another version, or holds beyond the source
    read_into( root, src, key, write )  a file's bytes, chunk by chunk, read again once if it changed meanwhile
    Writer                              the destination's side: a file written beside its target, then renamed

`sync( src_root, dst_root, sel )` puts them together for two directories of this machine.

Paths are posix, relative to the root, NFC: macOS writes NFD, and the two must name the same file.
What is kept of a file: its contents, its mtime, its executable bit. Links stay links, unless the
selection follows them ( toward Windows ). Directories are created and removed, empty ones too.
"""
from __future__ import annotations

import errno
import fnmatch
import hashlib
import json
import os
import stat
import unicodedata
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple


CHUNK = 1 << 20
COPY_STATE = ".errand-copy"      # at a copy's root: its trusted manifest ( `agents/syncop.py` ), never part of a sync


class SyncError( Exception ):
    pass


class Entry( NamedTuple ):
    kind    : str                # "f" a file, "l" a link, "d" a directory
    size    : int = 0
    mtime_ns: int = 0
    exe     : bool = False
    digest  : str = ""           # a file's contents ( blake2b ), "" until computed
    target  : str = ""           # what a link points to

    def same( self, other: "Entry" ) -> bool:
        """Equal without reading either: rsync's quick check, size and mtime."""
        if self.kind != other.kind:
            return False
        if self.kind == "f":
            return ( self.size, self.mtime_ns, self.exe ) == ( other.size, other.mtime_ns, other.exe )
        if self.kind == "l":
            return self.target == other.target
        return True


class Manifest( dict ):
    """path -> Entry. `real`: the name on disk, where it is not the path ( NFD on macOS )."""

    def __init__( self, *args, **kw ):
        super().__init__( *args, **kw )
        self.real : dict = { }
        self.found: list = [ ]       # [ ( Finding, Entry on disk or None ) ]: a check's, not yet said by a sync
        self.generation = ""         # changes each time a sync writes it

    def on_disk( self, key: str ) -> str:
        return self.real.get( key, key )


class Patterns:
    """Paths as rsync reads them: a name pattern matched against every component ( `__pycache__`,
    `*.pyc` ), a path anchored at the root ( `/torch.sif` ), or an inner path ( `pkg/build` ), which
    matches at any depth."""

    def __init__( self, patterns = ( ) ):
        self.patterns = list( patterns )
        free = [ p.strip( "/" ) for p in self.patterns if not p.startswith( "/" ) ]   # `build/`: `build`
        self._names    = [ p for p in free if "/" not in p ]
        self._inner    = [ p for p in free if "/" in p ]
        self._anchored = [ p.strip( "/" ) for p in self.patterns if p.startswith( "/" ) ]

    def match( self, key: str, name: str ) -> str | None:
        """The pattern `key` ( whose last component is `name` ) falls under, None if none."""
        for p in self._names:
            if fnmatch.fnmatchcase( name, p ):
                return p
        for p in self._anchored:
            if fnmatch.fnmatchcase( key, p ):
                return "/" + p
        for p in self._inner:
            if fnmatch.fnmatchcase( key, p ) or fnmatch.fnmatchcase( key, f"*/{p}" ):
                return p
        return None


# What a zone is for ( ADR 0006 ): the copy over there is errand's, except in its zones, where the
# other side writes. A push never sends into a zone, never deletes in one, and a change there is
# no finding.
ZONES = {
    "build" : "built over there",            # a layer's image or venv, a build directory
    "back"  : "written over there, brought back here",
    "errand": "errand's own records",       # errand-outputs/: each side keeps its own
}


class Zone( NamedTuple ):
    pattern: str
    kind   : str                 # one of ZONES

    def __str__( self ):
        return f"{self.pattern} ( {self.kind} zone )"


@dataclass
class Selection:
    """What a sync looks at, on both sides alike. What `excludes` names is not part of the copy:
    caches, a repository. What `zones` name is part of it, but the other side's ( see `ZONES` ).
    Both are neither sent nor deleted, and never found as a change; a zone is named in what is said."""
    excludes    : list = field( default_factory = list )
    follow_links: bool = False
    zones       : list = field( default_factory = list )     # [ Zone ]

    def __post_init__( self ):
        for z in self.zones:
            if not isinstance( z, Zone ) or z.kind not in ZONES:
                raise SyncError( f"{z!r}: a zone is a Zone( pattern, kind ), its kind one of {', '.join( ZONES )}" )
        self._excludes = Patterns( self.excludes )
        self._zones = { }
        for z in self.zones:
            self._zones.setdefault( z.kind, [ ] ).append( z.pattern )
        self._zones = [ ( kind, Patterns( ps ) ) for kind, ps in self._zones.items() ]

    def zone( self, key: str, name: str | None = None ) -> Zone | None:
        name = key.rsplit( "/", 1 )[ -1 ] if name is None else name
        for kind, ps in self._zones:
            p = ps.match( key, name )
            if p is not None:
                return Zone( p, kind )
        return None

    def skips( self, key: str, name: str ) -> bool:
        return self._excludes.match( key, name ) is not None or self.zone( key, name ) is not None

    def zone_under( self, key: str ) -> Zone | None:
        """The zone `key` or one of its parents is in."""
        parts = key.split( "/" )
        for i in range( 1, len( parts ) + 1 ):
            z = self.zone( "/".join( parts[ : i ] ), parts[ i - 1 ] )
            if z is not None:
                return z
        return None


# -- a manifest -----------------------------------------------------------------

def hash_file( path ) -> str:
    h = hashlib.blake2b( digest_size = 16 )
    with open( path, "rb" ) as f:
        for chunk in iter( lambda: f.read( CHUNK ), b"" ):
            h.update( chunk )
    return h.hexdigest()


def scan( root, sel: Selection, cache: dict | None = None, hashing = True ) -> Manifest:
    """What `root` holds, minus what `sel` excludes. A file's hash is taken from `cache` while its
    size and mtime have not changed, computed otherwise -- or left out, without `hashing`."""
    root, out, old = Path( root ), Manifest(), cache or { }

    def walk( directory: str, key_dir: str, real_dir: str ):
        try:
            it = os.scandir( directory )
        except ( FileNotFoundError, NotADirectoryError ):
            return
        with it:
            for e in sorted( it, key = lambda e: e.name ):
                name = unicodedata.normalize( "NFC", e.name )
                key, real = key_dir + name, real_dir + e.name
                if sel.skips( key, name ) or ( not key_dir and name.startswith( COPY_STATE ) ):
                    continue
                if key in out:
                    raise SyncError( f"{real_dir + e.name!r} and {out.on_disk( key )!r} are one name once "
                                     f"normalized: rename one of them" )
                try:
                    st = os.stat( e.path ) if sel.follow_links else e.stat( follow_symlinks = False )
                except FileNotFoundError:
                    continue                     # gone since listed, or a link to nothing that is followed
                if real != key:
                    out.real[ key ] = real
                if stat.S_ISLNK( st.st_mode ):
                    out[ key ] = Entry( "l", target = os.readlink( e.path ) )
                elif stat.S_ISDIR( st.st_mode ):
                    out[ key ] = Entry( "d" )
                    walk( e.path, key + "/", real + "/" )
                elif stat.S_ISREG( st.st_mode ):
                    exe = bool( st.st_mode & stat.S_IXUSR )
                    prev = old.get( key )
                    digest = prev.digest if prev is not None and prev.kind == "f" and \
                             ( prev.size, prev.mtime_ns ) == ( st.st_size, st.st_mtime_ns ) else ""
                    if hashing and not digest:
                        digest = hash_file( e.path )
                    out[ key ] = Entry( "f", st.st_size, st.st_mtime_ns, exe, digest )
                # sockets, fifos, devices: not part of a project

    walk( str( root ), "", "" )
    return out


def load( path ) -> Manifest | None:
    """A manifest kept from an earlier sync; None if there is none, or one that cannot be read."""
    try:
        raw = json.loads( Path( path ).read_text() )
    except ( OSError, ValueError ):
        return None
    out = Manifest( ( k, Entry( *v ) ) for k, v in raw.get( "entries", { } ).items() )
    out.real = raw.get( "real", { } )
    out.found = [ ( Finding( *f ), Entry( *e ) if e else None ) for f, e in raw.get( "found", [ ] ) ]
    out.generation = raw.get( "generation", "" )
    return out


def save( path, manifest: Manifest ):
    path = Path( path )
    path.parent.mkdir( parents = True, exist_ok = True )
    part = path.with_name( path.name + ".part" )
    part.write_text( json.dumps( { "entries": { k: list( v ) for k, v in manifest.items() },
                                   "real": manifest.real, "generation": getattr( manifest, "generation", "" ),
                                   "found": [ [ list( f ), list( e ) if e else None ]
                                              for f, e in getattr( manifest, "found", [ ] ) ] } ) )
    os.replace( part, path )


# -- what changed, what to do ---------------------------------------------------

class Finding( NamedTuple ):
    key     : str
    what    : str                # "changed", "added", "removed"
    mtime_ns: int = 0            # when, for a file still there


def compare( trusted: Manifest, found: Manifest ) -> list:
    """What `found` ( a walk of the disk ) says changed since `trusted` was written."""
    out = [ ]
    for key, e in found.items():
        t = trusted.get( key )
        if t is None:
            out.append( Finding( key, "added", e.mtime_ns ) )
        elif not t.same( e ) and not ( t.kind == "f" and t.digest and t.digest == e.digest and t.exe == e.exe ):
            out.append( Finding( key, "changed", e.mtime_ns ) )
    out += [ Finding( key, "removed" ) for key in trusted if key not in found ]
    return sorted( out )


def check( root, sel: Selection, trusted ) -> list:
    """The copy at `root` against what errand wrote there ( the manifest at `trusted` ): what the
    agent holding the copy does when it starts and when it goes ( ADR 0006 ). What it finds is kept
    with the manifest, for the next sync to say and put back. -> the findings, new ones and pending."""
    known = load( trusted )
    if known is None:
        return [ ]
    disk = scan( root, sel, known, hashing = False )
    pending = { f.key: ( f, e ) for f, e in known.found }
    for f in compare( known, disk ):
        if f.key not in pending:               # the first time it was seen says when
            pending[ f.key ] = ( f, disk.get( f.key ) )
    known.found = [ pending[ k ] for k in sorted( pending ) ]
    save( trusted, known )
    return [ f for f, _ in known.found ]


@dataclass
class Plan:
    delete: list = field( default_factory = list )   # deepest first
    dirs  : list = field( default_factory = list )
    links : list = field( default_factory = list )
    send  : list = field( default_factory = list )   # files whose contents cross
    touch : list = field( default_factory = list )   # files with the same contents: only mtime and mode set


def depth_first( keys ) -> list:
    return sorted( set( keys ), key = lambda k: ( -k.count( "/" ), k ) )


def plan( src: Manifest, dst: Manifest, hash_dst = None ) -> Plan:
    """What brings `dst` in line with `src`. A file of the same size whose mtime differs is hashed on
    the destination ( `hash_dst( key )` ) before its contents are sent: a `touch` costs no transfer."""
    p = Plan()
    for key, s in src.items():
        d = dst.get( key )
        if d is not None and ( d.kind != s.kind or ( s.kind == "l" and d.target != s.target ) ):
            p.delete.append( key )
            d = None
        if s.kind == "d":
            if d is None:
                p.dirs.append( key )
        elif s.kind == "l":
            if d is None:
                p.links.append( key )
        elif d is None:
            p.send.append( key )
        elif not s.same( d ):
            theirs = d.digest or ( hash_dst( key ) if hash_dst is not None and d.size == s.size else "" )
            ( p.touch if s.digest and theirs == s.digest else p.send ).append( key )
    p.delete += [ key for key in dst if key not in src ]
    p.delete = depth_first( p.delete )
    p.dirs.sort()
    return p


def collisions( keys ) -> list:
    """Names that are one on a case-insensitive file system."""
    seen : dict = { }
    for k in keys:
        seen.setdefault( k.casefold(), [ ] ).append( k )
    return sorted( v for v in seen.values() if len( v ) > 1 )


def case_insensitive( root ) -> bool:
    probe = Path( root ) / f".errand-case-{os.getpid()}"
    probe.touch()
    try:
        return os.path.exists( str( Path( root ) / probe.name.upper() ) )
    finally:
        probe.unlink()


# -- the contents ---------------------------------------------------------------

def read_into( root, src: Manifest, key: str, write, again = None ):
    """The bytes of `key`, given to `write` chunk by chunk. A file that changed while it was read is
    read once more, after `again()` ( the receiver starts over ). -> ( its Entry as read, stable )."""
    path = Path( root ) / src.on_disk( key )
    for attempt in ( 0, 1 ):
        if attempt:
            again()
        h = hashlib.blake2b( digest_size = 16 )
        with open( path, "rb" ) as f:
            before = os.fstat( f.fileno() )
            size = 0
            for chunk in iter( lambda: f.read( CHUNK ), b"" ):
                h.update( chunk )
                size += len( chunk )
                write( chunk )
            after = os.stat( path )
        entry = Entry( "f", size, after.st_mtime_ns, bool( after.st_mode & stat.S_IXUSR ), h.hexdigest() )
        if ( before.st_size, before.st_mtime_ns ) == ( after.st_size, after.st_mtime_ns ) == ( size, after.st_mtime_ns ):
            return entry, True
        if again is None:
            break
    return entry, False


class Writer:
    """The destination's side: what a plan does there. A file is written beside its target and
    renamed into place once whole: an interrupted sync never leaves half a file under its name."""

    def __init__( self, root, dst: Manifest | None = None ):
        self.root = Path( root )
        self.dst = dst if dst is not None else Manifest()
        mask = os.umask( 0 )
        os.umask( mask )
        self.modes = ( 0o666 & ~mask, 0o777 & ~mask )

    def path( self, key: str ) -> Path:
        return self.root / self.dst.on_disk( key )

    def delete( self, key: str ) -> bool:
        """-> False for a directory that is not empty: something excluded is left in it."""
        p = self.path( key )
        try:
            if p.is_dir() and not p.is_symlink():
                p.rmdir()
            else:
                p.unlink()
        except FileNotFoundError:
            pass
        except OSError as err:
            if err.errno in ( errno.ENOTEMPTY, errno.EEXIST ):
                return False
            raise
        self.dst.real.pop( key, None )
        return True

    def mkdir( self, key: str ):
        self.path( key ).mkdir( parents = True, exist_ok = True )

    def link( self, key: str, target: str ):
        p = self.path( key )
        p.parent.mkdir( parents = True, exist_ok = True )
        os.symlink( target, p )

    def begin( self, key: str ):
        p = self.path( key )
        p.parent.mkdir( parents = True, exist_ok = True )
        part = p.with_name( f".{p.name}.errand-part" )
        return [ part, open( part, "wb" ), p ]

    def restart( self, handle ):
        handle[ 1 ].seek( 0 )
        handle[ 1 ].truncate()

    def write( self, handle, chunk: bytes ):
        handle[ 1 ].write( chunk )

    def commit( self, handle, entry: Entry ):
        part, f, p = handle
        f.close()
        os.chmod( part, self.modes[ entry.exe ] )
        os.utime( part, ns = ( entry.mtime_ns, entry.mtime_ns ) )
        os.replace( part, p )

    def abort( self, handle ):
        handle[ 1 ].close()
        try:
            handle[ 0 ].unlink()
        except OSError:
            pass

    def touch( self, key: str, entry: Entry ):
        p = self.path( key )
        os.chmod( p, self.modes[ entry.exe ] )
        os.utime( p, ns = ( entry.mtime_ns, entry.mtime_ns ) )


# -- two directories of this machine -------------------------------------------

def _held( sel: Selection, key: str, directory: Path ) -> Zone | None:
    """The zone of what keeps `directory` from going, when it is right in it."""
    try:
        names = sorted( os.listdir( directory ) )
    except OSError:
        return None
    for name in names:
        z = sel.zone( f"{key}/{unicodedata.normalize( 'NFC', name )}", unicodedata.normalize( "NFC", name ) )
        if z is not None:
            return z
    return None

@dataclass
class Report:
    sent    : list = field( default_factory = list )
    bytes   : int = 0
    touched : list = field( default_factory = list )
    deleted : list = field( default_factory = list )
    kept    : list = field( default_factory = list )     # directories not removed: something excluded is in them
    findings: list = field( default_factory = list )     # changed on the destination since it was last written
    unstable: list = field( default_factory = list )     # changed while being read, twice

    def __bool__( self ):
        return bool( self.sent or self.touched or self.deleted )


def when( mtime_ns: int ) -> str:
    import time
    return time.strftime( "%Y-%m-%d %H:%M:%S", time.localtime( mtime_ns / 1e9 ) )


def say_findings( findings, where: str, say, sel: Selection | None = None ):
    """What changed on the copy outside its zones, and that it is about to be put back. Then, once,
    where a run may write: the zones, and how to declare one."""
    for f in findings:
        if f.what == "removed":
            say( f"  {f.key}: removed on {where} since errand wrote it -- written again" )
        elif f.what == "added":
            say( f"  {f.key}: appeared on {where} ( {when( f.mtime_ns )} ), not in the project -- removed" )
        else:
            say( f"  {f.key}: changed on {where} ( {when( f.mtime_ns )} ) since errand wrote it -- replaced" )
    if findings:
        zones = ", ".join( f"{z.pattern} ( {z.kind} )" for z in ( sel.zones if sel else [ ] ) if z.kind != "errand" )
        say( f"  outside its zones{' ( ' + zones + ' )' if zones else ''}, {where} holds only what errand "
             f"sends. A path a run writes, to keep: declare a zone, "
             f"`errand.configure( zones = {{ \"path\": \"back\" }} )`" )


def sync( src_root, dst_root, sel: Selection, *, src_cache = None, trusted = None, check = True,
          where = "the copy", say = print ) -> Report:
    """`dst_root` in line with `src_root`.

    `src_cache`: where the source's manifest is kept, so that only a changed file is hashed again.
    `trusted`: where the destination's is kept -- what errand wrote there. With `check`, the
    destination is walked, and what changed since is said before it is replaced; without, the
    trusted manifest is taken for the disk ( ADR 0006: checked when the agent starts and goes )."""
    src_root, dst_root = Path( src_root ), Path( dst_root )
    report = Report()
    src = scan( src_root, sel, load( src_cache ) if src_cache else None )
    if src_cache:
        save( src_cache, src )
    known = load( trusted ) if trusted else None
    if check or known is None:
        dst = scan( dst_root, sel, known, hashing = False )
        if known is not None:
            first = { f.key: f for f, _ in known.found }         # a check saw it first: its time is the one
            report.findings = [ first.get( f.key, f ) for f in compare( known, dst ) ]
    else:
        dst = Manifest( known )                # the disk, as the agent's checks left it: the trusted
        dst.real = dict( known.real )          # manifest, and what they found since
        for f, e in known.found:
            if e is None:
                dst.pop( f.key, None )
            else:
                dst[ f.key ] = e._replace( digest = "" ) if e.kind == "f" else e
        report.findings = [ f for f, _ in known.found ]
    say_findings( report.findings, where, say, sel )
    dst_root.mkdir( parents = True, exist_ok = True )
    if case_insensitive( dst_root ):
        clash = collisions( src )
        if clash:
            raise SyncError( "names that are one on " + where + " ( it does not tell case apart ): "
                             + "; ".join( " / ".join( c ) for c in clash ) )
    w = Writer( dst_root, dst )

    def theirs( key ):
        try:
            return hash_file( w.path( key ) )
        except OSError:
            return ""

    p = plan( src, dst, theirs )
    for key in p.delete:
        if w.delete( key ):
            report.deleted.append( key )
        else:
            report.kept.append( key )
            if key not in src:
                held = _held( sel, key, w.path( key ) )
                if held is not None and held.kind != "errand":
                    say( f"  {key}: left on {where}, it holds {held}" )
    report.deleted = [ k for k in report.deleted if k not in src ]       # a key whose kind changed was replaced
    for key in p.dirs:
        w.mkdir( key )
    for key in p.links:
        w.link( key, src[ key ].target )
    written = Manifest( src )                      # what the destination holds once done: its names, not the source's
    written.real = { k: v for k, v in dst.real.items() if k in src }
    for key in [ k for k in report.kept if k not in src ]:   # still there: not something to find next time
        written[ key ] = dst[ key ]
    for key in p.send:
        h = w.begin( key )
        try:
            entry, stable = read_into( src_root, src, key, lambda c: w.write( h, c ), lambda: w.restart( h ) )
        except BaseException:
            w.abort( h )
            raise
        w.commit( h, entry )
        written[ key ] = entry
        report.sent.append( key )
        report.bytes += entry.size
        if not stable:
            report.unstable.append( key )
            say( f"  {key}: changed while it was read, twice -- what was read is on {where}" )
    for key in p.touch:
        w.touch( key, src[ key ] )
        report.touched.append( key )
    if trusted:
        save( trusted, written )
    return report


# -- on the wire ----------------------------------------------------------------

def _zstd():
    try:
        from compression import zstd           # Python 3.14
        return zstd
    except ImportError:
        return None


def codecs( ) -> list:
    """What this side reads: told to the other, which then packs with the best of them."""
    return [ "z", "d", "-" ] if _zstd() is not None else [ "d", "-" ]


def pack( data: bytes, accepted = ( "z", "d" ) ) -> bytes:
    """A chunk as it crosses: zstd where both sides have it, zlib otherwise; the first byte says which."""
    z = _zstd() if "z" in accepted else None
    if z is not None:
        return b"z" + z.compress( data )
    if "d" in accepted:
        return b"d" + zlib.compress( data, 1 )
    return b"-" + data


def unpack( data: bytes ) -> bytes:
    tag, body = data[ : 1 ], data[ 1 : ]
    if tag == b"z":
        z = _zstd()
        if z is None:
            raise SyncError( "a chunk compressed with zstd, which this Python cannot read" )
        return z.decompress( body )
    if tag == b"d":
        return zlib.decompress( body )
    if tag == b"-":
        return body
    raise SyncError( f"a chunk of unknown kind {tag!r}" )
