"""What `errand run` draws ( ADR 0016 ): a header per case, its output behind a gutter -- whoever wrote it,
Python or a child process -- an end line, whole blocks under `-j`; and the records left as written."""
import io
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from errand import test

from _infra import run_errand, write_project

MIXED = '''
import subprocess, sys
from errand import test

if test( "mixed" ):
    print( "python out", flush = True )
    print( "python err", file = sys.stderr, flush = True )
    subprocess.run( [ "sh", "-c", "echo child out; echo child err >&2" ] )
    print( "tty", sys.stdout.isatty(), flush = True )
'''


def leaf_of( project: Path, name: str ) -> Path:
    return next( p.parent for p in ( project / "errand-outputs" / "runs" ).rglob( "result.yaml" ) if name in str( p ) )


if test( "rows: aligned on the rows before, drawn again on a terminal when a column grows, whole under -j" ):
    import json
    from errand import rows
    from errand.cli.render import Renderer
    os.environ[ "ERRAND_STEPS" ] = "/dev/null"
    try:
        lines = [ rows.text( "add_balls", [ "n=1250", "pts=1250", "r=0.005" ] ),
                  rows.text( "adjust", [ "ctr=1", "pts=1250", "r=0.005" ], [ "loss 35.2", "→ 0.0035" ], [ "3.4 s" ] ),
                  rows.text( "adjust", [ "ctr=1", "pts=1250", "r=0.00706" ], [ "loss 0.00347", "→ 0.00346" ], [ "2.7 s" ] ),
                  rows.text( "split_items", [ "div=4", "pts=5000" ] ) ]
    finally:
        del os.environ[ "ERRAND_STEPS" ]
    assert lines[ 0 ].endswith( "\x07add_balls  n=1250 pts=1250 r=0.005" ), repr( lines[ 0 ] )   # what a file shows
    assert rows.text( "a", "b" ) == "a  b", "outside errand: the line only"

    # off a terminal: aligned on the rows before only; under -j: at the widths of the whole case
    for blocks, want in ( ( False, [ "add_balls  n=1250 pts=1250 r=0.005",
                                     "adjust     ctr=1 pts=1250 r=0.005  loss 35.2 → 0.0035  3.4 s",
                                     "adjust     ctr=1 pts=1250 r=0.00706  loss 0.00347 → 0.00346  2.7 s",
                                     "split_items  div=4 pts=5000" ] ),
                          ( True, [ "add_balls    n=1250 pts=1250 r=0.005",
                                    "adjust       ctr=1 pts=1250 r=0.005    loss 35.2    → 0.0035   3.4 s",
                                    "adjust       ctr=1 pts=1250 r=0.00706  loss 0.00347 → 0.00346  2.7 s",
                                    "split_items  div=4 pts=5000" ] ) ):
        out = io.StringIO()
        r = Renderer( out, out )
        r.mode, r.color, r.blocks = "bar", False, blocks
        r.head( "foam", "f.py:1" )
        data = ( "\n".join( lines ) + "\nplain\n" ).encode()
        for i in range( 0, len( data ), 7 ):                   # rows cut anywhere still arrive whole
            r.write( data[ i : i + 7 ] )
        r.tail( "PASS", "foam", "f.py:1" )
        got = out.getvalue().splitlines()[ 1 : -1 ]
        assert got == [ "  │ " + l for l in want ] + [ "  │ plain" ], "\n".join( got )

    # on a terminal: the rows drawn before, drawn again in place, at the new widths
    class Tty( io.StringIO ):
        def isatty( self ):
            return True
    out = Tty()
    r = Renderer( out, out )
    r.mode, r.color, r._live = "bar", False, lambda: True
    r._ticking = True                                         # ( no line said under it meanwhile )
    r.head( "foam", "f.py:1" )
    for l in lines[ :3 ]:
        r.write( l + "\n" )
    said = out.getvalue()
    assert "\x1b[2A\r\x1b[K  │ adjust     ctr=1 pts=1250 r=0.005    loss 35.2    → 0.0035   3.4 s\x1b[2B\r" in said, repr( said )
    r.tail( "PASS", "foam", "f.py:1" )


