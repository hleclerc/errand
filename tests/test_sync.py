"""The sync by manifest ( ADR 0006 ), between two directories of this machine: what rsync did,
and the corner cases it had settled -- links, modes, types that change, names, files that change
while they are read, a copy changed behind errand's back.
"""
import os
import shutil
import tempfile
import time
import unicodedata
from pathlib import Path

from errand import test
from errand import sync as S


def tree( spec: dict, root = None ) -> Path:
    """{ "a/b.txt": "text", "run.sh": ( "text", 0o755 ), "ln": ( "->", "a/b.txt" ), "empty/": None }"""
    root = Path( root or tempfile.mkdtemp() )
    for rel, what in spec.items():
        p = root / rel
        if rel.endswith( "/" ):
            p.mkdir( parents = True, exist_ok = True )
            continue
        p.parent.mkdir( parents = True, exist_ok = True )
        if isinstance( what, tuple ) and what[ 0 ] == "->":
            os.symlink( what[ 1 ], p )
            continue
        text, mode = what if isinstance( what, tuple ) else ( what, 0o644 )
        p.write_text( text )
        os.chmod( p, mode )
    return root


def same_trees( a, b, sel = S.Selection() ):
    ma, mb = S.scan( a, sel ), S.scan( b, sel )
    assert ma.keys() == mb.keys(), ( sorted( ma.keys() ^ mb.keys() ) )
    for k in ma:
        ea, eb = ma[ k ], mb[ k ]
        assert ea.kind == eb.kind and ea.target == eb.target, ( k, ea, eb )
        if ea.kind == "f":
            assert ( ea.digest, ea.exe, ea.mtime_ns, ea.size ) == ( eb.digest, eb.exe, eb.mtime_ns, eb.size ), ( k, ea, eb )


def quiet( * _ ):
    pass


def pair( spec ):
    src = tree( spec )
    dst = Path( tempfile.mkdtemp() ) / "copy"
    state = Path( tempfile.mkdtemp() )
    return src, dst, state


def run( src, dst, state, sel = S.Selection(), **kw ):
    said = [ ]
    r = S.sync( src, dst, sel, src_cache = state / "src.json", trusted = state / "dst.json",
                say = said.append, **kw )
    return r, said


if test( "a tree crosses whole: contents, mtimes, the executable bit, links, empty directories" ):
    src, dst, state = pair( { "a/b.txt": "b", "run.sh": ( "#!/bin/sh\n", 0o755 ), "ln": ( "->", "a/b.txt" ),
                              "dangling": ( "->", "nowhere" ), "empty/": None, "a/c/d.txt": "d" } )
    r, said = run( src, dst, state )
    same_trees( src, dst )
    assert sorted( r.sent ) == [ "a/b.txt", "a/c/d.txt", "run.sh" ] and not said
    assert os.readlink( dst / "dangling" ) == "nowhere"
    again, _ = run( src, dst, state )
    assert not again, ( "nothing changed, nothing crosses", again )


if test( "what is excluded is neither sent nor deleted: by name anywhere, or anchored at the root" ):
    sel = S.Selection( [ "__pycache__", "*.pyc", "/img.sif", "build" ] )
    src, dst, state = pair( { "m.py": "x", "pkg/__pycache__/m.pyc": "c", "pkg/n.pyc": "c", "img.sif": "big",
                              "sub/img.sif": "small", "build/o": "o" } )
    tree( { "img.sif": "theirs", "build/out": "theirs" }, dst )
    run( src, dst, state, sel )
    assert ( dst / "sub/img.sif" ).read_text() == "small", "anchored: only at the root"
    assert ( dst / "img.sif" ).read_text() == "theirs" and ( dst / "build/out" ).exists()
    assert not ( dst / "pkg/__pycache__" ).exists() and not ( dst / "pkg/n.pyc" ).exists()


if test( "what left the source leaves the copy; a directory holding something excluded stays, and says so" ):
    sel = S.Selection( [ "__pycache__" ] )
    src, dst, state = pair( { "keep.txt": "k", "gone.txt": "g", "old/a.txt": "a", "pkg/m.py": "m" } )
    run( src, dst, state, sel )
    ( dst / "pkg/__pycache__" ).mkdir()
    ( src / "gone.txt" ).unlink()
    shutil.rmtree( src / "old" )
    shutil.rmtree( src / "pkg" )
    r, _ = run( src, dst, state, sel )
    assert sorted( r.deleted ) == [ "gone.txt", "old", "old/a.txt", "pkg/m.py" ], r.deleted
    assert r.kept == [ "pkg" ] and ( dst / "pkg/__pycache__" ).is_dir()
    assert sorted( os.listdir( dst ) ) == [ "keep.txt", "pkg" ]
    r, said = run( src, dst, state, sel )
    assert not r.findings and not said, "a directory left in place is not found again as a change"


