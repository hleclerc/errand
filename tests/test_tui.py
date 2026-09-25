"""The screen itself, driven through a real terminal.

A curses program cannot be tested by capturing its output: it writes to a
terminal, and without one it refuses. So it gets a real one -- a pty, with a
real size -- and the test types at it, clicks in it, turns the wheel, and reads
what it painted.

What the screen is ABOUT is `test_session.py`, which needs no terminal at all.
Here is only what a view can get wrong: what the lists hold, what a key does,
and where a click lands.
"""
import tempfile
from pathlib import Path

from errand import test

from _demo import UNREADABLE, WORK, a_project
from _infra import run_errand
from _tty import DOWN, HOME, click, fkey, plain, start_tui, wheel

MANY = "from errand import test\n\n" + "\n".join(
    f"if test( 'case_{i:02}' ):\n    pass\n" for i in range( 60 ) )


def until( term, text, timeout = 60 ):
    assert term.wait_for( text, timeout ), plain( term.buf )[ -3000 : ]


if test( "the cases are a tree by file, and what would not import is in it" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp, { "test_demo.py": WORK, "test_absent.py": UNREADABLE } )
        term = start_tui( project )
        try:
            until( term, "test_demo.py" )
            shown = term.text()
            # The file is a row of its own, and its cases hang under it.
            assert "▾ test_demo.py" in shown, shown
            assert "[ ] quick" in shown and "[ ] slow" in shown, shown
            # A file that would not import is a row too, not an empty list --
            # and putting the cursor on it says why, in full.
            assert "test_absent.py" in shown and "ModuleNotFoundError" in shown, shown
            for _ in range( 3 ):           # down to the broken row, which is last
                term.send( DOWN )
            why = term.text()
            assert "a_module_that_is_not_installed" in why, why
            assert "Traceback" in why, why
            term.send( HOME )              # back to the top of the tree

            term.send( " " )               # space on the file folds it
            folded = term.frame()
            assert "▸ test_demo.py" in folded, folded
            assert "[ ] quick" not in folded, folded
        finally:
            term.close()


if test( "the directories are the tree, and a lonely one costs no row" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp, { "bench/gpu/heavy.py": WORK,
                                    "tests/one.py": WORK,
                                    "tests/two.py": WORK } )
        term = start_tui( project )
        try:
            until( term, "tests" )
            shown = term.frame()
            # `bench` holds one directory holding one file: three rows that
            # could only be walked through become one that says where it is.
            assert "▾ bench/gpu/heavy.py" in shown, shown
            assert "▾ gpu" not in shown, shown
            # `tests` holds two files, so it is a directory of its own and the
            # files hang under it, indented.
            assert "▾ tests" in shown, shown
            assert "  ▾ one.py" in shown and "  ▾ two.py" in shown, shown

            # Folding the directory takes its files with it.
            for _ in range( 3 ):           # past heavy.py and its two cases
                term.send( DOWN )
            term.send( " " )
            folded = term.frame()
            assert "▸ tests" in folded, folded
            assert "one.py" not in folded and "two.py" not in folded, folded
            assert "bench/gpu/heavy.py" in folded, "its neighbour is untouched"
        finally:
            term.close()


if test( "F2 and F3 turn the page, and tab walks the rectangles" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )
        term = start_tui( project )
        try:
            until( term, "test_demo.py" )
            assert "[cases]" in term.frame(), term.frame()
            term.send( fkey( 3 ) )             # the page after
            assert "[runs]" in term.frame(), term.frame()
            term.send( fkey( 2 ) )             # and the one before
            assert "[cases]" in term.frame(), term.frame()
            # tab stays on the page it is on: it is a neighbour, not a journey.
            term.send( "\t" ); term.send( "\t" )
            assert "[cases]" in term.frame(), term.frame()
        finally:
            term.close()


if test( "enter on a case asks where, and runs it", tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )
        term = start_tui( project )
        try:
            until( term, "test_demo.py" )
            term.send( DOWN )              # onto `quick`
            term.send( "\n" )              # the window
            asked = term.text()
            assert "run: quick" in asked, asked
            # Where, with which tags, with which parameters -- and not WHICH
            # CASE, which was the list enter was pressed in.
            assert "env" in asked and "[ ] plain" in asked and "--fp" in asked, asked
            # One line each: the flag, the boxes to tick, what it means.
            assert "[ ] 32" in asked and "[ ] 64" in asked, asked
            assert "errand test_demo::quick" in asked, asked

            term.send( "\n" )              # and run it
            until( term, "hello from quick", 90 )
            ran = term.text()
            assert "errand test_demo::quick" in ran, ran
            # Facing it: what it wrote, and the file under the cursor.
            assert "result.yaml" in ran, ran
        finally:
            term.close()


