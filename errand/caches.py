"""The caches of the libraries a run uses ( ADR 0019, `$ERRAND_CACHES/<name>` ), and what errand removes from them
( ADR 0020 ).

A library that wants its cache looked after keeps, at the root of it, the format below. errand knows nothing else of
the library: what an entry is, what its key means and what it depends on are the library's to say.

    <cache>/errand-cache-journal/<host>-<pid>-<start>.jsonl     each process its own, one JSON object a line:
        { "op": "create", "entry": K, "product": [ paths ], "intermediate": [ paths ], "needs": [ entries ],
          "shared": false, "size": bytes, "cost_s": seconds, "deps": { "/abs/path": [ sha256, size, mtime_ns ] },
          "at": "2026-11-19T10:00:00Z" }
        { "op": "use", "entries": [ K, ... ], "at": "..." }
    <cache>/errand-cache.json                                   the entries, written only by a compactor
    <cache>/errand-cache.lock/                                  the compactor's lock ( `mkdir`: atomic on NFS, Lustre )

Paths of an entry are relative to the cache; its `deps` are absolute ( a cache is one machine's ). A writer appends a
line by opening, writing and closing its own file: nobody else writes it. A compactor takes a journal by renaming it
first, so that a line written meanwhile goes to a new file of the same name.

What goes ( `purge` ), with no age and no size budget for now:

1. an entry not used for a day, one of whose `deps` is gone or holds other contents;
2. a `shared` entry not used for a day that no remaining entry `needs`;
3. ( `intermediate` paths: in the format, not removed yet. )

A path no entry names is never touched.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

FORMAT   = "errand-cache/1"
MANIFEST = "errand-cache.json"
JOURNALS = "errand-cache-journal"
LOCK     = "errand-cache.lock"
DAY      = 86400.0
STALE    = 15 * 60.0            # a lock older than this was left by a compactor that died


def now_iso( t: float | None = None ) -> str:
    return datetime.fromtimestamp( time.time() if t is None else t, timezone.utc ).strftime( "%Y-%m-%dT%H:%M:%SZ" )


def seconds( iso: str | None ) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.strptime( iso, "%Y-%m-%dT%H:%M:%SZ" ).replace( tzinfo = timezone.utc ).timestamp()
    except ValueError:
        return 0.0


def sha256( path ) -> str:
    h = hashlib.sha256()
    with open( path, "rb" ) as f:
        for chunk in iter( lambda: f.read( 1 << 20 ), b"" ):
            h.update( chunk )
    return h.hexdigest()


# -- the lock -------------------------------------------------------------------

@contextlib.contextmanager
def locked( root, wait = 0.0 ):
    """The compactor's lock of the cache at `root`. Yields False when another holds it ( and `wait` ran out ):
    the caller does nothing, the other one is at it."""
    lock = Path( root ) / LOCK
    deadline = time.monotonic() + wait
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > STALE:
                    shutil.rmtree( lock, ignore_errors = True )
                    continue
            except OSError:
                continue
            if time.monotonic() >= deadline:
                yield False
                return
            time.sleep( 0.1 )
        except OSError:
            yield False
            return
    try:
        ( lock / "owner" ).write_text( f"{socket.gethostname()} {os.getpid()}\n" )
    except OSError:
        pass
    try:
        yield True
    finally:
        shutil.rmtree( lock, ignore_errors = True )


# -- the manifest ---------------------------------------------------------------

def load( root ) -> dict:
    try:
        m = json.loads( ( Path( root ) / MANIFEST ).read_text() )
        if m.get( "format" ) == FORMAT:
            m.setdefault( "entries", { } )
            return m
    except ( OSError, ValueError ):
        pass
    return { "format": FORMAT, "hash": "sha256", "purged": None, "entries": { } }


def save( root, m: dict ):
    path = Path( root ) / MANIFEST
    part = path.with_name( f".{path.name}.{os.getpid()}.part" )
    part.write_text( json.dumps( m, indent = 1, sort_keys = True ) )
    os.replace( part, path )


def merge( m: dict, line: dict ):
    """One journal line into the manifest `m`."""
    op, at = line.get( "op" ), line.get( "at" ) or now_iso()
    entries = m[ "entries" ]
    if op == "create" and line.get( "entry" ):
        old = entries.get( line[ "entry" ], { } )
        entries[ line[ "entry" ] ] = {
            "product"     : list( line.get( "product", [ ] ) ),
            "intermediate": list( line.get( "intermediate", [ ] ) ),
            "needs"       : list( line.get( "needs", [ ] ) ),
            "shared"      : bool( line.get( "shared", False ) ),
            "size"        : int( line.get( "size", 0 ) ),
            "cost_s"      : float( line.get( "cost_s", 0.0 ) ),
            "deps"        : dict( line.get( "deps", { } ) ),
            "created"     : at,
            "used"        : max( at, old.get( "used", "" ) ),    # ISO strings of one format sort as times
        }
    elif op == "use":
        for k in line.get( "entries", [ ] ):
            if k in entries:
                entries[ k ][ "used" ] = max( at, entries[ k ].get( "used", "" ) )


def compact( root ) -> dict:
    """The journals of the cache at `root` merged into its manifest, then removed. To be called with the lock held."""
    root = Path( root )
    m = load( root )
    jd = root / JOURNALS
    try:
        names = sorted( os.listdir( jd ) )
    except OSError:
        return m
    taken = [ ]
    for name in names:
        p = jd / name
        if name.endswith( ".jsonl" ):
            to = p.with_name( f"{name}.taken-{os.getpid()}" )
            try:
                os.replace( p, to )
            except OSError:
                continue
            taken.append( to )
        elif ".jsonl.taken-" in name:               # a compactor that died after taking it: taken again
            taken.append( p )
    lines = [ ]
    for p in taken:
        try:
            text = p.read_text( errors = "replace" )
        except OSError:
            continue
        for raw in text.splitlines():
            try:
                lines.append( json.loads( raw ) )
            except ValueError:
                pass                                 # a line cut short by a process that died
    for line in sorted( lines, key = lambda l: l.get( "at", "" ) ):
        merge( m, line )
    save( root, m )
    for p in taken:
        with contextlib.suppress( OSError ):
            p.unlink()
    return m


# -- what goes ------------------------------------------------------------------

def _changed( deps: dict, hashes: dict ) -> bool:
    """One of `deps` is gone or holds other contents. `hashes`: path -> its hash now, kept over one purge."""
    for path, rec in deps.items():
        want = rec[ 0 ] if isinstance( rec, list ) else rec
        try:
            st = os.stat( path )
        except OSError:
            return True
        if isinstance( rec, list ) and len( rec ) >= 3 and ( rec[ 1 ], rec[ 2 ] ) == ( st.st_size, st.st_mtime_ns ):
            continue
        if path not in hashes:
            try:
                hashes[ path ] = sha256( path )
            except OSError:
                return True
        if hashes[ path ] != want:
            return True
        if isinstance( rec, list ) and len( rec ) >= 3:      # the same contents, touched: known as it is now
            rec[ 1 ], rec[ 2 ] = st.st_size, st.st_mtime_ns
    return False


def _remove( root: Path, paths ) -> int:
    freed = 0
    for rel in paths:
        p = root / rel
        if ".." in Path( rel ).parts or Path( rel ).is_absolute():
            continue                                 # an entry names what is in its cache, nothing else
        try:
            if p.is_dir() and not p.is_symlink():
                freed += sum( f.stat().st_size for f in p.rglob( "*" ) if f.is_file() and not f.is_symlink() )
                shutil.rmtree( p, ignore_errors = True )
            elif p.exists() or p.is_symlink():
                freed += p.lstat().st_size
                p.unlink()
        except OSError:
            pass
    return freed


def purge( root, *, now: float | None = None, dry_run = False, wait = 0.0 ) -> dict | None:
    """Compact, then remove what the rules say ( module doc ). -> { "removed": [ entries ], "freed": bytes,
    "entries": how many remain, "size": their bytes }, None if another compactor holds the cache."""
    root = Path( root )
    now = time.time() if now is None else now
    with locked( root, wait ) as held:
        if not held:
            return None
        m = compact( root )
        entries, hashes, gone = m[ "entries" ], { }, [ ]
        idle = lambda e: now - seconds( e.get( "used" ) ) >= DAY
        for k, e in list( entries.items() ):
            if not any( ( root / p ).exists() for p in e.get( "product", [ ] ) ):
                del entries[ k ]                     # removed by hand, or never published: nothing to do
            elif not e.get( "shared" ) and idle( e ) and _changed( e.get( "deps", { } ), hashes ):
                gone.append( k )
        alive = { k for k in entries if k not in gone }
        while True:                                  # a shared entry goes once nothing left needs it
            needed = { n for k in alive for n in entries[ k ].get( "needs", [ ] ) }
            more = [ k for k in alive if entries[ k ].get( "shared" ) and k not in needed and idle( entries[ k ] ) ]
            if not more:
                break
            gone += more
            alive -= set( more )
        freed = 0
        for k in gone:
            e = entries[ k ]
            if dry_run:
                freed += int( e.get( "size", 0 ) )
            else:
                freed += _remove( root, [ *e.get( "product", [ ] ), *e.get( "intermediate", [ ] ) ] )
                del entries[ k ]
        if not dry_run:
            m[ "purged" ] = now_iso( now )
            save( root, m )
        return { "removed": sorted( gone ), "freed": freed, "entries": len( alive ),
                 "size": sum( int( entries[ k ].get( "size", 0 ) ) for k in alive ) }


# -- every cache of a place -----------------------------------------------------

def caches_in( caches_root ) -> list:
    """The caches under `$ERRAND_CACHES` that follow the format ( a manifest or journals ): the others are left alone."""
    try:
        dirs = sorted( d for d in Path( caches_root ).iterdir() if d.is_dir() )
    except OSError:
        return [ ]
    return [ d for d in dirs if ( d / MANIFEST ).is_file() or ( d / JOURNALS ).is_dir() ]


def due( cache ) -> bool:
    """Not purged for a day ( ADR 0020: at most once a day and a cache )."""
    return time.time() - seconds( load( cache ).get( "purged" ) ) >= DAY


def purge_all( caches_root, *, dry_run = False, only_due = False, say = None ) -> list:
    """Each cache of a place: [ ( name, report ) ]. `say` gets one line for a cache something went from."""
    out = [ ]
    for cache in caches_in( caches_root ):
        if only_due and not due( cache ):
            continue
        r = purge( cache, dry_run = dry_run )
        if r is None:
            continue
        out.append( ( cache.name, r ) )
        if say and r[ "removed" ]:
            verb = "would free" if dry_run else "freed"
            say( f"caches/{cache.name}: {len( r[ 'removed' ] )} entries, {human( r[ 'freed' ] )} {verb} "
                 f"( {r[ 'entries' ]} left, {human( r[ 'size' ] )} )" )
    return out


def human( n: float ) -> str:
    for unit in ( "B", "kB", "MB", "GB" ):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} TB"
