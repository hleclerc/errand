"""The caches of the libraries ( ADR 0020 ): a cache written by hand, as the format says, is read, compacted and purged
by errand, which knows nothing else of the library that wrote it."""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from errand import test
from errand import caches as C


def cache( ) -> Path:
    return Path( tempfile.mkdtemp() ) / "lib"


def write( root: Path, rel: str, text = "x" ):
    p = root / rel
    p.parent.mkdir( parents = True, exist_ok = True )
    p.write_text( text )
    return p


def dep( path: Path ) -> list:
    st = path.stat()
    return [ C.sha256( path ), st.st_size, st.st_mtime_ns ]


def journal( root: Path, *lines, name = "host-1-0" ):
    d = root / C.JOURNALS
    d.mkdir( parents = True, exist_ok = True )
    with open( d / f"{name}.jsonl", "a" ) as f:
        for l in lines:
            f.write( json.dumps( l ) + "\n" )


def create( key, product, at, deps = None, needs = ( ), shared = False, size = 10 ):
    return { "op": "create", "entry": key, "product": product, "needs": list( needs ), "shared": shared,
             "size": size, "cost_s": 4.0, "deps": deps or { }, "at": C.now_iso( at ) }


DAYS = 2 * C.DAY

if test( "journals are merged into the manifest; a line cut short waits for its end; read and a day old, removed" ):
    root = cache()
    write( root, "k/a.so" )
    t = time.time() - 10
    journal( root, create( "k/a", [ "k/a" ], t ) )
    journal( root, { "op": "use", "entries": [ "k/a", "unknown" ], "at": C.now_iso( t + 5 ) }, name = "host-2-0" )
    with open( root / C.JOURNALS / "host-2-0.jsonl", "a" ) as f:
        f.write( '{"op": "use", "entr' )
    with C.locked( root ) as held:
        assert held
        m = C.compact( root )
    assert list( m[ "entries" ] ) == [ "k/a" ] and m[ "entries" ][ "k/a" ][ "used" ] == C.now_iso( t + 5 ), m
    assert json.loads( ( root / C.MANIFEST ).read_text() )[ "format" ] == C.FORMAT
    with open( root / C.JOURNALS / "host-2-0.jsonl", "a" ) as f:          # the cut line, finished: read now, once
        f.write( 'ies": [ "k/a" ], "at": "' + C.now_iso( t + 9 ) + '"}\n' )
    with C.locked( root ) as held:
        m = C.compact( root )
        assert m[ "entries" ][ "k/a" ][ "used" ] == C.now_iso( t + 9 ), m           # a line being written, not garbage
        m = C.compact( root, now = time.time() + 2 * C.DAY )                       # read to the end, a day old: gone
    assert os.listdir( root / C.JOURNALS ) == [ ] and m[ "journals" ] == { }, m


if test( "a line written to a journal a compactor has just read is merged next time: nothing is taken away from a writer" ):
    root = cache()
    write( root, "k/a.so" ), write( root, "k/b.so" )
    journal( root, create( "k/a", [ "k/a" ], time.time() ) )
    f = open( root / C.JOURNALS / "host-1-0.jsonl", "a" )                     # a writer that opened it ...
    with C.locked( root ) as held:
        assert list( C.compact( root )[ "entries" ] ) == [ "k/a" ]
    f.write( json.dumps( create( "k/b", [ "k/b" ], time.time() ) ) + "\n" )   # ... and writes after the compaction
    f.close()
    assert C.summary( root, compacted = False )[ "journals" ] == 1
    with C.locked( root ) as held:
        assert sorted( C.compact( root )[ "entries" ] ) == [ "k/a", "k/b" ]
    assert C.summary( root, compacted = False )[ "journals" ] == 0


