"""A push by manifest through an agent ( ADR 0006 ): on this machine, with `local` agents, the same
protocol as over ssh. Two agents on one copy are two machines that share a file system."""
import contextlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from errand import test
from errand import sync as S


@contextlib.contextmanager
def scratch( ):
    d = tempfile.mkdtemp( dir = "/tmp" )       # a unix socket's path must be short
    try:
        yield Path( d )
    finally:
        shutil.rmtree( d, ignore_errors = True )


def agent( d, keep = 5 ):
    from errand import agents
    os.environ[ "ERRAND_AGENT" ] = "direct"
    return agents.open( { "kind": "local", "dir": str( d ), "keep_alive": keep } )


def tree( root, spec ):
    for rel, text in spec.items():
        p = Path( root ) / rel
        p.parent.mkdir( parents = True, exist_ok = True )
        p.write_text( text )
    return Path( root )


def push( conn, src, dst, sel = None, **kw ):
    from errand.agents import syncop
    said = [ ]
    r = syncop.push( conn, src, dst, sel or S.Selection( [ "__pycache__" ], zones = [ S.Zone( "/results", "back" ) ] ),
                     say = said.append, **kw )
    return r, said


def same( a, b ):
    ma, mb = S.scan( a, S.Selection( [ "__pycache__", "results" ] ) ), S.scan( b, S.Selection( [ "__pycache__", "results" ] ) )
    assert { k: ( e.kind, e.digest, e.mtime_ns, e.exe ) for k, e in ma.items() } == \
           { k: ( e.kind, e.digest, e.mtime_ns, e.exe ) for k, e in mb.items() }


if test( "a push through the agent: the tree crosses, then nothing does; zones are left alone" ):
    with scratch() as d:
        src = tree( d / "src", { "a.py": "a", "pkg/b.py": "b", "results/r.txt": "here" } )
        os.symlink( "a.py", src / "ln" )
        dst = d / "copy"
        conn = agent( d / "ag" )
        r, said = push( conn, src, dst )
        assert sorted( r.sent ) == [ "a.py", "pkg/b.py" ] and not said, ( r, said )
        same( src, dst )
        assert os.readlink( dst / "ln" ) == "a.py" and ( dst / S.COPY_STATE ).exists()
        tree( dst, { "results/out.txt": "written there" } )
        ( src / "a.py" ).write_text( "A" )
        ( src / "pkg/b.py" ).unlink()
        r, said = push( conn, src, dst )
        assert r.sent == [ "a.py" ] and r.deleted == [ "pkg/b.py" ] and not said, ( r, said )
        assert ( dst / "results/out.txt" ).exists() and not ( dst / "results/r.txt" ).exists()
        r, said = push( conn, src, dst )
        assert not r and not said, r


if test( "within an agent's life the copy is trusted; a new agent walks it, and says what changed" ):
    with scratch() as d:
        src = tree( d / "src", { "a.py": "a", "b.py": "b" } )
        dst = d / "copy"
        conn = agent( d / "ag" )
        push( conn, src, dst )
        ( dst / "a.py" ).write_text( "edited over there" )
        r, said = push( conn, src, dst )
        assert not r.findings and ( dst / "a.py" ).read_text() == "edited over there", \
            "the same agent trusts its manifest: no walk"
        other = agent( d / "ag2" )
        r, said = push( other, src, dst )
        assert [ ( f.key, f.what ) for f in r.findings ] == [ ( "a.py", "changed" ) ] and r.sent == [ "a.py" ], ( r, said )
        assert "a.py: changed on the copy" in said[ 0 ] and ( dst / "a.py" ).read_text() == "a"


if test( "two machines on one file system: one copy, one manifest, nothing found that errand did" ):
    with scratch() as d:
        src = tree( d / "src", { "a.py": "a", "pkg/b.py": "b" } )
        dst = d / "copy"
        lmo, n22 = agent( d / "lmo" ), agent( d / "n22" )
        push( lmo, src, dst )
        r, said = push( n22, src, dst )
        assert not r and not r.findings and not said, ( "what the other pushed is errand's", r, said )
        ( src / "a.py" ).write_text( "A" )
        push( lmo, src, dst )
        r, said = push( n22, src, dst )
        assert not r and not said, ( r, said )
        assert not [ p for p in os.listdir( dst ) if p.startswith( S.COPY_STATE ) and p != S.COPY_STATE ], "the lock went"