if test( "the renderer: a header, the gutter of each stream, an end line; a block held whole under -j" ):
    from errand.cli.render import Renderer
    out, err = io.StringIO(), io.StringIO()
    r = Renderer( out, err )
    r.mode, r.color = "bar", False
    r.head( "solve", "s.py:3", { "n": "3" } )
    r.write( b"one\ntw" )
    r.write( b"o\n" )
    r.write( "oops\n", err = True )
    r.tail( "PASS", "solve", "s.py:3", seconds = 2.1, results = { "residual": 1e-3, "big": [ 1, 2 ] } )
    assert out.getvalue() == "  ▸ solve  s.py:3 · n=3\n  │ one\n  │ two\n  ╰ PASS solve  2.1 s · residual 0.001\n", repr( out.getvalue() )
    assert err.getvalue() == "  ┃ oops\n", repr( err.getvalue() )

    # a line left open ends before errand's next one; a bar redrawn in place keeps its gutter
    out = io.StringIO()
    r = Renderer( out, out )
    r.mode, r.color = "bar", False
    r.head( "p", "p.py:1" )
    r.write( "\rstep 1\rstep 2" )
    r.tail( "FAIL", "p", "p.py:1", seconds = 0.5, error = "ValueError: no", output = "errand-outputs/x/output.txt" )
    assert out.getvalue() == ( "  ▸ p  p.py:1\n\r  │ step 1\r  │ step 2\n  ╰ FAIL p  500 ms  ValueError: no\n"
                               "    ↳ errand-outputs/x/output.txt\n" ), repr( out.getvalue() )

    # `-j`: nothing of a case before its end, then all of it at once
    out = io.StringIO()
    r = Renderer( out, out )
    r.mode, r.color, r.blocks = "bar", False, True
    r.head( "a", "a.py:1" )
    r.write( "x\n" )
    r.write( "y\n", err = True )
    assert out.getvalue() == "", out.getvalue()
    r.tail( "PASS", "a", "a.py:1" )
    assert out.getvalue() == "  ▸ a  a.py:1\n  │ x\n  ┃ y\n  ╰ PASS a\n", repr( out.getvalue() )

    # `spaces`, `off`
    for mode, want in ( ( "spaces", "    x\n" ), ( "off", "x\n" ) ):
        out = io.StringIO()
        r = Renderer( out, out )
        r.mode, r.color = mode, False
        r.in_case = True
        r.write( "x\n" )
        assert out.getvalue() == want, ( mode, out.getvalue() )


if test( "off a terminal, a child's output is behind the gutter too, and output.txt holds everything, as written",
         tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "test_mixed.py": MIXED } )
        code, output = run_errand( project, "run", "--no-queue", "test_mixed.py::*" )
        assert code == 0, output
        for line in ( "  │ python out", "  ┃ python err", "  │ child out", "  ┃ child err" ):
            assert line in output.splitlines(), f"{line!r}\n{output}"
        assert any( l.startswith( "  ▸ mixed (default)  test_mixed.py:" ) for l in output.splitlines() ), output
        leaf = leaf_of( project, "mixed" )
        everything = ( leaf / "output.txt" ).read_text()
        for line in ( "python out", "python err", "child out", "child err" ):
            assert line in everything.splitlines(), f"{line!r} not in output.txt:\n{everything}"
        assert ( leaf / "stdout.txt" ).read_text().splitlines()[ : 2 ] == [ "python out", "child out" ]
        assert "│" not in everything + ( leaf / "stdout.txt" ).read_text() + ( leaf / "stderr.txt" ).read_text()
        assert "errand-op" not in everything + ( leaf / "stdout.txt" ).read_text(), "a session's marks are not output"
        code, output = run_errand( project, "run", "--no-queue", "--plain", "test_mixed.py::*" )
        assert "python out" in output.splitlines() and "│" not in output, output