if test( "rule 1: an entry whose dependency changed or went, unused for a day, goes; one used since stays" ):
    root, src = cache(), Path( tempfile.mkdtemp() )
    h1, h2, h3 = write( src, "h1.h", "one" ), write( src, "h2.h", "two" ), write( src, "h3.h", "three" )
    for k in ( "a", "b", "c", "d" ):
        write( root, f"kernels/{k}/{k}.so" )
    old = time.time() - DAYS
    journal( root, create( "kernels/a", [ "kernels/a" ], old, { str( h1 ): dep( h1 ) } ),
                   create( "kernels/b", [ "kernels/b" ], old, { str( h2 ): dep( h2 ) } ),
                   create( "kernels/c", [ "kernels/c" ], old, { str( h3 ): dep( h3 ) } ),
                   create( "kernels/d", [ "kernels/d" ], time.time(), { str( h2 ): dep( h2 ) } ) )
    h2.write_text( "changed" )
    h3.unlink()
    os.utime( h1, ( time.time() + 5, time.time() + 5 ) )      # touched, same contents: alive
    r = C.purge( root )
    assert r[ "removed" ] == [ "kernels/b", "kernels/c" ], r
    assert ( root / "kernels/a" ).exists() and ( root / "kernels/d" ).exists() and not ( root / "kernels/b" ).exists()
    assert sorted( C.load( root )[ "entries" ] ) == [ "kernels/a", "kernels/d" ]


if test( "rule 2: a shared entry goes once nothing left needs it; a path no entry names is never touched" ):
    root, src = cache(), Path( tempfile.mkdtemp() )
    h = write( src, "h.h" )
    write( root, "units/u.so" ), write( root, "units/v.so" ), write( root, "kernels/a/a.so" ), write( root, "kernels/b/b.so" )
    write( root, "stray/file" )
    old = time.time() - DAYS
    journal( root, create( "units/u.so", [ "units/u.so" ], old, shared = True ),
                   create( "units/v.so", [ "units/v.so" ], old, shared = True ),
                   create( "kernels/a", [ "kernels/a" ], old, { str( h ): dep( h ) }, needs = [ "units/u.so" ] ),
                   create( "kernels/b", [ "kernels/b" ], old, { str( h ): dep( h ) }, needs = [ "units/v.so" ] ) )
    h.write_text( "other" )                          # both kernels go, then the units they needed
    r = C.purge( root, dry_run = True )
    assert r[ "removed" ] == [ "kernels/a", "kernels/b", "units/u.so", "units/v.so" ] and ( root / "units/u.so" ).exists(), r
    r = C.purge( root )
    assert len( r[ "removed" ] ) == 4 and not ( root / "units" / "u.so" ).exists() and ( root / "stray/file" ).exists(), r


if test( "an entry removed by hand leaves the manifest; another compactor's lock makes a purge do nothing" ):
    root = cache()
    write( root, "k/a.so" )
    journal( root, create( "k/a", [ "k/a" ], time.time() ) )
    C.purge( root )
    shutil.rmtree( root / "k" )
    C.purge( root )
    assert C.load( root )[ "entries" ] == { }
    ( root / C.LOCK ).mkdir()
    assert C.purge( root ) is None
    old = time.time() - 2 * C.STALE
    os.utime( root / C.LOCK, ( old, old ) )           # left by a compactor that died
    assert C.purge( root ) is not None and not ( root / C.LOCK ).exists()


if test( "every cache of a place: only those that follow the format, at most once a day" ):
    top = Path( tempfile.mkdtemp() )
    write( top / "lib", "k/a.so" )
    journal( top / "lib", create( "k/a", [ "k/a" ], time.time() ) )
    write( top / "other", "big.bin" )                  # a cache errand does not keep: left alone
    assert [ d.name for d in C.caches_in( top ) ] == [ "lib" ]
    assert [ n for n, _ in C.purge_all( top, only_due = True ) ] == [ "lib" ]
    assert C.purge_all( top, only_due = True ) == [ ]


# -- ADR 0022: views, removal by hand, the registry, the screens -----------------

def private_cache_dir():
    d = Path( tempfile.mkdtemp() ) / "errand-cache"
    os.environ[ "ERRAND_CACHE_DIR" ] = str( d )
    return d