if test( "a click chooses a row, and makes its pane the active one" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )
        term = start_tui( project )
        try:
            until( term, "test_demo.py" )
            # Line 0 is the two pages, line 1 the search, line 2 the border:
            # so the file is on 3, `quick` on 4 and `slow` on 5. The cursor
            # starts on the file; clicking `slow` chooses it without walking.
            click( term, 5, 8 )
            term.send( "\n" )
            asked = term.text()
            assert "run: slow" in asked, asked
            term.send( "\x1b", settle = 1.5 )     # give up on the window
            assert "run: slow" not in term.frame(), "the window is still there"

            # A click on the box itself ticks, rather than only selecting.
            click( term, 4, 4 )
            assert "[x] quick" in term.text(), term.text()
        finally:
            term.close()


if test( "the wheel scrolls what is under the pointer, and chooses nothing" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp, { "test_many.py": MANY } )
        term = start_tui( project )
        try:
            until( term, "case_00" )
            term.send( DOWN )              # the cursor sits on case_00
            wheel( term, 5, 10, down = True, times = 5 )
            after = term.frame()
            # The ROW is gone from the list. The name itself is still on the
            # screen, in the pane facing it, because that is where the cursor
            # still is -- which is the very thing being tested.
            assert "[ ] case_00" not in after, after
            assert "[ ] case_1" in after or "[ ] case_2" in after, after

            # The cursor stayed on case_00 while the view moved away from it:
            # looking is not choosing.
            term.send( "\n" )
            asked = term.text()
            assert "run: case_00" in asked, asked
        finally:
            term.close()


if test( "typing is a search, and the best answer comes first" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp, { "test_demo.py": WORK, "test_many.py": MANY } )
        term = start_tui( project )
        try:
            until( term, "test_demo.py" )
            # Not a filter over the letters in order: `sl` has to reach `slow`
            # past sixty other cases, and land on it.
            term.send( "sl" )
            found = term.frame()
            assert "find: sl" in found, found
            assert "slow" in found and "case_00" not in found, found

            term.send( "\n" )
            assert "run: slow" in term.text(), term.text()
            term.send( "\x1b", settle = 1.0 )

            # While a search is on, space is a word separator -- so the tick is
            # ctrl-space, and it works on the narrowed list.
            term.send( "\x00" )
            ticked = term.frame()
            assert "[x] slow" in ticked, ticked
            assert "find: sl" in ticked, "what was typed is still there"

            # And esc starts by clearing what was typed: a filter is the thing
            # you most want gone, and it was the hardest to get rid of.
            term.send( "\x1b" )
            cleared = term.frame()
            assert "find: sl" not in cleared, cleared
            assert "case_00" in cleared, cleared
        finally:
            term.close()


if test( "runs and history are one list, and a command runs again", tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )
        code, output = run_errand( project, "test_demo::quick", "--env", "other" )
        assert code == 0, output

        term = start_tui( project )
        try:
            until( term, "test_demo.py" )
            term.send( fkey( 3 ) )         # to the runs page
            shown = term.text()
            # A command typed in a shell is in the same list as one run here.
            assert "test_demo::quick --env other" in shown, shown

            term.send( "\n" )              # fold it open: what it produced
            opened = term.text()
            assert "ok" in opened and "quick" in opened, opened

            term.send( fkey( 5 ) )         # the last command, again
            until( term, "1 ok", 90 )
        finally:
            term.close()


if test( "the runs are searched too, by their command", tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )
        for case in ( "quick", "slow" ):
            code, output = run_errand( project, f"test_demo::{case}" )
            assert code == 0, output

        term = start_tui( project )
        try:
            until( term, "test_demo.py" )
            term.send( fkey( 3 ) )
            both = term.frame()
            assert "test_demo::quick" in both and "test_demo::slow" in both, both

            # A history is only useful once one line of it can be found.
            term.send( "slo" )
            found = term.frame()
            assert "find: slo" in found, found
            assert "test_demo::slow" in found, found
            assert "test_demo::quick" not in found, found

            # And the search of one page is not the search of the other.
            term.send( fkey( 2 ) )
            assert "find: slo" not in term.frame(), term.frame()
        finally:
            term.close()