if test( "a case-only clash, toward a copy that does not tell case apart, is refused before anything crosses" ):
    with scratch() as d:
        dst = d / "copy"
        dst.mkdir()
        if S.case_insensitive( dst ):
            src = d / "src"
            src.mkdir()
            from errand.agents import syncop
            m = S.Manifest( { "A.txt": S.Entry( "f" ), "a.txt": S.Entry( "f" ) } )
            real = S.scan
            S.scan = lambda root, *a, **k: m if Path( root ) == src else real( root, *a, **k )
            try:
                push( agent( d / "ag" ), src, dst )
                assert False, "no clash said"
            except S.SyncError as e:
                assert "A.txt / a.txt" in str( e )
            finally:
                S.scan = real
            assert not ( dst / "A.txt" ).exists()


if test( "the agent checks the copy when it goes; the next push says what it found, and when" ):
    with scratch() as d:
        from errand.agents import client
        src = tree( d / "src", { "a.py": "a" } )
        dst = d / "copy"
        conn = agent( d / "ag", keep = 1 )
        push( conn, src, dst )
        ( dst / "a.py" ).write_text( "edited by a run" )
        seen = ( dst / "a.py" ).stat().st_mtime_ns
        call = conn.open( { "op": "stop" } )
        call.reply()
        deadline = time.time() + 20
        while time.time() < deadline and not json.loads( ( dst / S.COPY_STATE ).read_text() ).get( "found" ):
            time.sleep( 0.1 )
        found = json.loads( ( dst / S.COPY_STATE ).read_text() )[ "found" ]
        assert [ ( f[ 0 ], f[ 1 ], f[ 2 ] ) for f, _ in found ] == [ ( "a.py", "changed", seen ) ], found
        from errand import agents
        agents._open.clear()
        ( dst / "a.py" ).write_text( "edited again" )          # after the check: the first sight is what is said
        r, said = push( agent( d / "ag" ), src, dst )
        assert [ ( f.key, f.mtime_ns ) for f in r.findings ] == [ ( "a.py", seen ) ] and r.sent == [ "a.py" ], r


if test( "a pull brings back what is under the paths asked for, deletes nothing here, skips what it has" ):
    with scratch() as d:
        from errand.agents import syncop
        there = tree( d / "copy", { "errand-outputs/runs/r1/out.txt": "1", "errand-outputs/runs/r1/sub/big.bin": "x" * 100000,
                                    "errand-outputs/runs/r2/out.txt": "2", "results/a.csv": "a", "src.py": "s" } )
        os.symlink( "r1", there / "errand-outputs/runs/latest" )
        here = tree( d / "here", { "errand-outputs/runs/r0/old.txt": "mine", "results/local.csv": "mine" } )
        conn = agent( d / "ag" )
        said = [ ]
        r = syncop.pull( conn, there, here, [ "errand-outputs/runs/r1", "errand-outputs/runs/latest", "results", "nothing/here" ],
                         say = said.append )
        assert sorted( r.sent ) == [ "errand-outputs/runs/r1/out.txt", "errand-outputs/runs/r1/sub/big.bin", "results/a.csv" ], r
        assert ( here / "errand-outputs/runs/r1/sub/big.bin" ).read_text() == "x" * 100000
        assert os.readlink( here / "errand-outputs/runs/latest" ) == "r1"
        assert ( here / "results/local.csv" ).exists() and ( here / "errand-outputs/runs/r0/old.txt" ).exists(), "nothing deleted"
        assert not ( here / "errand-outputs/runs/r2" ).exists() and not ( here / "src.py" ).exists()
        assert ( here / "results/a.csv" ).stat().st_mtime_ns == ( there / "results/a.csv" ).stat().st_mtime_ns
        r = syncop.pull( conn, there, here, [ "errand-outputs/runs/r1", "results" ], say = said.append )
        assert not r, ( "nothing new", r )
        ( there / "results/a.csv" ).write_text( "b" )               # same size: hashed, then sent
        later = time.time_ns() + 10**9
        os.utime( there / "errand-outputs/runs/r1/out.txt", ns = ( later, later ) )     # touched only
        r = syncop.pull( conn, there, here, [ "errand-outputs/runs/r1", "results" ], say = said.append )
        assert r.sent == [ "results/a.csv" ] and r.touched == [ "errand-outputs/runs/r1/out.txt" ], r
        assert ( here / "results/a.csv" ).read_text() == "b"
        r = syncop.pull( conn, there, here, [ "errand-outputs/runs/latest" ], links = False, say = said.append )
        assert not said, said