if test( "a purge judges its own view's entries only, marks the dead ones used today, and clears a mark once back" ):
    root, src = cache(), Path( tempfile.mkdtemp() )
    h = write( src, "h.h", "one" )
    for k in ( "bare", "boxed", "fresh" ):
        write( root, f"k/{k}/x.so" )
    old = time.time() - DAYS
    journal( root, create( "k/bare", [ "k/bare" ], old, { str( h ): dep( h ) } ),
                   { **create( "k/boxed", [ "k/boxed" ], old, { str( h ): dep( h ) } ), "view": "apptainer:img.sif" },
                   create( "k/fresh", [ "k/fresh" ], time.time(), { str( h ): dep( h ) } ) )
    saved = dep( h )
    h.write_text( "two" )
    r = C.purge( root )                                  # the bare view: k/boxed is the container's to judge
    assert r[ "removed" ] == [ "k/bare" ], r
    es = C.load( root )[ "entries" ]
    assert es[ "k/fresh" ].get( "dead" ) and not es[ "k/boxed" ].get( "dead" ), es
    assert C.purge( root, view = "apptainer:img.sif" )[ "removed" ] == [ "k/boxed" ]
    h.write_text( "one" )                                 # switched back: alive again
    C.purge( root )
    assert not C.load( root )[ "entries" ][ "k/fresh" ].get( "dead" )
    assert C.due( root, "other:view" ) and not C.due( root, "" )


if test( "removal by hand: a shared entry takes what needs it, then the shared entries nothing needs go at once" ):
    root = cache()
    for rel in ( "u/u.so", "v/v.so", "k/a/a.so", "k/b/b.so", "k/c/c.so" ):
        write( root, rel )
    now = time.time()
    journal( root, create( "u", [ "u" ], now, shared = True ), create( "v", [ "v" ], now, shared = True ),
                   create( "k/a", [ "k/a" ], now, needs = [ "u" ] ), create( "k/b", [ "k/b" ], now, needs = [ "u", "v" ] ),
                   create( "k/c", [ "k/c" ], now - 40 * C.DAY, needs = [ "v" ] ) )
    r = C.remove( root, [ "u" ], dry_run = True )
    assert r[ "removed" ] == [ "k/a", "k/b", "u" ] and ( root / "u" ).exists(), r
    r = C.remove( root, rule = "unused", days = 30 )       # k/c, then v that nothing needs any more? k/b needs it
    assert r[ "removed" ] == [ "k/c" ], r
    r = C.remove( root, [ "k/b" ] )                       # now nothing needs v: it goes at once
    assert r[ "removed" ] == [ "k/b", "v" ] and not ( root / "v" ).exists() and ( root / "u" ).exists(), r
    m = C.load( root )
    m[ "entries" ][ "k/a" ][ "dead" ] = C.now_iso()
    C.save( root, m )
    assert C.remove( root, rule = "dead" )[ "removed" ] == [ "k/a", "u" ]


if test( "purge --unused: entries not used for DAYS go with the rules, then the shared ones left alone" ):
    root = cache()
    for rel in ( "u/u.so", "k/a/a.so", "k/b/b.so" ):
        write( root, rel )
    journal( root, create( "u", [ "u" ], time.time(), shared = True ),
                   create( "k/a", [ "k/a" ], time.time() - 10 * C.DAY, needs = [ "u" ] ),
                   create( "k/b", [ "k/b" ], time.time() - 2 * C.DAY ) )
    assert C.purge( root, unused_days = 5 )[ "removed" ] == [ "k/a", "u" ]


