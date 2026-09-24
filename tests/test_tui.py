"""The screen: what is ticked becomes a command, and what ran is read back."""
import tempfile
import time
from pathlib import Path

from errand import test, config, tui
from errand import results as R

from _infra import run_errand, write_project
from _tty import DOWN, plain, start_tui


CONFIG = '''
from errand import env, Vars

env( "plain", [ Vars( { "DEMO": "1" } ) ], fp = "32|64" )
env( "other", [ Vars( { "DEMO": "2" } ) ], fp = "64" )
'''

WORK = '''
from errand import test, bench, Param

if test( "quick" ):
    print( "hello from quick" )

if p := bench( "slow", exclusive = False, n = Param( 1 ),
               method = Param( "cg", choices = [ "cg", "direct" ] ) ):
    print( f"{p.n} turns of {p.method}" )
    p.results[ "seconds" ] = 0.1 * p.n
'''


def a_project( tmp ):
    return write_project( Path( tmp ) / "proj", CONFIG, { "test_demo.py": WORK } )


def a_screen( project ):
    """A screen on a project, without the config of the suite running this one.

    `discover` loads a project's config into module-level state, which is the
    state THIS suite is running under; it is put back afterwards.
    """
    kept = ( config.settings, dict( config.envs ), list( config.providers ) )
    screen = tui.Screen( project, project / "runs" )
    screen.discover()
    return screen, kept


def put_back( kept ):
    config.settings = kept[ 0 ]
    config.envs.clear(); config.envs.update( kept[ 1 ] )
    config.providers[ : ] = kept[ 2 ]


def tick( panel, label ):
    for row in panel.rows:
        if row.label.strip() == label:
            row.checked = True
            return row
    raise AssertionError( f"no row called {label!r} among "
                          f"{[ r.label for r in panel.rows ]}" )


# ── the lists ────────────────────────────────────────────────────────────────

if test( "a filter hides rows; it does not untick them" ):
    panel = tui.Panel( "1", "entries" )
    panel.rows = [ tui.Row( "alpha" ), tui.Row( "beta" ), tui.Row( "gamma" ) ]
    panel.rows[ 0 ].checked = panel.rows[ 2 ].checked = True
    panel.filter = "bet"
    assert [ r.label for r in panel.shown() ] == [ "beta" ]
    # Narrowing the list to find one more case must not drop the two already
    # chosen -- which is why `ticked` reads every row and not the shown ones.
    assert [ r.label for r in panel.ticked() ] == [ "alpha", "gamma" ]


if test( "a heading is passed over, never landed on" ):
    panel = tui.Panel( "1", "entries" )
    panel.rows = [ tui.Row( "a file", kind = "head" ), tui.Row( "one" ), tui.Row( "two" ) ]
    panel.first()
    assert panel.current().label == "one"
    panel.move( -1 )
    assert panel.current().label == "one", "moving up off the top must not land on the heading"


# ── the command it writes ────────────────────────────────────────────────────

if test( "what is ticked becomes a command line" ):
    with tempfile.TemporaryDirectory() as tmp:
        screen, kept = a_screen( a_project( tmp ) )
        try:
            assert screen.line() == "errand", "nothing ticked asks for everything"

            tick( screen._panel( "entries" ), "slow" )
            tui._remember( screen, screen._panel( "entries" ) )
            assert screen.line() == "errand test_demo::slow"

            # A comma is a matrix, and a second tick is a comma: two
            # environments, two values of a tag and two of a parameter are
            # eight runs, said the same way they would be said by hand.
            for name in ( "plain", "other" ):
                tick( screen._panel( "envs" ), name )
            for value in ( "32", "64" ):
                tick( screen._panel( "tags" ), value )
            for value in ( "cg", "direct" ):
                tick( screen._panel( "params" ), value )
            tui._remember( screen, screen._panel( "params" ) )
            assert screen.line() == ( "errand test_demo::slow --env plain,other "
                                      "--method cg,direct --fp 32,64" ), screen.line()
        finally:
            put_back( kept )


if test( "every case of a file is the file" ):
    with tempfile.TemporaryDirectory() as tmp:
        screen, kept = a_screen( a_project( tmp ) )
        try:
            screen._panel( "entries" ).set_all( True )
            tui._remember( screen, screen._panel( "entries" ) )
            # Shorter, and it stays true when a case is added tomorrow.
            assert screen.line() == "errand test_demo"
        finally:
            put_back( kept )


if test( "the screen knows where every run will write, before it runs" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )
        screen, kept = a_screen( project )
        try:
            plan = screen.predict( [ "test_demo::slow", "--env", "plain,other", "--n", "1,2" ] )
            assert len( plan ) == 4, plan
            assert { row[ "env" ] for row in plan } == { "plain", "other" }
            # The environment is part of the place: two environments on one
            # machine are two sets of numbers, and before this the second
            # cleared the first.
            assert { row[ "place" ] for row in plan } == { R.place( "plain" ), R.place( "other" ) }
        finally:
            put_back( kept )

        code, output = run_errand( project, "test_demo::slow", "--env", "plain,other",
                                   "--n", "1,2" )
        assert code == 0, output
        for row in plan:
            # Predicted before, found after: the same claim `--batch` and `-j`
            # rest on, and the reason a pane can face a case at all.
            assert ( project / row[ "under" ] ).is_dir(), row
            assert list( ( project / row[ "under" ] ).glob( "*/*/result.yaml" ) ), row


# ── the screen itself ────────────────────────────────────────────────────────

if test( "the screen runs what it shows, and each case's output faces it",
         tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )
        term = start_tui( project )
        try:
            assert term.wait_for( "quick", 30 ), plain( term.buf )[ -2000 : ]
            term.send( " " )                     # tick the first case
            term.send( "r" )                     # and run it
            assert term.wait_for( "all good", 90 ), plain( term.buf )[ -3000 : ]

            shown = term.text()
            # The command at the bottom of the screen is the command that ran:
            # a tick is a way of writing one, not a private way of launching.
            assert "$ errand test_demo::quick" in shown, shown
            assert "ok " in shown and "quick" in shown, shown

            # The pane facing the case holds what the case printed -- read out
            # of the file the run wrote, not out of the pipe.
            term.send( DOWN )
            assert "hello from quick" in term.text(), term.text()
        finally:
            term.close()


if test( "a line of history runs again", tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )
        code, output = run_errand( project, "test_demo::quick", "--env", "other" )
        assert code == 0, output

        term = start_tui( project )
        try:
            assert term.wait_for( "quick", 30 )
            term.send( "6" )                     # the history
            assert "test_demo::quick --env other" in term.text(), term.text()
            # What was typed in a shell is what comes back: the history holds
            # commands, not some replayable record only errand could read.
            term.send( "\n" )
            assert term.wait_for( "all good", 90 ), plain( term.buf )[ -3000 : ]
        finally:
            term.close()