if test( "a file touched but not changed costs no transfer: only its mtime and mode are set" ):
    src, dst, state = pair( { "a.txt": "same", "b.txt": "b" } )
    run( src, dst, state )
    later = time.time_ns() + 5_000_000_000
    os.utime( src / "a.txt", ns = ( later, later ) )
    os.chmod( src / "a.txt", 0o755 )
    ( src / "b.txt" ).write_text( "B" )
    r, _ = run( src, dst, state )
    assert r.touched == [ "a.txt" ] and r.sent == [ "b.txt" ], r
    same_trees( src, dst )


if test( "a path that changes kind is replaced: file to directory, directory to file, file to link" ):
    src, dst, state = pair( { "x": "file", "y/inside.txt": "i", "z": "file" } )
    run( src, dst, state )
    ( src / "x" ).unlink()
    tree( { "x/now.txt": "n" }, src )
    shutil.rmtree( src / "y" )
    ( src / "y" ).write_text( "now a file" )
    ( src / "z" ).unlink()
    os.symlink( "y", src / "z" )
    r, _ = run( src, dst, state )
    same_trees( src, dst )
    assert "x" not in r.deleted and "y/inside.txt" in r.deleted, "a replaced path is not a deleted one"


if test( "a link that points elsewhere is replaced; links followed, a link is its target" ):
    src, dst, state = pair( { "t1": "one", "t2": "two", "ln": ( "->", "t1" ) } )
    run( src, dst, state )
    ( src / "ln" ).unlink()
    os.symlink( "t2", src / "ln" )
    run( src, dst, state )
    assert os.readlink( dst / "ln" ) == "t2"
    followed = Path( tempfile.mkdtemp() ) / "w"
    S.sync( src, followed, S.Selection( follow_links = True ), say = quiet )
    assert not ( followed / "ln" ).is_symlink() and ( followed / "ln" ).read_text() == "two"


if test( "names are NFC on both sides: a name macOS wrote decomposed is the same file" ):
    nfd = unicodedata.normalize( "NFD", "café.txt" )
    src, dst, state = pair( { nfd: "c" } )
    m = S.scan( src, S.Selection() )
    assert list( m ) == [ "café.txt" ] and unicodedata.is_normalized( "NFC", list( m )[ 0 ] )
    r, _ = run( src, dst, state )
    assert r.sent == [ "café.txt" ]
    again, _ = run( src, dst, state )
    assert not again, again


if test( "a rename that only changes case reaches a copy that does not tell case apart" ):
    src, dst, state = pair( { "readme": "r" } )
    run( src, dst, state )
    os.rename( src / "readme", src / "tmp" )
    os.rename( src / "tmp", src / "README" )
    run( src, dst, state )
    assert os.listdir( dst ) == [ "README" ], os.listdir( dst )
    assert S.collisions( [ "A.txt", "a.txt", "b" ] ) == [ [ "A.txt", "a.txt" ] ]


if test( "a copy changed behind errand's back is said so, then put back; trusted, it is not looked at" ):
    src, dst, state = pair( { "a.txt": "a", "b.txt": "b", "c.txt": "c" } )
    run( src, dst, state )
    ( dst / "a.txt" ).write_text( "edited over there" )
    ( dst / "b.txt" ).unlink()
    ( dst / "new.txt" ).write_text( "n" )
    r, said = run( src, dst, state )
    assert [ ( f.key, f.what ) for f in r.findings ] == [ ( "a.txt", "changed" ), ( "b.txt", "removed" ),
                                                          ( "new.txt", "added" ) ], r.findings
    assert len( said ) == 4 and "a.txt: changed on the copy" in said[ 0 ] and "zone" in said[ 3 ], said
    same_trees( src, dst )
    ( dst / "c.txt" ).write_text( "edited again" )
    r, said = run( src, dst, state, check = False )
    assert not r and not said and ( dst / "c.txt" ).read_text() == "edited again", \
        "between the checks, the trusted manifest is the disk"


