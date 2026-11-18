"""errand on a machine it was not installed on: its sources travel, and it starts on a Python found -- or made -- there.

What can be checked here is checked here: the commands that cross, the search on this machine, the shipped copy
started the way it is started over there. The making itself fetches uv and a Python, and is exercised by hand on a
real machine ( `errand -v run --env <ssh env>` with no python3 >= 3.8 over there ).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from errand import test

from errand import bootstrap as B, layers as L


def run_sh( line, home, path = None ):
    env = { **{ k: v for k, v in os.environ.items() if k != B.ENV }, "HOME": str( home ) }
    if path is not None:
        env[ "PATH" ] = path
    return subprocess.run( [ "/bin/sh", "-c", line ], capture_output = True, text = True, env = env, timeout = 120 )


if test( "errand itself is told apart from any other command" ):
    assert B.is_errand( [ "python", "-m", "errand", "run" ] )
    assert B.is_errand( [ "python3", "-m", "errand" ] )
    assert B.is_errand( [ sys.executable, "-m", "errand", "list" ] )
    assert not B.is_errand( [ "python", "-m", "pytest" ] )
    assert not B.is_errand( [ "make", "-m", "errand" ] )


if test( "what crosses: the interpreter a layer chooses, else one searched for where it starts" ):
    cmd = L.Command( [ "python", "-m", "errand", "run", "a b.py" ], { "K": "v" } )
    chosen = B.command( cmd, [ L.Micromamba( "x" ) ], "/home/me" )
    assert chosen.argv == [ "python", f"/home/me/{B.boot_rel()}", "run", "a b.py" ] and chosen.env == { "K": "v" }

    searched = B.command( cmd, [ L.Vars( { } ) ], "/home/me", "python3.11" )
    assert searched.argv[ : 2 ] == [ "sh", "-c" ] and searched.argv[ 3 : ] == [ "sh", "run", "a b.py" ]
    assert "want=python3.11" in searched.argv[ 2 ] and B.boot_rel() in searched.argv[ 2 ]

    walled = B.command( cmd, [ L.Docker( "img" ) ], "/home/me", "python3" )
    assert walled.argv == [ "python3", "-m", "errand", "run", "a b.py" ], "the home directory is not in the container"

    other = L.Command( [ "make", "all" ], { } )
    assert B.command( other, [ ], "/home/me" ) is other


if test( "the search finds a Python recent enough on this machine" ):
    with tempfile.TemporaryDirectory() as home:
        got = run_sh( B.find_line( "no-such-python" ), home )
        assert got.returncode == 0, got.stderr
        python = B._said( "ERRAND_PYTHON", got.stdout )
        assert python and os.path.isabs( python ), got.stdout
        ok = subprocess.run( [ python, "-c", "import sys; print( sys.version_info >= ( 3, 8 ) )" ],
                             capture_output = True, text = True )
        assert ok.stdout.strip() == "True"
        assert not ( Path( home ) / B.BASE / "python" ).exists(), "found: nothing is made"


if test( "nothing to be found and nothing to make one with: it says so, and fails" ):
    with tempfile.TemporaryDirectory() as home:
        # A shell and the tools the search uses, and nothing else: no python, no uv, no conda, no curl.
        bare = Path( home ) / "bin"
        bare.mkdir()
        for tool in ( "sh", "mkdir", "rm", "rmdir", "sleep" ):
            ( bare / tool ).symlink_to( shutil.which( tool ) )
        got = run_sh( B.find_line( "python3" ), home, path = str( bare ) )
        assert got.returncode != 0 and "ERRAND_PYTHON" not in got.stdout, got.stdout
        assert "making one for errand alone" in got.stderr, got.stderr
        assert "no curl nor wget" in got.stderr, got.stderr
        assert not ( Path( home ) / B.BASE / "python.lock" ).exists(), "the lock is let go"


def started_copy( cache_env = None ):
    """The shipped copy, put where errand's per-user directory is, started as over there."""
    with tempfile.TemporaryDirectory() as home:
        cache = Path( cache_env ) if cache_env else Path( home ) / B.BASE
        copy = cache / B.src_rel() / "errand"
        shutil.copytree( B.PACKAGE, copy, ignore = shutil.ignore_patterns( "__pycache__" ) )
        cmd = B.command( L.Command( [ "python", "-m", "errand", "--version" ], { } ), [ ], str( cache ) )
        env = { k: v for k, v in os.environ.items() if k not in ( "PYTHONPATH", B.ENV ) }
        got = subprocess.run( cmd.argv, capture_output = True, text = True, cwd = home, timeout = 120,
                              env = { **env, "HOME": home, **( { B.ENV: cache_env } if cache_env else { } ) } )
        assert got.returncode == 0, got.stderr
        assert str( copy ) in got.stdout, got.stdout