if test( "on a terminal, the run still sees one, and a child's output is behind the gutter", tags = [ "slow" ] ):
    if os.name != "posix":
        from errand import skip
        skip( "pseudo-terminals are POSIX's" )
    from _tty import Term, plain
    import errand
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "test_mixed.py": MIXED } )
        env = { k: v for k, v in os.environ.items() if not k.startswith( "ERRAND_" ) }
        env.update( TERM = "xterm-256color", XDG_RUNTIME_DIR = str( project / ".queue" ),
                    PYTHONPATH = str( Path( errand.__file__ ).resolve().parents[ 1 ] ) )
        ( project / ".queue" ).mkdir()
        term = Term( [ sys.executable, "-m", "errand", "run", "--no-queue", "test_mixed.py::*" ], project, env = env )
        try:
            assert term.wait_for( "PASS", timeout = 60 ), term.buf
            time.sleep( 0.3 )
            shown = plain( term.read( 0.3 ) ).replace( "\r", "" )
        finally:
            term.close()
        for line in ( "  │ python out", "  ┃ python err", "  │ child out", "  ┃ child err", "  │ tty True" ):
            assert line in shown.splitlines(), f"{line!r}\n{shown}"
        leaf = leaf_of( project, "mixed" )
        assert "child out" in ( leaf / "output.txt" ).read_text() and "│" not in ( leaf / "output.txt" ).read_text()
        assert "\r\n" not in ( leaf / "stdout.txt" ).read_text(), "the pseudo-terminal changes no byte"


TWO = '''
import subprocess, sys, time
from errand import test

for name in ( "a", "b" ):
    if test( f"case {name}" ):
        for i in range( 3 ):
            print( f"{name} out {i}", flush = True )
            print( f"{name} err {i}", file = sys.stderr, flush = True )
            subprocess.run( [ "echo", f"{name} child {i}" ] )
            time.sleep( 0.1 )
'''


if test( "-j in sessions: each case one block, from its header to its end, whoever wrote in it", tags = [ "slow" ] ):
    config = 'import errand\nerrand.envs[ "vars" ] = errand.Env( [ errand.Vars( { "A": "1" } ) ] )\n'
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", config, { "test_two.py": TWO } )
        code, output = run_errand( project, "run", "--no-queue", "-j", "2", "--env", "vars", "test_two.py::*" )
        assert code == 0, output
        lines = output.splitlines()
        for name in ( "a", "b" ):
            start = lines.index( next( l for l in lines if l.startswith( f"  ▸ case {name}" ) ) )
            end = lines.index( next( l for l in lines if l.startswith( f"  ╰ PASS case {name}" ) ) )
            inside = lines[ start + 1 : end ]
            mine = [ l for l in inside if re.match( rf"^  [│┃] {name} (out|err|child) \d$", l ) ]
            assert len( mine ) == 9 and len( inside ) == 9, f"case {name}:\n" + "\n".join( inside ) + f"\n---\n{output}"


if test( "errand's work is said at the bottom while it lasts, never in the history; its numbers go to the journal" ):
    from errand import steps
    from errand.cli import bottom
    out = io.StringIO()
    kept = sys.stdout
    sys.stdout = out                                  # not a terminal: nothing drawn at all
    try:
        with bottom.working( "↑ sync push → far", kind = "push" ) as w:
            time.sleep( 0.05 )
            w.numbers = { "files": 3, "bytes": 12 }
    finally:
        sys.stdout = kept
    assert out.getvalue() == "", out.getvalue()
    r = w.record
    assert r[ "transfer" ] == "push" and r[ "files" ] == 3 and r[ "s" ] >= 0.05 and r[ "t" ] > 0, r
    # in a journal, a transfer is no step: no curve, no start of the run, no text
    s = steps.summarize( [ r, { "t": r[ "t" ] + 5, "text": "iteration 1", "residual": 1e-3 },
                           { "t": r[ "t" ] + 6, "transfer": "pull", "s": 0.1, "files": 2 } ] )
    assert s[ "curves" ] == { "residual": [ 1e-3 ] } and s[ "first" ] == r[ "t" ] + 5, s