if test( "only a file whose size or mtime changed is hashed again" ):
    src, dst, state = pair( { f"f{i}.txt": str( i ) for i in range( 5 ) } )
    run( src, dst, state )
    ( src / "f3.txt" ).write_text( "changed" )
    hashed = [ ]
    real = S.hash_file
    S.hash_file = lambda p: hashed.append( Path( p ).name ) or real( p )
    try:
        run( src, dst, state )
    finally:
        S.hash_file = real
    assert hashed == [ "f3.txt" ], hashed


if test( "a file that changes while it is read is read again; one that keeps changing is said so" ):
    src = tree( { "log.txt": "x" * 100 } )
    m = S.scan( src, S.Selection() )
    got, starts = [ ], [ ]

    def growing( times ):
        def write( chunk ):                # once per reading: what it appends is read in the same pass
            got.append( chunk )
            if len( starts ) < times and len( got ) == 1:
                with open( src / "log.txt", "a" ) as f:
                    f.write( "more" )
                os.utime( src / "log.txt", ns = ( time.time_ns() + len( starts ) * 10**9, ) * 2 )
        return write

    entry, stable = S.read_into( src, m, "log.txt", growing( 1 ), lambda: ( starts.append( 1 ), got.clear() ) )
    assert stable and entry.size == 104 and b"".join( got ) == b"x" * 100 + b"more", ( entry, stable )
    starts.clear(), got.clear()
    entry, stable = S.read_into( src, m, "log.txt", growing( 5 ), lambda: ( starts.append( 1 ), got.clear() ) )
    assert not stable and starts == [ 1 ]


if test( "an interrupted copy leaves no half file under its name" ):
    src, dst, state = pair( { "a.txt": "old" } )
    run( src, dst, state )
    ( src / "a.txt" ).write_text( "new contents" )
    real = S.read_into
    S.read_into = lambda *a, **k: ( _ for _ in ( ) ).throw( KeyboardInterrupt )
    try:
        run( src, dst, state )
        assert False, "the interruption went through"
    except KeyboardInterrupt:
        pass
    finally:
        S.read_into = real
    assert ( dst / "a.txt" ).read_text() == "old" and not [ p for p in os.listdir( dst ) if "errand-part" in p ]


if test( "a chunk crosses packed with what both sides read" ):
    data = b"errand " * 1000
    for accepted in ( S.codecs(), [ "d" ] ):
        packed = S.pack( data, accepted )
        assert len( packed ) < len( data ) and S.unpack( packed ) == data
    assert S.pack( data, [ "d" ] )[ : 1 ] == b"d"


# -- zones ( ADR 0006 ): where the other side writes ---------------------------------

def zoned( ):
    return S.Selection( [ "__pycache__" ], zones = [ S.Zone( "/results", "back" ), S.Zone( "build", "build" ),
                                                     S.Zone( "/errand-outputs", "errand" ) ] )


if test( "a zone is neither sent into, nor deleted in, nor found changed" ):
    sel = zoned()
    src, dst, state = pair( { "m.py": "m", "results/old.txt": "here", "pkg/build/o": "local build" } )
    run( src, dst, state, sel )
    assert not ( dst / "results" ).exists() and not ( dst / "pkg/build" ).exists(), "nothing crosses into a zone"
    tree( { "results/r.txt": "written there", "pkg/build/o": "built there", "errand-outputs/runs/x": "x",
            "sub/results/r.txt": "not a zone: anchored" }, dst )
    r, said = run( src, dst, state, sel )
    assert [ f.key for f in r.findings ] == [ "sub", "sub/results", "sub/results/r.txt" ], r.findings
    assert ( dst / "results/r.txt" ).read_text() == "written there" and ( dst / "pkg/build/o" ).exists()
    assert ( dst / "errand-outputs/runs/x" ).exists() and not ( dst / "sub" ).exists()
    r, said = run( src, dst, state, sel )
    assert not r and not r.findings and not said, ( r, said )


if test( "a directory left because it holds a zone says which" ):
    sel = zoned()
    src, dst, state = pair( { "m.py": "m", "pkg/m.py": "m" } )
    run( src, dst, state, sel )
    tree( { "pkg/build/o": "built there" }, dst )
    shutil.rmtree( src / "pkg" )
    r, said = run( src, dst, state, sel )
    assert r.kept == [ "pkg" ] and r.deleted == [ "pkg/m.py" ], r
    assert said == [ "  pkg: left on the copy, it holds build ( build zone )" ], said


