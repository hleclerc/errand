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
