"""What the screen is about, tested without a screen.

Everything here is `errand.session`: reading a project, writing a command out of
what was ticked, working out where a run will land, and finding what it wrote.
No terminal, no textual -- which is the point of the model being a module of
its own.
"""
import tempfile
from pathlib import Path

from errand import test
from errand import results as R

from _demo import CONFIG, UNREADABLE, WORK, a_project, a_session, named, put_back
from _infra import run_errand, write_project


# ── reading a project ────────────────────────────────────────────────────────

if test( "one file that will not import costs its own row, and nothing else" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp, { "test_demo.py": WORK, "test_absent.py": UNREADABLE } )
        session, kept = a_session( project )
        try:
            assert sorted( e.name for e in session.entries ) == [ "quick", "slow" ]
            assert len( session.broken ) == 1
            path, why, trace = session.broken[ 0 ]
            assert path.name == "test_absent.py"
            assert "a_module_that_is_not_installed" in why, why
            assert "Traceback" in trace, "the whole of it is kept, to be shown"
        finally:
            put_back( kept )

        # Tolerant, not silent: the runner says so, and fails over it.
        code, output = run_errand( project )
        assert code == 1, output
        assert "could not be read" in output and "test_absent.py" in output, output
        assert "PASS quick" in output, "the readable file still ran"


if test( "a directory with a config file of its own is another project" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )
        # Its entries would run with OUR src, OUR providers and OUR
        # environments, which is to say wrongly.
        write_project( project / "vendored", CONFIG, { "test_theirs.py": WORK } )
        session, kept = a_session( project )
        try:
            assert [ str( e.file.relative_to( project ) ) for e in session.entries ] == \
                   [ "test_demo.py", "test_demo.py" ]
        finally:
            put_back( kept )


if test( "a file that declares work can import its neighbours" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp, {
            "deep/helper.py"   : "def answer():\n    return 42\n",
            "deep/test_deep.py": ( "from errand import test\n"
                                   "from helper import answer\n\n"
                                   "if test( 'the neighbour' ):\n"
                                   "    assert answer() == 42\n" ),
        } )
        # Work is declared NEXT TO the code it exercises, so this is the
        # ordinary case -- and it must not depend on which directory errand was
        # started from. Here it is started two levels above `helper.py`.
        code, output = run_errand( project )
        assert code == 0, output
        assert "PASS the neighbour" in output, output

        import sys

        from errand import discovery
        before = list( sys.path )
        discovery.collect( [ project / "deep" / "test_deep.py" ], project )
        # Borrowed, not kept: a path left behind would decide somebody else's
        # import later on.
        assert sys.path == before, [ p for p in sys.path if p not in before ]


# ── writing a command ────────────────────────────────────────────────────────

if test( "what was ticked becomes a command line" ):
    with tempfile.TemporaryDirectory() as tmp:
        session, kept = a_session( a_project( tmp ) )
        try:
            assert session.command() == [ ]
            assert session.command( entries = [ named( session, "slow" ) ] ) == \
                   [ "test_demo::slow" ]

            # A comma is a matrix, and a second tick is a comma: two
            # environments, two values of a tag and two of a parameter are
            # eight runs, said the way they would be said by hand.
            argv = session.command(
                entries = [ named( session, "slow" ) ], envs = [ "plain", "other" ],
                tags = { "fp": [ "32", "64" ] }, params = { "method": [ "cg", "direct" ] },
                jobs = 4 )
            assert argv == [ "test_demo::slow", "--env", "plain,other", "--fp", "32,64",
                             "--method", "cg,direct", "-j", "4" ], argv
        finally:
            put_back( kept )


if test( "every case of a file is the file" ):
    with tempfile.TemporaryDirectory() as tmp:
        session, kept = a_session( a_project( tmp ) )
        try:
            # Shorter, and it stays true when a case is added tomorrow.
            assert session.pattern_for( session.entries ) == "test_demo"
        finally:
            put_back( kept )


if test( "a tag that says nothing offers every value it could have" ):
    with tempfile.TemporaryDirectory() as tmp:
        session, kept = a_session( a_project( tmp ) )
        try:
            # `fp = "32|64"` is two boxes, because that is what it means.
            assert session.tag_values() == { "fp": [ "32", "64" ] }
        finally:
            put_back( kept )


# ── where it will land, and what came back ───────────────────────────────────

if test( "the session knows where every run will write, before it runs" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )
        session, kept = a_session( project )
        try:
            plan = session.predict( [ "test_demo::slow", "--env", "plain,other", "--n", "1,2" ] )
            assert len( plan ) == 4, plan
            assert { row[ "place" ] for row in plan } == { R.place( "plain" ), R.place( "other" ) }

            code, output = run_errand( project, "test_demo::slow", "--env", "plain,other",
                                       "--n", "1,2" )
            assert code == 0, output

            states = session.states_of( plan )
            assert [ s[ "status" ] for s in states ] == [ "PASS" ] * 4, states
            # Predicted before, found after -- and with it the file the case
            # wrote, which is what a pane can face.
            for state in states:
                assert state[ "output" ].exists()
                assert "turns of cg" in "\n".join( session.tail( state[ "output" ] ) )
                assert state[ "dir" ] / "result.yaml" in session.files_of( state[ "dir" ] )
        finally:
            put_back( kept )


if test( "a command cannot be read is still a command worth running" ):
    with tempfile.TemporaryDirectory() as tmp:
        session, kept = a_session( a_project( tmp ) )
        try:
            # No panes for it, and it says so by having no rows -- rather than
            # refusing, or worse, watching the wrong files.
            assert session.predict( [ "--nonsense" ] ) == [ ]
        finally:
            put_back( kept )


if test( "the history holds commands, and gives them back as they were typed" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = a_project( tmp )
        run_errand( project, "test_demo::quick", "--env", "other" )
        session, kept = a_session( project )
        try:
            assert session.history()[ 0 ] == "test_demo::quick --env other"
            assert session.args_of( "errand test_demo::quick --env other" ) == \
                   [ "test_demo::quick", "--env", "other" ]
        finally:
            put_back( kept )
