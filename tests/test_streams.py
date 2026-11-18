"""A run's raw streams: stdout and stderr kept in its directory, whatever ends the process, and the
last of stderr said when it ended by its exit status or a signal."""
import os
import signal
import tempfile
import time
from pathlib import Path

from errand import test, yamlish
from errand import results as R, streams

from _infra import run_errand, write_project


CRASHING = '''
import ctypes, os, sys
from errand import test

if test( "segfaults" ):
    print( "before the crash" )
    sys.stdout.flush()
    os.write( 2, b"said on fd 2, by C\\n" )
    ctypes.string_at( 0 )
'''

SCRIPT = '''
import sys
print( "on stdout" )
print( "the reason, on stderr", file = sys.stderr )
sys.exit( 3 )
'''


def runs_of( root, *parts ):
    return sorted( p for p in ( root / "errand-outputs" / "runs" ).joinpath( *parts ).iterdir()
                   if p.is_dir() and not p.is_symlink() )


if test( "a process that fails keeps its stdout and stderr apart, and says the last of stderr" ):
    with tempfile.TemporaryDirectory() as tmp:
        root = write_project( Path( tmp ) / "proj", "import errand\n", { "fails.py": SCRIPT } )
        code, output = run_errand( root, "run", "--no-queue", "python", "fails.py" )
        assert code == 1, output
        assert "exit 3" in output and "last lines of stderr" in output and "the reason, on stderr" in output, output
        leaf, = runs_of( root, "python" )
        assert ( leaf / R.STDOUT ).read_text().strip().endswith( "on stdout" )
        assert ( leaf / R.STDERR ).read_text().strip() == "the reason, on stderr"
        assert "the reason, on stderr" in yamlish.read( leaf / R.RESULT )[ "error" ]


if test( "a process that dies keeps what it wrote, and its record is written for it" ):
    if os.name != "posix":
        from errand import skip
        skip( "the keeper of the streams is POSIX's" )
    with tempfile.TemporaryDirectory() as tmp:
        root = write_project( Path( tmp ) / "proj", "import errand\n", { "test_crash.py": CRASHING } )
        code, output = run_errand( root, "run", "--no-queue", "test_crash.py::segfaults" )
        assert code != 0, output
        leaf, = runs_of( root, "test_crash.py", "segfaults" )
        # The keeper outlives the run: it writes the record once the streams are closed.
        for _ in range( 100 ):
            if ( leaf / R.RESULT ).exists():
                break
            time.sleep( 0.1 )
        err = ( leaf / R.STDERR ).read_text()
        # What C wrote, and the fault handler's word on where: kept, though Python never got to say it.
        assert "said on fd 2, by C" in err and "Segmentation fault" in err, err
        assert "before the crash" in ( leaf / R.STDOUT ).read_text()
        got = yamlish.read( leaf / R.RESULT )
        assert got[ "status" ] == "FAIL" and "before its record was written" in got[ "error" ], got
        assert got[ "name" ] == "segfaults" and got[ "duration_s" ] is None


if test( "an ending is said as a person reads it" ):
    assert streams.ended( 3 ) == "exit 3"
    assert streams.ended( -signal.SIGSEGV ) == "signal SIGSEGV"
    assert streams.ended( 128 + signal.SIGKILL ) == "signal SIGKILL"
    # The fault handler's C stack would push the Python frames out of a tail.
    text = "x\nFatal Python error: Segmentation fault\n  File \"a.py\", line 3 in f\n" + \
           "Current thread's C stack trace (most recent call first):\n" + "  Binary file \"lib\", at f\n" * 40
    tail = streams.tail_of( text )
    assert tail.endswith( 'File "a.py", line 3 in f' ) and "Binary" not in tail, tail
    assert streams.with_tail( "exit 1", "" ) == "exit 1"


if test( "a session that dies is said: how, in which case, and the last of its stderr" ):
    from types import SimpleNamespace
    from errand.cli.here import Report
    from errand.cli.sessions import follow
    marks = [ { "op": "prepared", "rc": 0, "broken": [ ] },
              { "op": "start", "case": [ 0, 0 ], "entry": { "name": "big", "file": "t.py", "line": 4 } },
              { "op": "exit", "code": -signal.SIGSEGV } ]
    session = SimpleNamespace( next = lambda: marks.pop( 0 ),
                               stderr_tail = b"Fatal Python error: Segmentation fault\n  File \"t.py\", line 9\n" )
    report = Report()
    assert follow( session, report, { } ) == 1
    ( e, why ), = report.failed
    assert e.name == "big" and why.startswith( "signal SIGSEGV" ) and 'File "t.py", line 9' in why, why