if test( "what a push would lose over there is moved aside, even between two walks; what errand wrote is not" ):
    with scratch() as d:
        src = tree( d / "src", { "a.py": "a", "b.py": "b", "c.py": "c" } )
        dst = d / "copy"
        conn = agent( d / "ag" )
        r, _ = push( conn, src, dst )
        assert not r.spared, r
        ( dst / "a.py" ).write_text( "edited by a run over there" )      # the same agent: no walk sees it
        tree( dst, { "notes.txt": "written over there, outside the zones" } )
        ( src / "a.py" ).write_text( "A" )
        ( src / "b.py" ).write_text( "B" )
        r, said = push( conn, src, dst )
        assert sorted( r.sent ) == [ "a.py", "b.py" ] and not r.findings, r
        assert [ ( k, w ) for k, w, _ in r.spared ] == [ ( "a.py", "changed" ) ], r.spared
        kept = dst / r.spared_in
        assert ( kept / "a.py" ).read_text() == "edited by a run over there" and ( dst / "a.py" ).read_text() == "A"
        assert not ( kept / "b.py" ).exists(), "what errand wrote is not kept"
        assert any( "a.py: changed on the copy" in s and "kept" in s for s in said ), said
        assert ( dst / "notes.txt" ).exists(), "trusted: a file nobody pushed over is not seen until a walk"
        other = agent( d / "ag2" )                                     # a new agent walks: it is found, and kept
        r, said = push( other, src, dst )
        assert [ ( f.key, f.what ) for f in r.findings ] == [ ( "notes.txt", "added" ) ], r
        assert [ k for k, _, _ in r.spared ] == [ "notes.txt" ] and not ( dst / "notes.txt" ).exists()
        assert ( dst / r.spared_in / "notes.txt" ).read_text() == "written over there, outside the zones"
        assert any( "moved aside" in s for s in said ) and any( "1 of the files above" in s for s in said ), said
        assert S.scan( dst, S.Selection() ).get( r.spared_in.split( "/" )[ 0 ] ) is None, "never part of the copy"
        r, said = push( other, src, dst )
        assert not r and not said, ( r, said )


if test( "a first sync over a copy errand never wrote keeps what it removes or replaces, not what it only touches" ):
    with scratch() as d:
        src = tree( d / "src", { "a.py": "a", "same.py": "s" } )
        dst = tree( d / "copy", { "a.py": "an older a", "same.py": "s", "old.py": "only there", "results/r.txt": "zone" } )
        r, said = push( agent( d / "ag" ), src, dst )
        kept = dst / r.spared_in
        assert sorted( k for k, _, _ in r.spared ) == [ "a.py", "old.py" ], r.spared
        assert ( kept / "a.py" ).read_text() == "an older a" and ( kept / "old.py" ).read_text() == "only there"
        assert not ( kept / "same.py" ).exists() and ( dst / "results/r.txt" ).exists()
        assert any( "old.py: not written by errand" in s for s in said ), said