if test( "the agent's check finds a change when it starts or goes; the next sync says it, with when it was seen" ):
    sel = zoned()
    src, dst, state = pair( { "a.txt": "a", "b.txt": "b" } )
    run( src, dst, state, sel )
    ( dst / "a.txt" ).write_text( "edited by a run" )
    seen = ( dst / "a.txt" ).stat().st_mtime_ns
    ( dst / "results" ).mkdir()
    ( dst / "results/r.txt" ).write_text( "a zone: no finding" )
    found = S.check( dst, sel, state / "dst.json" )
    assert [ ( f.key, f.what, f.mtime_ns ) for f in found ] == [ ( "a.txt", "changed", seen ) ], found
    later = seen + 10**9
    ( dst / "a.txt" ).write_text( "edited again" )
    os.utime( dst / "a.txt", ns = ( later, later ) )
    ( dst / "b.txt" ).unlink()
    found = S.check( dst, sel, state / "dst.json" )
    assert [ ( f.key, f.mtime_ns ) for f in found ] == [ ( "a.txt", seen ), ( "b.txt", 0 ) ], \
        "found when first seen, and kept until a sync says it"
    r, said = run( src, dst, state, sel, check = False )
    assert [ f.key for f in r.findings ] == [ "a.txt", "b.txt" ] and "zones ( /results ( back ), build ( build ) )" in said[ -1 ], said
    same_trees( src, dst, sel )
    assert not S.check( dst, sel, state / "dst.json" ), "said and put back: nothing pending"


if test( "a zone of no known kind is refused; a path is in a zone through its parents" ):
    try:
        S.Selection( zones = [ S.Zone( "x", "scratch" ) ] )
        assert False
    except S.SyncError as e:
        assert "back" in str( e )
    sel = zoned()
    assert sel.zone_under( "results/a/b.txt" ) == S.Zone( "/results", "back" )
    assert sel.zone_under( "src/build/x.o" ) == S.Zone( "build", "build" ) and sel.zone_under( "src/x.o" ) is None


if test( "the project declares its zones; a push's selection adds errand's outputs and what layers build" ):
    import errand
    from errand import config as C
    from errand.layers import gateways
    try:
        for bad in ( [ "results" ], { "results": "scratch" }, { "../up": "back" } ):
            try:
                errand.configure( zones = bad )
                assert False, bad
            except ( TypeError, ValueError ):
                pass
        errand.configure( zones = { "/results": "back", "cache": "build" } )
        sel = gateways.selection( Path( tempfile.mkdtemp() ) )
        assert sel.zone( "results" ) == S.Zone( "/results", "back" ) and sel.zone( "a/cache" ).kind == "build"
        assert sel.zone( "errand-outputs" ).kind == "errand" and sel.zone( ".venv" ).kind == "build"
        assert sel.skips( "pkg/__pycache__", "__pycache__" ) and sel.zone( "pkg/__pycache__" ) is None
    finally:
        C.reset()


if test( "a runner says where its tool writes: its zones join the project's, which has the last word" ):
    import errand
    from errand import config as C
    from errand.layers import gateways
    try:
        try:
            errand.runners[ "cov" ] = errand.Pytest( zones = { "/htmlcov": "elsewhere" } )
            assert False, "a zone of no known kind was taken"
        except ValueError as err:
            assert "runners[ 'cov' ].zones" in str( err ), err
        errand.runners.replace( errand.Pytest( zones = { "/htmlcov": "back", "/.coverage-data": "back" } ) )
        errand.runners.replace( errand.Cargo( target_dir = None, zones = { "/target/criterion": "back" } ) )
        errand.configure( zones = { "/.coverage-data": "build" } )
        assert C.zones()[ "/htmlcov" ] == "back" and C.zones()[ "/.coverage-data" ] == "build"
        assert gateways.back_zones() == [ "htmlcov", "target/criterion" ], "brought back after a command"
        sel = gateways.selection( Path( tempfile.mkdtemp() ) )
        assert sel.zone( "htmlcov" ) == S.Zone( "/htmlcov", "back" )
        assert sel.zone( "target/criterion" ).kind == "back" and sel.zone( "target" ).kind == "build", \
               "brought back from inside what is built"
    finally:
        C.reset()