if test( "a run over there: no transfer in the history, the push and the pull in its journal", tags = [ "ssh", "slow" ] ):
    from _infra import ssh_target
    import subprocess
    host, options, root_of = ssh_target()
    remote_root = root_of()
    config = ( 'import errand\nerrand.configure( exclude = [ "_lib" ] )\n'
               f'errand.envs[ "far" ] = errand.Env( [ errand.Ssh( host = {host!r}, root = {remote_root!r}, '
               f'options = {options!r} ), errand.Vars( {{ "PYTHONPATH": "{remote_root}/_lib" }} ) ] )\n' )
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", config, { "test_mixed.py": MIXED }, vendor = True )
        code, output = run_errand( project, "run", "--no-queue", "--env", "far", "test_mixed.py::*" )
        assert code == 0, output
        assert "push" not in output and "pull" not in output and "sent (" not in output, output
        from errand import steps
        events = steps.read( leaf_of( project, "mixed" ) / "steps.jsonl" )
        kinds = [ e.get( "transfer" ) for e in events if "transfer" in e ]
        assert kinds[ 0 ] == "push" and "pull" in kinds, events
        assert any( e.get( "transfer" ) == "pull" and any( "runs" in p for p in e.get( "paths", [ ] ) ) for e in events ), events
    subprocess.run( [ "ssh", *options, host, f"rm -rf {remote_root}" ] )


if test( "the bottom: one line with one case, a line per case under -j, +k more, the case in front above them" ):
    from errand.cli import bottom
    from errand.cli.footer import fit
    assert fit( "\x1b[1mabcdef\x1b[0m", 3 ) == "\x1b[1mabc\x1b[0m" and fit( "abc", 9 ) == "abc"
    kept = ( dict( bottom._parts ), dict( bottom._cases ), bottom._focus )
    bottom._draw, real = ( lambda: None ), bottom._draw              # nothing drawn: only what would be
    try:
        bottom._parts.clear(); bottom._cases.clear(); bottom._focus = None
        bottom._parts[ "env" ] = "far: ssh:far"
        bottom._cases[ "a" ] = { "label": "case a", "step": "iteration 3", "since": time.time(), "recent": None, "n": 1 }
        assert bottom.lines( 24 ) == [ "far: ssh:far" ], "one case says its time under its own lines"
        for i, k in enumerate( "bcdefghij" ):
            bottom._cases[ k ] = { "label": f"case {k}", "step": None, "since": time.time(), "recent": None, "n": i + 2 }
        got = bottom.lines( 24 )
        assert got[ 0 ] == "1 ▸ case a · iteration 3" and got[ 1 ] == "2 ▸ case b · 0 s", got
        assert got[ 8 ] == "+2 more" and got[ 9 ] == "far: ssh:far", got            # a third of 24 rows: 8 cases
        bottom._cases[ "b" ][ "recent" ] = lambda n: [ f"  │ b {i}" for i in range( 50 ) ][ -n : ]
        bottom.focus( 2 )
        got = bottom.lines( 24 )
        assert got[ -1 ] == "far: ssh:far" and "2 ▶ case b · 0 s" in got and got[ 0 ].startswith( "  │ b " ), got
        assert got.index( "2 ▶ case b · 0 s" ) > got.index( "  │ b 49" ), "the case in front, above the lines"
        bottom.focus( "next" ); assert bottom._focus == "c"
        bottom.focus( None ); assert bottom._focus is None
        bottom.case_end( "a" ); assert "a" not in bottom._cases
    finally:
        bottom._draw = real
        bottom._parts.clear(); bottom._parts.update( kept[ 0 ] )
        bottom._cases.clear(); bottom._cases.update( kept[ 1 ] )
        bottom._focus = kept[ 2 ]


