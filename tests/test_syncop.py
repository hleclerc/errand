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