if test( "a zone may name the environment: its build directory, its name" ):
    import errand
    from errand import config as C
    from errand.layers import gateways
    try:
        errand.envs[ "gpu" ] = errand.Env( [ ] )
        errand.envs[ "cpu" ] = errand.Env( [ ] )
        errand.runners.replace( errand.Cargo( zones = { "/{build_dir}/target/criterion": "back" } ) )
        errand.configure( zones = { "/results/{env}": "back" } )
        assert gateways.back_zones( "gpu" ) == [ "build/gpu/target/criterion", "results/gpu" ]
        # without an environment, every one's: they share the copy over there
        assert gateways.back_zones() == [ "build/cpu/target/criterion", "build/gpu/target/criterion",
                                          "results/cpu", "results/gpu" ]
        sel = gateways.selection( Path( tempfile.mkdtemp() ) )
        assert sel.zone( "build/gpu/target/criterion" ).kind == "back"
    finally:
        C.reset()


if test( "a push never deletes the records of runs only the copy has, wherever their tree is" ):
    src, dst, state = pair( { "src.py": "s", "runs/a/2026-x/result.yaml": "here too\n" } )
    run( src, dst, state )
    # Runs made over there, in a `--out` tree of the project: never brought back here.
    tree( { "runs/a/2026-y/result.yaml": "status: PASS\n", "runs/a/2026-y/stdout.txt": "o", "runs/a/2026-y/fig/f.png": "p",
            "runs/a/2026-z/output.txt": "still going", "runs/a/summary.yaml": "runs: 2\n", "runs/a/latest": ( "->", "2026-y" ),
            "stray.txt": "by hand" }, dst )
    r, said = run( src, dst, state )
    for k in ( "2026-y/result.yaml", "2026-y/stdout.txt", "2026-y/fig/f.png", "2026-z/output.txt", "summary.yaml" ):
        assert ( dst / "runs/a" / k ).exists(), ( k, r )
    assert os.path.islink( dst / "runs/a/latest" )
    assert "runs/a/2026-y/result.yaml" in r.kept_runs and not any( k.startswith( "runs/" ) for k in r.deleted ), r
    assert not any( "runs/" in s for s in said ), said                 # a run made there is no finding
    assert "stray.txt" in r.deleted, "what is not a run's goes, as before"
    # Gone from the source here, a run the copy holds stays there too.
    shutil.rmtree( src / "runs" )
    r, _ = run( src, dst, state )
    assert ( dst / "runs/a/2026-x/result.yaml" ).exists() and not any( k.startswith( "runs/" ) for k in r.deleted ), r


if test( "an rsync push is told the same: the run directories over there, protected" ):
    from errand.layers import gateways as G
    import subprocess as sp
    root = tree( { "runs/a/r1/result.yaml": "x", "runs/a/r1/f.png": "p", "deep/x/r2/stderr.txt": "e", ".git/result.yaml": "no" } )
    found = sp.run( [ "sh", "-c", G._RUNS_LISTING, "_", str( root ), "result.yaml", "stderr.txt" ],
                    capture_output = True, text = True, check = True ).stdout.split()
    assert sorted( found ) == [ "./deep/x/r2/stderr.txt", "./runs/a/r1/result.yaml" ], found
    rules = G.protect_runs( [ "runs/a/r1/result.yaml", "deep/x/r2/stderr.txt" ] )
    assert "/runs/a/r1/***" in rules and "/deep/x/r2/***" in rules and "/runs/a/summary.yaml" in rules, rules
    assert "/runs/a/latest" in rules and "/summary.yaml" in rules


# -- cache zones ( ADR 0012 ): both sides add, nobody replaces ------------------------

def cached( ):
    return S.Selection( [ "__pycache__" ], zones = [ S.Zone( "/data", "cache" ), S.Zone( "memo", "cache" ),
                                                     S.Zone( "/results", "back" ) ] )