SLOW = '''
import time, errand
from errand import test

for name in ( "alpha", "beta" ):
    if test( f"slow {name}" ):
        for i in range( 12 ):
            print( f"{name} line {i}", flush = True )
            errand.step( f"iteration {i}", done = ( i + 1 ) / 12 )
            time.sleep( 0.25 )
'''


if test( "-j on a terminal: a line per case at the bottom, and a key puts one in front, live", tags = [ "slow" ] ):
    if os.name != "posix":
        from errand import skip
        skip( "pseudo-terminals are POSIX's" )
    from _tty import Term, plain
    import errand
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "test_slow.py": SLOW } )
        env = { k: v for k, v in os.environ.items() if not k.startswith( "ERRAND_" ) }
        env.update( TERM = "xterm-256color", XDG_RUNTIME_DIR = str( project / ".queue" ),
                    PYTHONPATH = str( Path( errand.__file__ ).resolve().parents[ 1 ] ) )
        ( project / ".queue" ).mkdir()
        term = Term( [ sys.executable, "-m", "errand", "run", "--no-queue", "-j", "2", "test_slow.py::*" ], project,
                     rows = 24, cols = 100, env = env )
        try:
            assert term.wait_for( "2 ▸ slow beta", timeout = 60 ), plain( term.buf )
            term.send( "1", settle = 0.8 )
            seen = plain( term.read( 0.2 ) )
            assert "1 ▶ slow alpha" in seen and "│ alpha line" in seen, seen
            assert term.wait_for( "all good", timeout = 60 ), plain( term.buf )
        finally:
            term.close()
        history = plain( re.sub( r"\x1b7.*?\x1b8", "", term.buf, flags = re.S ) )
        assert history.count( "alpha line 11" ) == 1 and "╰ PASS slow alpha" in history, history


if test( "typing for the case in front: its number, the line edited at the bottom, Enter sends it, Ctrl-D ends it" ):
    from errand.cli import bottom
    from errand.cli.render import Renderer
    kept = ( dict( bottom._cases ), bottom._focus )
    bottom._draw, real = ( lambda: None ), bottom._draw
    sent, closed = [ ], [ ]
    try:
        bottom._cases.clear(); bottom._focus = None
        bottom.case_start( "a", "case a" )
        bottom.case_start( "b", "case b", write = sent.append, close = lambda: closed.append( 1 ) )
        bottom.case_end( "a" )
        bottom.case_start( "c", "case c" )
        assert [ k[ "n" ] for k in bottom._cases.values() ] == [ 2, 1 ], "a number stays with its case"
        bottom.key( b"2" ); assert bottom._focus == "b"
        for k in b"13x":
            bottom.key( bytes( [ k ] ) )
        bottom.key( b"\x7f" )                               # backspace
        assert bottom._typed == b"13" and sent == [ ], bottom._typed
        bottom.key( b"\n" ); assert sent == [ b"13\n" ] and bottom._typed == b""
        bottom.key( b"\x04" ); assert closed == [ 1 ]
        bottom.key( b"\x1b" ); assert bottom._focus is None
        bottom.key( b"1" ); assert bottom._focus == "c", "a case that takes no input: digits still choose"
    finally:
        bottom._draw = real
        bottom._cases.clear(); bottom._cases.update( kept[ 0 ] ); bottom._focus = kept[ 1 ]; bottom._typed = b""
    out = io.StringIO()
    r = Renderer( out, out )
    r.mode, r.color = "bar", False
    r.head( "asks", "a.py:1" )
    r.write( "name? " )
    r.last_write -= 5
    assert r.waiting(), "a question left open, then silence"
    r.typed( b"hugo\n", echoed = True )                    # the terminal showed it, and ended the line
    r.write( "got hugo\n" )
    assert out.getvalue().endswith( "  │ name?   │ got hugo\n" ) and not r.waiting(), repr( out.getvalue() )
    r.typed( b"x\n", echoed = False )                      # under Focus: in the case's output
    assert out.getvalue().endswith( "  │ x\n" ), repr( out.getvalue() )


