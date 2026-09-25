"""The screen itself, driven by textual's own pilot.

No terminal is involved: `App.run_test()` runs the app headless and lets the
test press keys at it and read the widgets back. So these check the things only
the view can get wrong -- what the lists hold, what the dialog builds, what the
pane facing a case shows -- while everything underneath is `test_session.py`.
"""
import asyncio
import importlib.util
import tempfile
import time
from pathlib import Path

from errand import test, skip

from _demo import UNREADABLE, WORK, a_project, a_session, named, put_back
from _infra import run_errand


def the_screen( ):
    """The app -- or a skip saying what to install.

    Asked for INSIDE an entry and never at module level: a skip raised while a
    file is being read is not a skip, it is a file that would not import, and
    the whole of it would be reported as unreadable.
    """
    if importlib.util.find_spec( "textual" ) is None:
        skip( "textual is not installed, so there is no screen to drive",
              "the screen is the one part of errand with a dependency:\n"
              "    pip install 'errand-run[tui]'\n"
              "  everything it does, the command line does -- the rest of the suite covers that" )
    from errand.tui import Errand, Launch
    return Errand, Launch


def drive( project, body, timeout = 120 ):
    """Run `body( pilot, app )` against the app, and put the config back."""
    Errand, _ = the_screen()
    session, kept = a_session( project )

    async def go():
        app = Errand( session )
        async with app.run_test() as pilot:
            await pilot.pause()
            await body( pilot, app )

    try:
        asyncio.run( asyncio.wait_for( go(), timeout ) )
    finally:
        put_back( kept )
    return session


async def settle( pilot, until, timeout = 90 ):
    """Wait for something to become true, letting the app breathe."""
    end = time.time() + timeout
    while time.time() < end:
        await pilot.pause( 0.2 )
        if until():
            return True
    return False


def column( app, table_id, index = 1 ):
    table = app.query_one( f"#{table_id}" )
    return [ str( table.get_row_at( r )[ index ] ) for r in range( table.row_count ) ]


if test( "the cases are listed, and what would not import is listed too" ):
    the_screen()
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp, { "test_demo.py": WORK, "test_absent.py": UNREADABLE } )

        async def body( pilot, app ):
            from textual.widgets import DataTable
            names = column( app, "cases" )
            assert "quick" in names and "slow" in names, names
            assert any( "test_absent.py" in n for n in names ), names
            # And the pane facing it says what went wrong, rather than the
            # screen being empty and the reason being nowhere.
            table = app.query_one( "#cases", DataTable )
            table.move_cursor( row = names.index( next( n for n in names if "absent" in n ) ) )
            await pilot.pause()
            shown = str( app.query_one( "#about" ).render() )
            assert "a_module_that_is_not_installed" in shown, shown

        drive( project, body )


if test( "enter on a case opens the dialog, and the dialog runs it", tags = [ "slow" ] ):
    _, Launch = the_screen()
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )

        async def body( pilot, app ):
            from textual.widgets import DataTable, Log, SelectionList
            app.query_one( "#cases", DataTable ).focus()
            await pilot.press( "enter" )
            await pilot.pause()
            assert isinstance( app.screen, Launch ), app.screen

            # The dimensions are all in the window: the case is ticked because
            # it is the one that opened it, and everything else is a box.
            cases = app.screen.query_one( "#cases", SelectionList )
            assert len( cases.selected ) == 1
            assert app.screen.argv() == [ "test_demo::quick" ], app.screen.argv()

            await pilot.press( "enter" )                  # run it
            assert await settle( pilot, lambda: app.session.states
                                 and all( s[ "state" ] == "done" for s in app.session.states ) ), \
                   list( app.session.log )
            assert column( app, "runs", 0 ) == [ "$", "ok" ], column( app, "runs", 0 )

            # The pane facing the case is the file that case wrote.
            app.query_one( "#runs", DataTable ).focus()
            await pilot.pause( 0.6 )
            written = app.query_one( "#out", Log )
            assert any( "hello from quick" in line for line in written.lines ), written.lines

        session = drive( project, body )
        assert session.history()[ 0 ] == "test_demo::quick", session.history()


if test( "ticking two of anything is the comma that says so" ):
    _, Launch = the_screen()
    from textual.widgets import SelectionList
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )

        async def body( pilot, app ):
            slow = named( app.session, "slow" )
            app.push_screen( Launch( app.session, [ slow ] ) )
            await pilot.pause()
            dialog = app.screen
            dialog.query_one( "#envs", SelectionList ).select_all()
            dialog.query_one( "#tag-fp", SelectionList ).select_all()
            dialog.query_one( "#choice-method", SelectionList ).select_all()
            await pilot.pause()
            assert dialog.argv() == [ "test_demo::slow", "--env", "plain,other",
                                      "--fp", "32,64", "--method", "cg,direct" ], dialog.argv()
            # And the window says what it is about to do, once, quietly.
            assert "--env plain,other" in str( dialog.query_one( "#preview" ).render() )

        drive( project, body )


if test( "a line of history runs again", tags = [ "slow" ] ):
    the_screen()
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )
        code, output = run_errand( project, "test_demo::quick", "--env", "other" )
        assert code == 0, output

        async def body( pilot, app ):
            from textual.widgets import DataTable
            app.query_one( "#tabs" ).active = "tab-history"
            await pilot.pause()
            assert column( app, "history", 0 ) == [ "test_demo::quick --env other" ]

            # The pane facing it holds what that command produced last time,
            # read out of the tree -- this session never ran it.
            app.query_one( "#history", DataTable ).focus()
            await pilot.pause()
            shown = str( app.query_one( "#past" ).render() )
            assert "hello from quick" in shown, shown

            await pilot.press( "enter" )
            assert await settle( pilot, lambda: app.session.states
                                 and all( s[ "state" ] == "done" for s in app.session.states ) ), \
                   list( app.session.log )

        drive( project, body )