if test( "a cache is pushed: what the copy lacks crosses, what is only there stays and is no finding" ):
    sel = cached()
    src, dst, state = pair( { "a.py": "a", "data/s1.h5": "sino 1", "pkg/memo/k1": "m1" } )
    r, said = run( src, dst, state, sel )
    assert sorted( r.sent ) == [ "a.py", "data/s1.h5", "pkg/memo/k1" ] and not said, ( r, said )
    tree( { "data/s2.h5": "downloaded there", "pkg/memo/k2": "computed there", "data/sub/x": "deep" }, dst )
    r, said = run( src, dst, state, sel )
    assert not r and not r.findings and not r.conflicts and not said, ( r, said )
    assert ( dst / "data/s2.h5" ).read_text() == "downloaded there" and ( dst / "pkg/memo/k2" ).exists()
    assert ( dst / "data/sub/x" ).exists()
    # removed here: never removed there
    ( src / "data/s1.h5" ).unlink()
    r, said = run( src, dst, state, sel )
    assert not r.deleted and ( dst / "data/s1.h5" ).read_text() == "sino 1", r
    # and the agent's check finds nothing in a cache either
    assert S.check( dst, sel, state / "dst.json" ) == [ ]


if test( "a file of a cache with other contents on each side is a conflict: said, neither replaced" ):
    sel = cached()
    src, dst, state = pair( { "data/s.h5": "here" } )
    tree( { "data/s.h5": "there, not the same", "data/t.h5": "same" }, dst )
    tree( { "data/t.h5": "same" }, src )
    os.utime( src / "data/t.h5", ns = ( 1, 1 ) )
    r, said = run( src, dst, state, sel )
    assert r.conflicts == [ ( "data/s.h5", "/data ( cache zone )" ) ] and not r.sent and not r.touched, ( r, said )
    assert ( dst / "data/s.h5" ).read_text() == "there, not the same"
    assert os.stat( dst / "data/t.h5" ).st_mtime_ns != 1, "the same contents: not even touched"
    assert len( said ) == 1 and "data/s.h5: not the same here and on the copy" in said[ 0 ], said
    # said again at the next sync, until one side is renamed or removed
    r, said = run( src, dst, state, sel )
    assert r.conflicts and said, said


if test( "a cache file written over there after the walk is not replaced: the guard looks at the target" ):
    sel = cached()
    src, dst, state = pair( { "a.py": "a" } )
    run( src, dst, state, sel )
    tree( { "data/new.h5": "here" }, src )
    tree( { "data/new.h5": "a run wrote it there meanwhile" }, dst )
    r, said = run( src, dst, state, sel, check = False )        # the trusted manifest does not know it
    assert r.conflicts == [ ( "data/new.h5", "/data ( cache zone )" ) ] and "data/new.h5" not in r.sent, ( r, said )
    assert ( dst / "data/new.h5" ).read_text() == "a run wrote it there meanwhile"
    assert not r.spared, "nothing moved aside: it is the cache's"


if test( "a cache zone is declared like the others; one path is brought back after each command" ):
    import errand
    from errand import config as C
    from errand.layers import gateways
    try:
        errand.configure( zones = { "/data-cache": "cache", "memo": "cache", "/c/*": "cache", "/results": "back" } )
        assert gateways.cache_zones() == [ "data-cache", "errand-cache" ] and gateways.back_zones() == [ "results" ]
        sel = gateways.selection( Path( tempfile.mkdtemp() ) )
        assert sel.zone( "data-cache" ) == S.Zone( "/data-cache", "cache" ) and not sel.skips( "data-cache", "data-cache" )
        assert sel.cached( "data-cache/a/b.h5" ) == S.Zone( "/data-cache", "cache" ) and sel.cached( "a.py" ) is None
        assert sel.cached( "x/memo/k" ).kind == "cache" and sel.skips( "x/.venv", ".venv" )
    finally:
        C.reset()


if test( "errand.cache_dir: the zone's path from the project root, made if missing" ):
    import errand
    root = Path( tempfile.mkdtemp() ).resolve()
    ( root / "errand-project.py" ).write_text( "" )
    ( root / "sub/deeper" ).mkdir( parents = True )
    old = os.getcwd()
    try:
        os.chdir( root / "sub/deeper" )
        assert errand.cache_dir( "/data-cache" ) == root / "data-cache" and ( root / "data-cache" ).is_dir()
        assert errand.cache_dir( "cache/esrf" ) == root / "cache/esrf"
        for bad in ( "/", "../x", "/c/*" ):
            try:
                errand.cache_dir( bad )
                assert False, bad
            except ValueError:
                pass
    finally:
        os.chdir( old )