if test( "the registry: a directory once per id, whatever the path it is reached by; gone, it is dropped" ):
    private_cache_dir()
    top = Path( tempfile.mkdtemp() ) / "caches"
    top.mkdir()
    link = top.parent / "bound"
    link.symlink_to( top )
    write( top / "lib", "k/a/a.so", "12345" )
    journal( top / "lib", create( "k/a", [ "k/a" ], time.time() - 40 * C.DAY, size = 5 ) )
    C.register( top, "", "/p/one" )
    C.register( link, "apptainer:x", "/p/one" )
    got = C.registered()
    assert len( got ) == 1 and got[ 0 ][ "path" ] == str( top ) and C.held_here( got[ 0 ] ) and got[ 0 ][ "views" ] == [ "", "apptainer:x" ], got
    rep = C.report( entries = [ "lib" ] )
    c = rep[ "dirs" ][ 0 ][ "caches" ][ 0 ]
    assert ( c[ "entries" ], c[ "size" ], c[ "unused" ] ) == ( 1, 5, 1 ) and c[ "list" ][ "k/a" ][ "unused" ], c
    from errand.agents import look
    said = look.answer( { "op": "caches", "entries": [ "lib" ] } )
    assert said[ "ok" ] and said[ "dirs" ][ 0 ][ "id" ] == got[ 0 ][ "id" ], said
    said = look.answer( { "op": "caches_remove", "id": got[ 0 ][ "id" ], "cache": "lib", "rule": "unused", "days": 30 } )
    assert said[ "removed" ] == [ "k/a" ] and not ( top / "lib/k/a" ).exists(), said
    assert "error" in look.answer( { "op": "caches_remove", "id": got[ 0 ][ "id" ], "cache": "../x", "keys": [ "a" ] } )
    other = dict( C.ident( top ), host = "node14" )                       # made by a compute node ...
    ( top / C.IDENT ).write_text( json.dumps( other ) )
    assert not C.held_here( C.registered()[ 0 ] )
    said = look.answer( { "op": "caches_hold", "id": got[ 0 ][ "id" ] } )       # ... held by this machine now
    assert said[ "held" ] == [ [ str( top ), "node14" ] ] and C.held_here( C.registered()[ 0 ] ), said
    assert C.ident( top )[ "id" ] == got[ 0 ][ "id" ]
    assert "error" in look.answer( { "op": "caches_hold", "id": "nope" } )
    shutil.rmtree( top )
    assert C.registered() == [ ]


class Fake:
    """A machine as `tui.machines.Machine` is, answering `caches` from what it was given."""
    def __init__( self, name, caches ):
        self.name, self.caches, self.here, self.dormant, self.caches_busy = name, caches, False, False, True
        self.asked = [ ]

    def ask( self, req, timeout = 0 ):
        self.asked.append( req )
        return { "ok": True, "removed": req.get( "keys" ) or [ "x" ], "freed": 7 }


def summary( list_ ):
    es = { k: { "size": s, "used": C.now_iso(), "dead": d, "unused": u, "shared": False, "needs": [ ], "view": "",
                "created": None, "cost_s": 0 } for k, ( s, d, u ) in list_.items() }
    return { "name": "loom", "entries": len( es ), "size": sum( e[ "size" ] for e in es.values() ),
             "dead": sum( 1 for e in es.values() if e[ "dead" ] ), "dead_size": sum( e[ "size" ] for e in es.values() if e[ "dead" ] ),
             "unused": sum( 1 for e in es.values() if e[ "unused" ] ),
             "unused_size": sum( e[ "size" ] for e in es.values() if e[ "unused" ] ), "journals": 0, "purged": None,
             "views": [ "" ], "list": es }