if test( "the shipped copy starts the way it starts over there" ):
    started_copy()


if test( "ERRAND_CACHE_DIR moves errand's per-user directory" ):
    with tempfile.TemporaryDirectory() as elsewhere:
        started_copy( elsewhere )
        old = os.environ.get( B.ENV )
        os.environ[ B.ENV ] = elsewhere
        try:
            assert B.local_cache() == Path( elsewhere )
            from errand.vm import places
            from errand.agents import upstream
            assert places.live_dir() == Path( elsewhere ) / "vm"
            assert upstream.hub_dir().parent == Path( elsewhere )
        finally:
            if old is None:
                os.environ.pop( B.ENV )
            else:
                os.environ[ B.ENV ] = old
    with tempfile.TemporaryDirectory() as home:
        got = run_sh( f'HOME={home}; ERRAND_CACHE_DIR={home}/c; echo {B.SH_BASE}', home )
        assert got.stdout.strip() == f"{home}/c", got.stdout
        got = run_sh( f'HOME={home}; unset ERRAND_CACHE_DIR; echo {B.SH_BASE}', home )
        assert got.stdout.strip() == f"{home}/.cache/errand", got.stdout


if test( "the oldest Python errand runs on is said once, and pyproject agrees" ):
    text = ( B.PACKAGE.parent / "pyproject.toml" ).read_text()
    assert f'requires-python = ">={B.MIN[ 0 ]}.{B.MIN[ 1 ]}"' in text