ASKS = '''
from errand import test

for name in ( "ann", "bob" ):
    if test( f"asks {name}" ):
        try:
            print( f"{name} got {input( f'{name}, a number? ' )!r}" )
        except EOFError:
            print( f"{name} got EOF" )
'''


def answers( project ):
    from errand import yamlish
    return { p.parent.parent.name: ( p.parent / "output.txt" ).read_text()
             for p in ( project / "errand-outputs" / "runs" ).rglob( "result.yaml" ) }


def typing_into( project, argv, script ):
    """`errand run` on a terminal of its own, and keys typed at it: ( "wait", text ) or keys."""
    from _tty import Term, plain
    import errand
    env = { k: v for k, v in os.environ.items() if not k.startswith( "ERRAND_" ) }
    env.update( TERM = "xterm-256color", XDG_RUNTIME_DIR = str( project / ".queue" ),
                PYTHONPATH = str( Path( errand.__file__ ).resolve().parents[ 1 ] ) )
    ( project / ".queue" ).mkdir( exist_ok = True )
    term = Term( [ sys.executable, "-m", "errand", "run", "--no-queue", *argv ], project, rows = 24, cols = 100,
                 env = env, controlling = True )
    try:
        for step in script:
            if isinstance( step, tuple ):
                assert term.wait_for( step[ 1 ], timeout = 60 ), plain( term.buf )
            else:
                os.write( term.master, step.encode() )
                term.read( 0.4 )
        deadline = time.time() + 60
        while term.child.poll() is None and time.time() < deadline:
            term.read( 0.3 )
    finally:
        term.close()


if test( "a case asks, the keyboard here answers: in this process, and under -j through the case in front",
         tags = [ "slow" ] ):
    if os.name != "posix":
        from errand import skip
        skip( "pseudo-terminals are POSIX's" )
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "test_asks.py": ASKS } )
        typing_into( project, [ "test_asks.py::asks ann" ], [ ( "wait", "ann, a number?" ), "12\r" ] )
        assert "ann got '12'" in answers( project )[ "asks_ann" ], answers( project )
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "test_asks.py": ASKS } )
        typing_into( project, [ "-j", "2", "test_asks.py::*" ],
                     [ ( "wait", "2 ▸ asks bob" ), "1", "12\r", "\x1b", ( "wait", "PASS asks ann" ), "2", "34\r" ] )
        got = answers( project )
        assert "ann got '12'" in got[ "asks_ann" ] and "bob got '34'" in got[ "asks_bob" ], got
    with tempfile.TemporaryDirectory() as tmp:            # off a terminal: nothing to answer, EOF
        project = write_project( Path( tmp ) / "proj", "", { "test_asks.py": ASKS } )
        code, output = run_errand( project, "run", "--no-queue", "test_asks.py::asks ann" )
        assert code == 0 and "ann got EOF" in output, output


if test( "a case over there asks, the keyboard here answers", tags = [ "ssh", "slow" ] ):
    from _infra import ssh_target
    import subprocess
    host, options, root_of = ssh_target()
    remote_root = root_of()
    config = ( 'import errand\nerrand.configure( exclude = [ "_lib" ] )\n'
               f'errand.envs[ "far" ] = errand.Env( [ errand.Ssh( host = {host!r}, root = {remote_root!r}, '
               f'options = {options!r} ), errand.Vars( {{ "PYTHONPATH": "{remote_root}/_lib" }} ) ] )\n' )
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", config, { "test_asks.py": ASKS }, vendor = True )
        typing_into( project, [ "--env", "far", "test_asks.py::asks ann" ],
                     [ ( "wait", "waits for input?" ), "12\r" ] )
        assert "ann got '12'" in answers( project ).get( "asks_ann", "" ), answers( project )
    subprocess.run( [ "ssh", *options, host, f"rm -rf {remote_root}" ] )


TRACED = '''
import json
from errand import test

def load( name ):
    try:
        return json.loads( "{" + name )
    except ValueError as err:
        raise RuntimeError( f"cannot load {name}" ) from err

if test( "nested" ):
    load( "mesh" )
'''