if test( "the caches tab: one row per place ( a shared directory once ), entries merged, removals planned per place" ):
    from errand.tui import caches as K, rows as R
    shared = { "path": "/nfs/p/caches", "id": "aa", "host": "lmo", "project": "/nfs/p", "views": [ "" ],
               "caches": [ summary( { "k1": ( 100, "2026-11-19T00:00:00Z", False ), "k2": ( 50, None, True ) } ) ] }
    mac = { "path": "/Users/h/p/caches", "id": "bb", "host": "mac", "project": "/Users/h/p", "views": [ "" ],
            "caches": [ summary( { "k1": ( 90, None, False ), "k3": ( 10, None, False ) } ) ] }
    ms = [ Fake( "mac", { "dirs": [ mac ], "guests": [ ] } ), Fake( "lmo", { "dirs": [ shared ], "guests": [ ] } ),
           Fake( "n22", { "dirs": [ shared ], "guests": [ ] } ) ]
    rows = R.build( ms, tab = "caches", opened = { "entries:loom" } )
    labels = [ ( r.kind, r.label ) for r in rows ]
    assert ( "cachefs", "lmo = n22  p" ) in labels and ( "cachefs", "mac  p" ) in labels, labels
    entries = { r.label: r for r in rows if r.kind == "centry" }
    assert sorted( entries ) == [ "k1", "k2" ], entries                       # k3: alive everywhere, not listed
    assert "dead on lmo = n22" in entries[ "k1" ].detail and "on mac, lmo = n22" in entries[ "k1" ].detail
    every = [ r.label for r in R.build( ms, tab = "caches", opened = { "entries:loom" }, every = True ) if r.kind == "centry" ]
    assert sorted( every ) == [ "k1", "k2", "k3" ]
    assert len( { R.key( r ) for r in rows } ) == len( rows )                  # the cursor can stay on any of them

    p = K.plan( entries[ "k1" ], "flagged", ms )
    assert [ ( m.name, req[ "id" ] ) for m, req, _ in p.reqs ] == [ ( "lmo", "aa" ) ], p.reqs
    p = K.plan( entries[ "k1" ], "everywhere", ms )
    assert sorted( m.name for m, _, _ in p.reqs ) == [ "lmo", "mac" ]
    assert K.send( p ).startswith( "2 entries removed" )
    head = next( r for r in rows if r.kind == "cache" )
    p = K.plan( head, "dead", ms )
    assert [ m.name for m, _, _ in p.reqs ] == [ "lmo" ] and "1 loom entries dead" in p.title, p.title
    place = next( r for r in rows if r.kind == "cachefs" and r.label.startswith( "mac" ) )
    try:
        K.plan( place, "unused", ms )
        assert False, "nothing unused on mac"
    except ValueError as err:
        assert "nothing unused" in str( err )
    assert any( k == "dead" for k, _ in R.facts( next( r for r in rows if r.kind == "cachefs" and r.label.startswith( "lmo" ) ), None ) )
    lmo_row = next( r for r in rows if r.kind == "cachefs" and r.label.startswith( "lmo" ) )
    h = K.hold_plan( lmo_row, ms )
    assert [ ( m.name, req ) for m, req, _ in h.reqs ] == [ ( "lmo", { "op": "caches_hold", "id": "aa" } ) ], h.reqs
    assert any( "also reached by n22" in l for l in h.lines ), h.lines
    try:
        K.hold_plan( head, ms )
        assert False
    except ValueError:
        pass
    folded = R.build( ms, tab = "caches", folded = { ( "cache", "loom" ) } )
    assert [ r.kind for r in folded ] == [ "cache" ]


if test( "errand status and errand caches say each machine's caches, a shared directory once" ):
    import contextlib as cl
    import io
    from errand.cli import standing
    rep = { "dirs": [ { "path": "/nfs/p/caches", "id": "aa", "project": "/nfs/p",
                        "caches": [ summary( { "k1": ( 2000, "x", False ) } ) ] } ] }
    out = io.StringIO()
    with cl.redirect_stdout( out ):
        n = standing.show_caches( [ ( "lmo", { "caches": rep }, None ), ( "n22", { "caches": rep }, None ), ( "x", None, "down" ) ] )
    assert n == 1 and "lmo" in out.getvalue() and "p/loom: 1 entries, 2.0 kB" in out.getvalue() and "1 dead" in out.getvalue(), out.getvalue()

    private_cache_dir()
    proj = Path( tempfile.mkdtemp() )
    out = io.StringIO()
    from errand import config
    with cl.redirect_stdout( out ):
        from errand.cli import caches as CC
        rc = CC.main( proj, [ ], unused = 3 )
    assert rc == 0 and str( config.caches( proj ).resolve() ) in out.getvalue(), out.getvalue()