if test( "a pull of run trees brings a run back once finished, and never deletes here" ):
    with scratch() as d:
        from errand.agents import syncop
        runs = "errand-outputs/runs/t.py/case"
        there = tree( d / "copy", { f"{runs}/done/result.yaml": "status: PASS\n", f"{runs}/done/output.txt": "o",
                                    f"{runs}/going/output.txt": "half", f"{runs}/going/stderr.txt": "e",
                                    f"{runs}/summary.yaml": "runs: 1\n" } )
        ( there / runs / "fresh" ).mkdir()
        os.symlink( "going", there / runs / "latest" )
        here = tree( d / "here", { f"{runs}/mine/result.yaml": "status: PASS\n", f"{runs}/clash": "a file here" } )
        ( there / runs / "clash" ).mkdir()
        ( there / runs / "clash" / "result.yaml" ).write_text( "x" )
        conn = agent( d / "ag" )
        said = [ ]
        syncop.pull( conn, there, here, [ runs ], say = said.append, finished_only = True )
        assert ( here / runs / "done" / "output.txt" ).exists()
        # Under way, or just made: left over there, and the `latest` that leads to one with it.
        assert not ( here / runs / "going" ).exists() and not ( here / runs / "fresh" ).exists()
        assert not ( here / runs / "latest" ).is_symlink()
        # Nothing here goes: not a run of its own, not a file where the other side has a directory.
        assert ( here / runs / "mine" / "result.yaml" ).exists()
        assert ( here / runs / "clash" ).read_text() == "a file here" and any( "clash" in s for s in said ), said
        # Once its record is written, the run comes back whole.
        ( there / runs / "going" / "result.yaml" ).write_text( "status: PASS\n" )
        syncop.pull( conn, there, here, [ runs ], say = said.append, finished_only = True )
        assert ( here / runs / "going" / "output.txt" ).read_text() == "half"
        assert os.readlink( here / runs / "latest" ) == "going"


if test( "a cache through the agent ( ADR 0012 ): pushed when missing there, kept there, never replaced" ):
    with scratch() as d:
        sel = S.Selection( [ "__pycache__" ], zones = [ S.Zone( "/data", "cache" ) ] )
        src = tree( d / "src", { "a.py": "a", "data/s1.h5": "sino 1" } )
        dst = d / "copy"
        conn = agent( d / "ag" )
        r, said = push( conn, src, dst, sel )
        assert sorted( r.sent ) == [ "a.py", "data/s1.h5" ] and not said, ( r, said )
        tree( dst, { "data/s2.h5": "downloaded there", "data/s1.h5": "sino 1, other bits" } )
        tree( src, { "data/s3.h5": "new here" } )
        ( src / "data/s1.h5" ).write_text( "sino 1" )            # the same file, touched here
        r, said = push( conn, src, dst, sel, check = True )
        assert r.sent == [ "data/s3.h5" ] and not r.findings and not r.deleted and not r.spared, ( r, said )
        assert r.conflicts == [ ( "data/s1.h5", "/data ( cache zone )" ) ] and "data/s1.h5" in said[ 0 ], said
        assert ( dst / "data/s1.h5" ).read_text() == "sino 1, other bits" and ( dst / "data/s2.h5" ).exists()
        # written there after the agent walked it: the guard at the target keeps it
        tree( src, { "data/s4.h5": "here" } )
        tree( dst, { "data/s4.h5": "there" } )
        r, said = push( conn, src, dst, sel )
        assert ( "data/s4.h5", "/data ( cache zone )" ) in r.conflicts and ( dst / "data/s4.h5" ).read_text() == "there"


