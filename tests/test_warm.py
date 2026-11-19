"""Warm imports ( ADR 0005, step 7 ): a session forked from a zygote that has already imported, or run cold.

What is gained is measured by hand, on a machine where imports cost something ( torch: 2.6 s cold,
1.3 s warm, on lmo ).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from errand import test

ROOT = Path( __file__ ).resolve().parent.parent

ENTRY = '''
import os, json
from errand import test
if test( "hello" ):
    print( "pid", os.getpid(), "ppid", os.getppid(), flush = True )
'''


def project( d: Path ) -> Path:
    p = d / "proj"
    p.mkdir()
    ( p / "errand-project.py" ).write_text( "" )
    ( p / "hello.py" ).write_text( ENTRY )
    return p


def session( p: Path, agent: Path, warm = "1" ):
    req = { "root": str( p ), "env": "default", "tags": { }, "verb": "run", "keep_alive": 20,
            "known": { "pattern": "hello.py::*", "target_args": [ ], "no_queue": True, "from_default": False,
                       "phase": "run" } }
    env = { **os.environ, "PYTHONPATH": str( ROOT ), "ERRAND_AGENT_DIR": str( agent ), "ERRAND_WARM": warm }
    return subprocess.run( [ sys.executable, "-m", "errand.agents.warm", "session", json.dumps( req ) ],
                           cwd = p, env = env, capture_output = True, text = True, timeout = 120 )


def passed( out: str, name = "hello" ) -> bool:
    """A session says how a case ended as an event ( `ran`, ADR 0016 ), drawn by the side that drives it."""
    return any( '"op": "ran"' in l and '"status": "PASS"' in l and f'"name": "{name}"' in l for l in out.splitlines() )


if test( "a session is a fork of the zygote, which stays, and learns what to import" ):
    if not hasattr( os, "fork" ):
        from errand import skip
        skip( "no fork here" )
    d = Path( tempfile.mkdtemp( dir = "/tmp" ) )
    try:
        p, agent = project( d ), d / "agent"
        first = session( p, agent )
        assert first.returncode == 0 and passed( first.stdout ), first.stdout + first.stderr
        zygote = agent / "warm"
        log = ( zygote / "log" ).read_text() if ( zygote / "log" ).exists() else "( no log )"
        assert ( zygote / "sock" ).exists(), f"the zygote stays:\n{log[ -1500 : ]}"
        second = session( p, agent )
        assert second.returncode == 0 and passed( second.stdout ), second.stdout + second.stderr
        pids = [ int( r.stdout.split( "pid " )[ 1 ].split()[ 0 ] ) for r in ( first, second ) ]
        assert pids[ 0 ] != pids[ 1 ], "each session is a process of its own"
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not ( zygote / "modules.json" ).exists():
            time.sleep( 0.2 )
        wanted = json.loads( ( zygote / "modules.json" ).read_text() )[ "want" ]
        assert "errand.cli.here" in wanted and "hello" not in wanted, "what the project is, is read again"
    finally:
        shutil.rmtree( d, ignore_errors = True )


if test( "ERRAND_WARM=0, or no agent to say where a zygote is: the session runs cold, here" ):
    d = Path( tempfile.mkdtemp( dir = "/tmp" ) )
    try:
        p, agent = project( d ), d / "agent"
        got = session( p, agent, warm = "0" )
        assert got.returncode == 0 and passed( got.stdout ), got.stdout + got.stderr
        assert not ( agent / "warm" ).exists(), "nothing was started"
    finally:
        shutil.rmtree( d, ignore_errors = True )


if test( "a fork's random generators are its own" ):
    import importlib.util
    if importlib.util.find_spec( "numpy" ) is None:
        from errand import skip
        skip( "no numpy here" )
    code = ( "import os, sys; sys.path.insert( 0, %r ); import numpy as np; from errand.agents.warm import _reseed\n"
             "r, w = os.pipe()\n"
             "for _ in range( 2 ):\n"
             "    if os.fork() == 0:\n"
             "        _reseed(); os.write( w, ( '%%.12f\\n' %% np.random.rand() ).encode() ); os._exit( 0 )\n"
             "    os.wait()\n"
             "print( os.read( r, 100 ).decode() )" ) % str( ROOT )
    out = subprocess.run( [ sys.executable, "-c", code ], capture_output = True, text = True, timeout = 60 )
    values = out.stdout.split()
    assert len( values ) == 2 and values[ 0 ] != values[ 1 ], out.stdout + out.stderr


if test( "sessions are forked only where the stack asks for it, with a Preload" ):
    import errand
    from errand.agents.envs import ops_argv
    cold = ops_argv( "py", "boot", { "verb": "run" } )
    assert cold[ 3 ] == "errand.agents.ops", "without Preload, a Python started anew"
    warm = ops_argv( "py", "boot", { "verb": "run" }, errand.Preload( "torch", learn = False ) )
    assert warm[ 3 ] == "errand.agents.warm"
    request = json.loads( warm[ -1 ] )
    assert request[ "preload" ] == [ "torch" ] and request[ "learn" ] is False


if test( "the zygote keeps as long as its agent, is listed, and goes when its agent goes ( ADR 0008 )" ):
    if not hasattr( os, "fork" ):
        from errand import skip
        skip( "no fork here" )
    from errand.agents import table as T
    d = Path( tempfile.mkdtemp( dir = "/tmp" ) )
    stand_in = subprocess.Popen( [ "sleep", "60" ] )         # the agent, as far as the zygote can tell
    try:
        p, agent = project( d ), d / "agent"
        os.environ[ "ERRAND_AGENT_PID" ], os.environ[ "ERRAND_AGENT_KEEP" ] = str( stand_in.pid ), "300"
        try:
            got = session( p, agent )
        finally:
            del os.environ[ "ERRAND_AGENT_PID" ], os.environ[ "ERRAND_AGENT_KEEP" ]
        assert got.returncode == 0 and passed( got.stdout ), got.stdout + got.stderr
        listed = T.zygotes( [ agent ] )
        assert len( listed ) == 1 and listed[ 0 ][ "pid" ], listed
        zygote = listed[ 0 ][ "pid" ]
        stand_in.kill()
        stand_in.wait()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and T.pid_runs( zygote ):
            time.sleep( 0.1 )
        assert not T.pid_runs( zygote ), "a zygote outlived its agent"
        assert T.zygotes( [ agent ] ) == [ ]
    finally:
        if stand_in.poll() is None:
            stand_in.kill()
        shutil.rmtree( d, ignore_errors = True )