if test( "the shipped copy is said whole only once every file is there, by one shipping at a time" ):
    tar = B.package_tar()
    with tempfile.TemporaryDirectory() as tmp:
        def unpack( d, data ):
            return subprocess.run( [ "sh", "-c", B.UNPACK, "sh", str( d ), "K" ], input = data, capture_output = True )
        whole = Path( tmp ) / "a" / "errand"
        assert unpack( whole, tar ).returncode == 0
        assert ( whole / ".sources" ).read_text().strip() == "K" and ( whole / "_boot.py" ).exists()
        # Cut short ( a network drop ): it fails, and nothing takes the place of a copy.
        cut = Path( tmp ) / "b" / "errand"
        assert unpack( cut, tar[ : len( tar ) // 2 ] ).returncode != 0
        assert not cut.exists() and not list( cut.parent.glob( "errand.part*" ) ), list( cut.parent.iterdir() )
        # A whole tar whose files are not all there ( its manifest says so ): no `.sources` either.
        import io, tarfile
        buf = io.BytesIO()
        with tarfile.open( fileobj = buf, mode = "w:gz" ) as t:
            listing = b"_boot.py\nyamlish.py\n"
            info = tarfile.TarInfo( B.MANIFEST ); info.size = len( listing )
            t.addfile( info, io.BytesIO( listing ) )
            info = tarfile.TarInfo( "yamlish.py" ); info.size = 1
            t.addfile( info, io.BytesIO( b"x" ) )
        part = Path( tmp ) / "c" / "errand"
        got = unpack( part, buf.getvalue() )
        assert got.returncode != 0 and b"without _boot.py" in got.stderr and not part.exists(), got
        # Two shippings at once each unpack in a directory of their own: the copy is whole.
        both = Path( tmp ) / "d" / "errand"
        procs = [ subprocess.Popen( [ "sh", "-c", B.UNPACK, "sh", str( both ), "K" ], stdin = subprocess.PIPE,
                                    stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL ) for _ in range( 4 ) ]
        for p in procs:
            p.stdin.write( tar )
            p.stdin.close()
        assert all( p.wait() == 0 for p in procs )
        names = { l for l in ( both / B.MANIFEST ).read_text().splitlines() if l }
        assert all( ( both / n ).is_file() for n in names ) and ( both / ".sources" ).exists()


if test( "the copy's place follows the sources' content, all of it" ):
    from errand import __version__
    assert B.key() == f"{__version__}-{B.sources_key()}" and B.src_rel() == f"src/{B.key()}"
    shipped = { rel.as_posix() for _, rel in B._shipped() }
    assert "_boot.py" in shipped and not any( "__pycache__" in s for s in shipped )
    # Every shipped file counts, `.py` or not: what the key hashes is what the tar holds.
    import io, tarfile
    with tarfile.open( fileobj = io.BytesIO( B.package_tar() ), mode = "r:gz" ) as t:
        assert { m.name for m in t.getmembers() } == shipped | { B.MANIFEST }


if test( "a Windows guest's copy: the same guarantees, by its Python" ):
    tar = B.package_tar()
    with tempfile.TemporaryDirectory() as tmp:
        def unpack( d, data, key = "K" ):
            return subprocess.run( [ "sh", "-c", B.unpack_py_line( sys.executable, str( d ), key ) ],
                                   input = data, capture_output = True )
        whole = Path( tmp ) / "a" / "errand"
        assert unpack( whole, tar ).returncode == 0
        assert ( whole / ".sources" ).read_text().strip() == "K" and ( whole / "_boot.py" ).exists()
        assert unpack( whole, b"" ).returncode == 0, "already there: nothing read"
        cut = Path( tmp ) / "b" / "errand"
        assert unpack( cut, tar[ : len( tar ) // 2 ] ).returncode != 0
        assert not cut.exists() and not list( cut.parent.iterdir() ), list( cut.parent.iterdir() )
        both = Path( tmp ) / "c" / "errand"
        procs = [ subprocess.Popen( [ "sh", "-c", B.unpack_py_line( sys.executable, str( both ), "K" ) ],
                                    stdin = subprocess.PIPE, stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL )
                  for _ in range( 4 ) ]
        for p in procs:
            p.stdin.write( tar )
            p.stdin.close()
        assert all( p.wait() == 0 for p in procs )
        names = { l for l in ( both / B.MANIFEST ).read_text().splitlines() if l }
        assert all( ( both / n ).is_file() for n in names ) and sorted( x.name for x in both.parent.iterdir() ) == [ "errand" ]


if test( "a copy of the sources goes once nothing needs it: no agent started from it, and unused for a while" ):
    import time
    with tempfile.TemporaryDirectory() as tmp:
        base = Path( tmp )
        def copy( name, key, age_days ):
            d = base / "src" / name / "errand"
            d.mkdir( parents = True )
            ( d / ".sources" ).write_text( key + "\n" )
            t = time.time() - age_days * 86400
            for p in ( d / ".sources", d.parent ):
                os.utime( p, ( t, t ) )
            return d.parent
        served = copy( "v-aaa", "aaa", 30 )            # an agent of it is there: kept, however old
        recent = copy( "v-bbb", "bbb", 2 )             # used two days ago ( a job may wait in a queue ): kept
        mine = copy( "v-ccc", "ccc", 30 )              # the asking agent's own: kept
        old = copy( "v-ddd", "ddd", 30 )               # nothing names it, unused for a month: goes
        legacy = copy( "2026.11.03.2-a4e77e0b", "eee", 30 )   # a copy named after a checkout's path: by what it holds
        half = base / "src" / "v-fff.part.123"         # a shipping left half done
        half.mkdir()
        t = time.time() - 7200
        os.utime( half, ( t, t ) )
        ( base / "agents" / "env-aaa-1234" ).mkdir( parents = True )
        ( base / "hub-zzz" ).mkdir()
        assert B.keys_in_use( base ) == { "aaa", "zzz" }
        gone = B.prune_sources( base, keep = { "ccc" } )
        assert sorted( d.name for d in gone ) == sorted( [ old.name, legacy.name, half.name ] ), gone
        assert served.exists() and recent.exists() and mine.exists()
        # The agent, after its runs, does the same from its own directory.
        from errand.agents import endpoint
        copy( "v-ggg", "ggg", 30 )
        endpoint.prune_sources( base / "agents" / "env-aaa-1234" )
        assert not ( base / "src" / "v-ggg" ).exists() and served.exists()