if test( "a cache pulled back: only what is missing here comes, a different file here is a conflict" ):
    from errand.agents import syncop
    with scratch() as d:
        there = tree( d / "copy", { "data/s1.h5": "same", "data/s2.h5": "computed there", "data/k/x": "deep",
                                    "data/clash.h5": "theirs" } )
        here = tree( d / "here", { "data/s1.h5": "same", "data/clash.h5": "mine", "data/only-here": "h" } )
        os.utime( here / "data/s1.h5", ns = ( 1, 1 ) )
        conn = agent( d / "ag" )
        said = [ ]
        r = syncop.pull( conn, there, here, [ "data" ], say = said.append, keep = True )
        assert sorted( r.sent ) == [ "data/k/x", "data/s2.h5" ] and not r.touched, r
        assert ( here / "data/clash.h5" ).read_text() == "mine" and ( here / "data/only-here" ).exists()
        assert os.stat( here / "data/s1.h5" ).st_mtime_ns == 1
        assert r.conflicts == [ ( "data/clash.h5", "data ( cache zone )" ) ] and "data/clash.h5" in said[ 0 ], said


if test( "a cache file a run wrote there, and that came back here, is not sent again: its hash is asked" ):
    with scratch() as d:
        sel = S.Selection( [ "__pycache__" ], zones = [ S.Zone( "/data", "cache" ) ] )
        src = tree( d / "src", { "a.py": "a" } )
        dst = d / "copy"
        conn = agent( d / "ag" )
        push( conn, src, dst, sel )
        tree( dst, { "data/big.h5": "downloaded there" * 1000 } )      # the run's, unknown to the manifest
        tree( src, { "data/big.h5": "downloaded there" * 1000 } )      # ... brought back by the pull
        r, said = push( conn, src, dst, sel )
        assert not r.sent and not r.conflicts and not said, ( r, said )
        known = S.load( dst / S.COPY_STATE )
        assert "data/big.h5" in known and known[ "data/big.h5" ].digest, "recorded: not hashed at every push"
        r, said = push( conn, src, dst, sel )
        assert not r.sent and not said, ( r, said )


TAG = "Signature: 8a477f597d28d172789f06886806bc55\n"

if test( "through the agent: a run's directory is said once; a tagged one never ( ADR 0019 )" ):
    with scratch() as d:
        sel = S.Selection( [ "__pycache__" ], zones = [ S.Zone( "*.so", "build" ) ] )
        src = tree( d / "src", { "a.py": "a", "kern/k.py": "k" } )
        dst = d / "copy"
        conn = agent( d / "ag" )
        push( conn, src, dst, sel )
        tree( dst, { "kern/x.so": "built there", "cat/CACHEDIR.TAG": TAG, "cat/y.so": "built there" } )
        shutil.rmtree( src / "kern" )
        r, said = push( conn, src, dst, sel, check = True )
        assert r.kept == [ "kern" ] and len( said ) == 1 and said[ 0 ].startswith( "  kern: no longer in the project" ), said
        r, said = push( conn, src, dst, sel, check = True )
        assert not said, said
        conn.close()
        conn = agent( d / "ag2" )              # a new agent walks the copy: still nothing to say
        r, said = push( conn, src, dst, sel )
        assert not said and ( dst / "cat/y.so" ).exists() and ( dst / "kern/x.so" ).exists(), said


if test( "through the agent: runs made there are told once; removed there by hand, they leave the manifest" ):
    with scratch() as d:
        sel = S.Selection( [ "__pycache__" ] )
        src = tree( d / "src", { "a.py": "a" } )
        dst = d / "copy"
        conn = agent( d / "ag" )
        push( conn, src, dst, sel )
        tree( dst, { "runs/p/2026-y/result.yaml": "status: PASS\n", "runs/p/2026-y/stdout.txt": "o" } )
        r, _ = push( conn, src, dst, sel, check = True )
        assert r.kept_runs == [ "runs/p/2026-y/result.yaml", "runs/p/2026-y/stdout.txt" ], r
        r, _ = push( conn, src, dst, sel )
        assert r.kept_runs == [ ] and ( dst / "runs/p/2026-y/result.yaml" ).exists(), "said once"
        shutil.rmtree( dst / "runs" )          # by hand, while the agent takes its manifest for the disk
        r, _ = push( conn, src, dst, sel )
        assert r.kept_runs == [ ], r
        known = S.load( dst / S.COPY_STATE )
        assert not any( k.startswith( "runs/p/2026-y" ) for k in known ) and "runs/p/2026-y" not in known.theirs, known
