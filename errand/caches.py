"""The caches of the libraries a run uses ( ADR 0019, `$ERRAND_CACHES/<name>` ), and what errand removes from them
( ADR 0020 ).

A library that wants its cache looked after keeps, at the root of it, the format below. errand knows nothing else of
the library: what an entry is, what its key means and what it depends on are the library's to say.

    <cache>/errand-cache-journal/<host>-<pid>-<start>.jsonl     each process its own, one JSON object a line:
        { "op": "create", "entry": K, "product": [ paths ], "intermediate": [ paths ], "needs": [ entries ],
          "shared": false, "size": bytes, "cost_s": seconds, "deps": { "/abs/path": [ sha256, size, mtime_ns ] },
          "view": "" ( ADR 0022, optional ),
          "at": "2026-11-19T10:00:00Z" }
        { "op": "use", "entries": [ K, ... ], "at": "..." }
    <cache>/errand-cache.json                                   the entries, written only by a compactor
    <cache>/errand-cache.lock/                                  the compactor's lock ( `mkdir`: atomic on NFS, Lustre )

Paths of an entry are relative to the cache; its `deps` are absolute ( a cache is one machine's ). A writer appends a
line by opening, writing and closing its own file: nobody else writes it. A compactor reads each journal from where it
stopped last time ( `journals` in the manifest ), whole lines only, and removes it once read and untouched for a day
( ADR 0022: taking it by renaming lost the lines of a writer that had it open, on NFS ).

What goes ( `purge` ), with no age and no size budget for now:

1. an entry not used for a day, one of whose `deps` is gone or holds other contents;
2. a `shared` entry not used for a day that no remaining entry `needs`;
3. ( `intermediate` paths: in the format, not removed yet. )

A path no entry names is never touched.

ADR 0022: a `create` line may say its `view` ( `$ERRAND_CACHES_VIEW`: empty on the machine as it is, `apptainer:<image>`
in a container ): a purge judges the `deps` of its own view's entries only, and marks `dead` one it finds dead but used
within a day. Each machine keeps a registry of the `$ERRAND_CACHES` its runs used ( `register`, `registered` ), and each
such directory says once who it is ( `errand-caches.id` ): two paths with one id are one directory.
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
VIEW_ENV = "ERRAND_CACHES_VIEW"  # where the `deps` of what a run creates are seen ( ADR 0022 )
IDENT    = "errand-caches.id"    # in `$ERRAND_CACHES`: { id, host, made }
REGISTRY = "caches"              # under errand's per-user directory: one file per `$ERRAND_CACHES` seen here
UNUSED_DAYS = 30                 # what the screens call unused, until told otherwise


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
        if old.get( "created", "" ) > at:
            return                                   # a later build of it was merged already
        entries[ line[ "entry" ] ] = {
            "product"     : list( line.get( "product", [ ] ) ),
            "intermediate": list( line.get( "intermediate", [ ] ) ),
            "needs"       : list( line.get( "needs", [ ] ) ),
            "shared"      : bool( line.get( "shared", False ) ),
            "size"        : int( line.get( "size", 0 ) ),
            "cost_s"      : float( line.get( "cost_s", 0.0 ) ),
            "deps"        : dict( line.get( "deps", { } ) ),
            "view"        : str( line.get( "view" ) or "" ),
            "created"     : at,
            "used"        : max( at, old.get( "used", "" ) ),    # ISO strings of one format sort as times
        }
    elif op == "use":
        for k in line.get( "entries", [ ] ):
            if k in entries:
                entries[ k ][ "used" ] = max( at, entries[ k ].get( "used", "" ) )


def _read_journal( path: Path, start: int ):
    """The whole lines of a journal from byte `start` -> ( lines, where the next read starts ). A line cut short ( a
    writer at it, a process that died ) is left for the next read."""
    with open( path, "rb" ) as f:
        f.seek( start )
        data = f.read()
    end = data.rfind( b"\n" ) + 1
    out = [ ]
    for raw in data[ : end ].splitlines():
        try:
            out.append( json.loads( raw ) )
        except ValueError:
            pass                                     # garbage: skipped, never read again
    return out, start + end


def compact( root, now: float | None = None ) -> dict:
    """The journals of the cache at `root` merged into its manifest. To be called with the lock held.

    A journal is read from where the last compaction stopped ( `journals`: name -> [ inode, offset ] in the manifest ),
    never renamed: a writer that opened it a moment ago appends to the very file that is read next time ( ADR 0022:
    renaming lost lines on NFS ). A journal read to its end and untouched for a day is removed."""
    root = Path( root )
    now = time.time() if now is None else now
    m = load( root )
    jd = root / JOURNALS
    try:
        names = sorted( os.listdir( jd ) )
    except OSError:
        return m
    state, lines, done = m.setdefault( "journals", { } ), [ ], [ ]
    for name in names:
        p = jd / name
        try:
            if name.endswith( ".jsonl" ):
                st = p.stat()
                ino, start = state.get( name, [ None, 0 ] )
                if ino != st.st_ino or start > st.st_size:
                    start = 0                        # another file of that name
                if st.st_size > start:
                    got, start = _read_journal( p, start )
                    lines += got
                state[ name ] = [ st.st_ino, start ]
                if start >= st.st_size and now - st.st_mtime > DAY:
                    done.append( p )
            elif ".jsonl.taken-" in name:            # an older compactor's, that died after taking it
                got, _ = _read_journal( p, 0 )
                lines += got
                done.append( p )
        except OSError:
            continue
    for line in sorted( lines, key = lambda l: l.get( "at", "" ) ):
        merge( m, line )
    for p in done:
        with contextlib.suppress( OSError ):
            p.unlink()
    present = set( names ) - { p.name for p in done }
    for name in list( state ):
        if name not in present:
            del state[ name ]
    save( root, m )
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


def _purged_key( view: str ) -> str:
    return "purged" if not view else f"purged:{view}"


def _closure( entries: dict, gone: list, eager: bool, idle ) -> list:
    """`gone`, with the entries that need a shared one of them, and then the shared entries nothing left needs
    ( not used for a day, unless `eager`: a removal by hand )."""
    gone = list( dict.fromkeys( gone ) )
    alive = { k for k in entries if k not in gone }
    while True:
        out = { k for k in gone if entries[ k ].get( "shared" ) }
        more = [ k for k in alive if out & set( entries[ k ].get( "needs", [ ] ) ) ] if eager else [ ]
        needed = { n for k in alive - set( more ) for n in entries[ k ].get( "needs", [ ] ) }
        more += [ k for k in alive - set( more ) if entries[ k ].get( "shared" ) and k not in needed
                  and ( eager or idle( entries[ k ] ) ) ]
        if not more:
            return gone
        gone += more
        alive -= set( more )


def _drop( root: Path, m: dict, gone: list, dry_run: bool ) -> int:
    entries, freed = m[ "entries" ], 0
    for k in gone:
        e = entries[ k ]
        if dry_run:
            freed += int( e.get( "size", 0 ) )
        else:
            freed += _remove( root, [ *e.get( "product", [ ] ), *e.get( "intermediate", [ ] ) ] )
            del entries[ k ]
    return freed


def _report( m: dict, gone: list, freed: int ) -> dict:
    alive = [ k for k in m[ "entries" ] if k not in gone ]
    return { "removed": sorted( gone ), "freed": freed, "entries": len( alive ),
             "size": sum( int( m[ "entries" ][ k ].get( "size", 0 ) ) for k in alive ) }


def purge( root, *, now: float | None = None, dry_run = False, wait = 0.0, view = "",
           unused_days: float | None = None ) -> dict | None:
    """Compact, then remove what the rules say ( module doc ), judging the `deps` of `view`'s entries only, and
    marking `dead` those found dead but used within a day. `unused_days`: also the entries not shared, not used for
    that long, and then the shared entries nothing needs, at once ( `errand caches --unused` ).
    -> { "removed": [ entries ], "freed": bytes, "entries": how many remain, "size": their bytes }, None if another
    compactor holds the cache."""
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
                continue
            if unused_days is not None and not e.get( "shared" ) and now - seconds( e.get( "used" ) ) >= unused_days * DAY:
                gone.append( k )
                continue
            if e.get( "shared" ) or e.get( "view", "" ) != view:
                continue                             # judged where its deps are seen ( ADR 0022 )
            if _changed( e.get( "deps", { } ), hashes ):
                e[ "dead" ] = e.get( "dead" ) or now_iso( now )
                if idle( e ):
                    gone.append( k )
            else:
                e.pop( "dead", None )                # back as it was: a branch switched away and back
        gone = _closure( entries, gone, eager = unused_days is not None, idle = idle )
        freed = _drop( root, m, gone, dry_run )
        if not dry_run:
            m[ _purged_key( view ) ] = now_iso( now )
            save( root, m )
        return _report( m, gone, freed )


def remove( root, keys = None, *, rule: str | None = None, days: float = UNUSED_DAYS, now: float | None = None,
            dry_run = False, wait = 10.0 ) -> dict | None:
    """Removal by hand ( ADR 0022 ): `keys`, or what `rule` names -- `dead` ( marked so by a purge in their view ),
    `unused` ( not shared, not used for `days` ). Takes the entries that need a shared one removed, then the shared
    entries nothing needs, at once. -> as `purge`, None if the lock stayed held."""
    root = Path( root )
    now = time.time() if now is None else now
    with locked( root, wait ) as held:
        if not held:
            return None
        m = compact( root )
        entries = m[ "entries" ]
        if rule == "dead":
            gone = [ k for k, e in entries.items() if e.get( "dead" ) ]
        elif rule == "unused":
            gone = [ k for k, e in entries.items() if not e.get( "shared" ) and now - seconds( e.get( "used" ) ) >= days * DAY ]
        elif rule is None:
            gone = [ k for k in keys or ( ) if k in entries ]
        else:
            raise ValueError( f"no rule {rule!r} ( dead, unused )" )
        gone = _closure( entries, gone, eager = True, idle = lambda e: True ) if gone else [ ]
        freed = _drop( root, m, gone, dry_run )
        if not dry_run and gone:
            save( root, m )
        return _report( m, gone, freed )


# -- every cache of a place -----------------------------------------------------

def caches_in( caches_root ) -> list:
    """The caches under `$ERRAND_CACHES` that follow the format ( a manifest or journals ): the others are left alone."""
    try:
        dirs = sorted( d for d in Path( caches_root ).iterdir() if d.is_dir() )
    except OSError:
        return [ ]
    return [ d for d in dirs if ( d / MANIFEST ).is_file() or ( d / JOURNALS ).is_dir() ]


def due( cache, view = "" ) -> bool:
    """Not purged for a day in `view` ( ADR 0020: at most once a day and a cache; ADR 0022: and a view )."""
    return time.time() - seconds( load( cache ).get( _purged_key( view ) ) ) >= DAY


def purge_all( caches_root, *, dry_run = False, only_due = False, say = None, view = "", unused_days = None ) -> list:
    """Each cache of a place: [ ( name, report ) ]. `say` gets one line for a cache something went from."""
    out = [ ]
    for cache in caches_in( caches_root ):
        if only_due and not due( cache, view ):
            continue
        r = purge( cache, dry_run = dry_run, view = view, unused_days = unused_days )
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


# -- what a machine holds ( ADR 0022 ) ------------------------------------------

def ident( where, make = True ) -> dict | None:
    """Who the `$ERRAND_CACHES` at `where` is: { id, host, made }, written once by the first run to use it --
    `host` is the machine that holds it. Two paths that say one id are one directory ( a bind, a home over NFS )."""
    path = Path( where ) / IDENT
    try:
        return json.loads( path.read_text() )
    except ( OSError, ValueError ):
        pass
    if not make:
        return None
    import secrets
    said = { "id": secrets.token_hex( 8 ), "host": socket.gethostname(), "made": now_iso() }
    try:
        fd = os.open( str( path ), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644 )
        with os.fdopen( fd, "w" ) as f:
            json.dump( said, f )
        return said
    except FileExistsError:
        try:
            return json.loads( path.read_text() )        # written by another meanwhile: theirs
        except ( OSError, ValueError ):
            return None
    except OSError:
        return None


def _registry( ) -> Path:
    from . import bootstrap
    return bootstrap.local_cache() / REGISTRY


def register( where, view = "", project = None ):
    """`$ERRAND_CACHES` at `where` used by a run on this machine, seen from `view`. Never fatal."""
    where = Path( where )
    try:
        said = ident( where ) or { }
        d = _registry()
        d.mkdir( parents = True, exist_ok = True )
        path = d / f"{hashlib.sha1( str( where ).encode() ).hexdigest()[ : 16 ]}.json"
        try:
            old = json.loads( path.read_text() )
        except ( OSError, ValueError ):
            old = { }
        views = sorted( set( old.get( "views", [ ] ) ) | { view or "" } )
        rec = { "path": str( where ), "id": said.get( "id" ), "host": said.get( "host" ), "views": views,
                "project": str( project ) if project else old.get( "project" ), "seen": now_iso() }
        if rec != { **old, "seen": rec[ "seen" ] }:
            tmp = path.with_suffix( f".{os.getpid()}.tmp" )
            tmp.write_text( json.dumps( rec ) )
            os.replace( tmp, path )
    except OSError:
        pass


def registered( ) -> list:
    """The `$ERRAND_CACHES` runs used on this machine, one per directory ( the first path of an id ): a record
    whose directory is gone is dropped."""
    out, ids = [ ], set()
    try:
        files = sorted( _registry().glob( "*.json" ) )
    except OSError:
        return [ ]
    for f in files:
        try:
            rec = json.loads( f.read_text() )
        except ( OSError, ValueError ):
            continue
        if not Path( rec.get( "path", "" ) ).is_dir():
            if not any( rec.get( "views" ) or [ "" ] ):  # seen from this machine as it is: gone
                with contextlib.suppress( OSError ):
                    f.unlink()
            continue                                 # a container's path for it: its bare path says it
        said = ident( rec[ "path" ], make = False ) or { }
        rec[ "id" ], rec[ "host" ] = said.get( "id" ) or rec.get( "id" ), said.get( "host" ) or rec.get( "host" )
        key = rec[ "id" ] or rec[ "path" ]
        if key in ids:
            first = next( r for r in out if ( r[ "id" ] or r[ "path" ] ) == key )
            views = sorted( set( first.get( "views", [ ] ) ) | set( rec.get( "views", [ ] ) ) )
            if "" in rec.get( "views", [ ] ) and "" not in first.get( "views", [ ] ):
                first.update( rec )                  # the path the machine as it is reaches it by
            first[ "views" ] = views
            continue
        ids.add( key )
        out.append( rec )
    return out


def hold( ident_or_path: str | None = None ) -> list:
    """This machine holds the registered directories named by id or path ( all of them when None ): its host agent
    purges them ( ADR 0022: chosen by hand, e.g. a cluster's login node rather than the compute node that made it ).
    -> [ ( path, previous holder ) ]. ValueError when none is named so here."""
    out = [ ]
    for rec in registered():
        if ident_or_path not in ( None, rec.get( "id" ), rec[ "path" ] ):
            continue
        path = Path( rec[ "path" ] ) / IDENT
        said = ident( rec[ "path" ] ) or { }
        was = said.get( "host" )
        said = { **said, "host": socket.gethostname(), "held": now_iso() }
        tmp = path.with_name( f".{IDENT}.{os.getpid()}.part" )
        tmp.write_text( json.dumps( said ) )
        os.replace( tmp, path )
        out.append( ( rec[ "path" ], was ) )
    if not out:
        raise ValueError( f"no cache directory {ident_or_path!r} on {socket.gethostname()}" if ident_or_path else
                          f"no cache directory on {socket.gethostname()}: a run under errand writes its $ERRAND_CACHES down" )
    return out


def held_here( rec: dict ) -> bool:
    """This machine holds the directory of `rec`: it made it ( ADR 0022 ), or nobody said."""
    return not rec.get( "host" ) or rec[ "host" ].split( "." )[ 0 ] == socket.gethostname().split( "." )[ 0 ]


def _entry_view( e: dict, now: float, days: float ) -> dict:
    return { "size": int( e.get( "size", 0 ) ), "used": e.get( "used" ), "created": e.get( "created" ),
             "dead": e.get( "dead" ), "shared": bool( e.get( "shared" ) ), "needs": e.get( "needs", [ ] ),
             "view": e.get( "view", "" ), "cost_s": e.get( "cost_s", 0.0 ),
             "unused": not e.get( "shared" ) and now - seconds( e.get( "used" ) ) >= days * DAY }


def summary( cache, *, days: float = UNUSED_DAYS, entries = False, compacted = True, now = None ) -> dict:
    """One cache as the screens show it: { name, entries, size, dead, dead_size, unused, unused_size, journals,
    purged }, and with `entries` its entries ( `_entry_view` ). Compacted first when its lock is free and
    `compacted`; otherwise read as it is, the journals not merged yet only counted."""
    cache, now = Path( cache ), time.time() if now is None else now
    m = None
    if compacted:
        with locked( cache ) as held:
            if held:
                m = compact( cache )
    if m is None:
        m = load( cache )
    journals, state = 0, m.get( "journals", { } )
    try:
        for n in os.listdir( cache / JOURNALS ):     # those with lines not merged yet
            if n.endswith( ".jsonl" ):
                st = ( cache / JOURNALS / n ).stat()
                ino, read = state.get( n, [ None, 0 ] )
                journals += st.st_size > ( read if ino == st.st_ino else 0 )
    except OSError:
        pass
    es = { k: _entry_view( e, now, days ) for k, e in m[ "entries" ].items() }
    out = { "name": cache.name, "entries": len( es ), "size": sum( e[ "size" ] for e in es.values() ),
            "dead": sum( 1 for e in es.values() if e[ "dead" ] ),
            "dead_size": sum( e[ "size" ] for e in es.values() if e[ "dead" ] ),
            "unused": sum( 1 for e in es.values() if e[ "unused" ] ),
            "unused_size": sum( e[ "size" ] for e in es.values() if e[ "unused" ] ),
            "journals": journals, "purged": m.get( "purged" ),
            "views": sorted( { e[ "view" ] for e in es.values() } ) }
    if entries:
        out[ "list" ] = es
    return out


def report( *, days: float = UNUSED_DAYS, entries = ( ), compacted = True, purge_with: dict | None = None,
            say = None ) -> dict:
    """What this machine holds: { host, dirs: [ { path, id, host, views, project, caches: [ summary ] } ] }.
    `entries`: the names of the caches whose entries come too ( `"*"`: all ). `purge_with`: ADR 0020's rules
    first ( { dry_run, unused_days } ), in the bare view, each cache's report as `purged` beside its summary."""
    dirs = [ ]
    for rec in registered():
        caches = [ ]
        for cache in caches_in( rec[ "path" ] ):
            try:
                done = None
                if purge_with is not None:
                    done = purge( cache, dry_run = bool( purge_with.get( "dry_run" ) ), wait = 10.0,
                                  unused_days = purge_with.get( "unused_days" ) )
                s = summary( cache, days = days, compacted = compacted and not ( purge_with or { } ).get( "dry_run" ),
                             entries = "*" in entries or cache.name in entries )
                if done is not None:
                    s[ "purged_now" ] = done
            except Exception as err:            # one cache that cannot be read is not the report's failure
                s = { "name": cache.name, "error": f"{type( err ).__name__}: {err}" }
            caches.append( s )
        dirs.append( { **rec, "caches": caches } )
    return { "host": socket.gethostname(), "time": time.time(), "dirs": dirs }


def remove_in( ident_or_path: str, cache: str, **how ) -> dict:
    """`remove` on cache `cache` of the registered directory named by its id ( or its path ). ValueError when
    there is none here."""
    for rec in registered():
        if ident_or_path in ( rec.get( "id" ), rec[ "path" ] ):
            root = Path( rec[ "path" ] ) / cache
            if cache in ( "", ".", ".." ) or "/" in cache or not root.is_dir():
                raise ValueError( f"no cache {cache!r} in {rec[ 'path' ]}" )
            got = remove( root, **how )
            if got is None:
                raise ValueError( f"{root}: its compactor's lock stayed held; try again" )
            return got
    raise ValueError( f"no cache directory {ident_or_path!r} on {socket.gethostname()}" )


def purge_held( say = None ) -> list:
    """The host agent's daily round ( ADR 0022 ): the registered directories this machine holds, in the bare view,
    those not purged for a day. -> [ ( path, name, report ) ]."""
    out = [ ]
    for rec in registered():
        if not held_here( rec ):
            continue
        for name, r in purge_all( rec[ "path" ], only_due = True, say = say ):
            out.append( ( rec[ "path" ], name, r ) )
    return out


def detected_view( ) -> str:
    """`$ERRAND_CACHES_VIEW` when the side that started this run said it; else what the process sees of a
    container it is in ( a run started by hand in one )."""
    if VIEW_ENV in os.environ:
        return os.environ[ VIEW_ENV ]
    image = os.environ.get( "APPTAINER_CONTAINER" ) or os.environ.get( "SINGULARITY_CONTAINER" )
    if image:
        return f"apptainer:{Path( image ).name}"
    if os.path.exists( "/.dockerenv" ) or os.path.exists( "/run/.containerenv" ):
        return f"container:{socket.gethostname()}"
    return ""
