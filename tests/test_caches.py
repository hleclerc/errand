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

if test( "journals are merged into the manifest, then removed; a line cut short is skipped" ):
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
    assert os.listdir( root / C.JOURNALS ) == [ ] and json.loads( ( root / C.MANIFEST ).read_text() )[ "format" ] == C.FORMAT


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