if test( "a case's traceback without errand's frames, its chain kept; whole with -v; errand's own never hidden" ):
    from errand.cli import tracebacks as T
    try:
        raise ValueError( "the matrix is singular" )         # raised here: a frame of the suite's, kept
    except ValueError as exc:
        assert "ValueError: the matrix is singular" in T.text( exc ) and __file__ in T.text( exc )
    assert T.errand_frame( T.__file__ ) and T.errand_frame( "<frozen importlib._bootstrap>" )
    assert not T.errand_frame( __file__ ) and not T.errand_frame( __import__( "json" ).__file__ )

    def errands_own():                               # a failure with no frame but errand's: kept whole
        import traceback
        te = traceback.TracebackException( KeyError, KeyError( "k" ), None )
        te.stack = traceback.StackSummary.from_list( [ ( T.__file__, 10, "f", "x" ) ] )
        T._trim( te, set() )
        return te
    assert len( errands_own().stack ) == 1

    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "test_traced.py": TRACED } )
        code, output = run_errand( project, "run", "--no-queue", "test_traced.py::*" )
        assert code == 1 and "RuntimeError: cannot load mesh" in output and "direct cause" in output, output
        assert "errand/cli/here.py" not in output and "frozen importlib" not in output, output
        assert "json/decoder.py" in output, "a library's frames stay"
        assert "  ┃\n" in output, "an empty line of the case keeps its gutter"
        code, output = run_errand( project, "run", "--no-queue", "-v", "test_traced.py::*" )
        assert "errand/cli/here.py" in output, "-v: whole"


if test( "colors forced for a case run elsewhere only when this terminal shows them, never against a choice" ):
    from errand.cli import render
    kept = { k: os.environ.get( k ) for k in ( "NO_COLOR", "FORCE_COLOR", "CLICOLOR_FORCE", render.COLOR, render.ENV ) }
    try:
        for k in kept:
            os.environ.pop( k, None )
        os.environ[ render.COLOR ] = "1"             # as if this terminal showed colors
        assert render.forced_colors() == { "FORCE_COLOR": "1", "CLICOLOR_FORCE": "1" }
        os.environ[ "NO_COLOR" ] = "1"
        assert render.forced_colors() == { }
        del os.environ[ "NO_COLOR" ]
        os.environ[ "FORCE_COLOR" ] = "0"
        assert render.forced_colors() == { }, "a value already chosen stands"
        del os.environ[ "FORCE_COLOR" ]
        del os.environ[ render.COLOR ]
        os.environ[ render.ENV ] = "plain"
        assert render.forced_colors() == { }
    finally:
        for k, v in kept.items():
            if v is None:
                os.environ.pop( k, None )
            else:
                os.environ[ k ] = v


if test( "on a terminal, how long a quiet case has run is said under its lines, and erased by what it writes next" ):
    import io
    from errand.cli.render import Renderer

    class Tty( io.StringIO ):
        def isatty( self ):
            return True

    out = Tty()
    kept = os.environ.get( "TERM" )
    os.environ[ "TERM" ] = "xterm"
    try:
        r = Renderer( out, out )
        r.mode, r.color = "bar", False
        r.head( "slow", "s.py:1" )
        r.write( "started\n" )
        r.set_step( "iteration 4" )
        time.sleep( 2.2 )
        said = out.getvalue()
        assert "\r\x1b[K  ┆ " in said and "· iteration 4" in said, repr( said )
        r.write( "more\n" )
        r.tail( "PASS", "slow", "s.py:1", seconds = 2.3 )
        time.sleep( 0.7 )
        after = out.getvalue()[ len( said ) : ]
        assert re.sub( r"\x1b\[[0-9;]*m", "", after ).startswith( "\r\x1b[K  │ more\n" ), repr( after )   # erased, then the line
        assert "┆" not in after, "nothing said once the case ended"
    finally:
        if kept is None:
            os.environ.pop( "TERM", None )
        else:
            os.environ[ "TERM" ] = kept
