"""`-v`: every process errand starts is said on stderr, with where and what changed, and a failure with its code."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from errand import test

from _infra import run_errand, write_project

ROOT = Path( __file__ ).resolve().parent.parent

# In a fresh interpreter: the hook replaces `subprocess.Popen` for the whole process.
PROBE = """
import os, subprocess, sys
sys.path.insert( 0, {root!r} )
os.environ[ "ERRAND_VERBOSE" ] = {on!r}
from errand import trace
trace.install()
subprocess.run( [ "sh", "-c", "echo out" ], cwd = "/", env = {{ **os.environ, "ERRAND_X": "1" }} )
subprocess.run( [ "sh", "-c", "exit 3" ] )
p = subprocess.Popen( [ "sh", "-c", "exit 4" ] )
while p.poll() is None:
    pass
"""


def probe( on ):
    env = { k: v for k, v in os.environ.items() if k != "ERRAND_VERBOSE" }
    return subprocess.run( [ sys.executable, "-c", PROBE.format( root = str( ROOT ), on = on ) ],
                           capture_output = True, text = True, env = env, timeout = 60 )


if test( "the command, where it runs and what it is handed are said on stderr, stdout untouched" ):
    got = probe( "1" )
    assert got.returncode == 0, got.stderr
    assert got.stdout == "out\n", "what is said must not land where a caller parses"
    assert "· $ sh -c 'echo out'" in got.stderr, got.stderr
    assert "in /" in got.stderr and "+ ERRAND_X=1" in got.stderr, got.stderr
    assert "ERRAND_VERBOSE" not in got.stderr, "only what differs from errand's own environment"


if test( "a failure says its code and the command it came from, once, through wait or poll" ):
    got = probe( "1" )
    assert "✗ exit 3" in got.stderr and "exit 3'" in got.stderr, got.stderr
    assert got.stderr.count( "✗ exit 4" ) == 1, got.stderr
    assert "✗ exit 0" not in got.stderr


if test( "without it, nothing is said" ):
    got = probe( "" )
    assert got.stderr == "" and got.stdout == "out\n", got.stderr


if test( "quiet probes keep their output under -v" ):
    import errand.layers as L
    from errand import trace
    kept = os.environ.get( trace.ENV )
    try:
        os.environ.pop( trace.ENV, None )
        assert L._how( True, False, None )[ "stdout" ] is subprocess.DEVNULL
        os.environ[ trace.ENV ] = "1"
        assert "stdout" not in L._how( True, False, None )
        assert L._how( True, False, None )[ "stdin" ] is subprocess.DEVNULL, "still not reading the terminal"
    finally:
        if kept is None:
            os.environ.pop( trace.ENV, None )
        else:
            os.environ[ trace.ENV ] = kept


if test( "`errand -v run` says the commands, and the errand it starts inherits it" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", {
            "show.py": "import os\nprint( 'verbose is', os.environ.get( 'ERRAND_VERBOSE' ) )\n" } )
        code, output = run_errand( project, "-v", "run", "--no-queue", "show.py" )
        assert code == 0, output
        assert "verbose is 1" in output, output
        code, output = run_errand( project, "run", "--no-queue", "show.py" )
        assert code == 0 and "verbose is None" in output and "· $" not in output, output
