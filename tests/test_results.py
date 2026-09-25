"""The output tree: paths that can be predicted, summaries that repair themselves."""
import tempfile
from pathlib import Path

from errand import test
from errand import results as R
from errand.entries import Entry, Param, TRAITS


def an_entry( name = "cost", file = "bench/solvers.py", line = 42 ):
    return Entry( name, [ ], { "n": Param( 1000 ) }, dict( TRAITS ), { }, file, line, "m" )


if test( "the path is a function of the run, not of an invocation" ):
    e = an_entry()
    a, root_a = R.dirs_for( Path( "/out" ), e, { "n": 1000 }, "host" )
    b, root_b = R.dirs_for( Path( "/out" ), e, { "n": 1000 }, "host" )
    assert a == b and root_a == root_b
    # ...which is what lets the local side work out where a remote run will write
    assert str( root_a ) == "/out/solvers/cost", root_a
    # The run's own directory says when, where, and with what -- in that order,
    # and in words rather than in a hash.
    assert a.name == f"{R.stamp()}-host-n=1000", a.name


if test( "different parameters, different directory" ):
    e = an_entry()
    a, _ = R.dirs_for( Path( "/out" ), e, { "n": 1000 }, "host" )
    b, _ = R.dirs_for( Path( "/out" ), e, { "n": 2000 }, "host" )
    assert a != b


if test( "one flat list of runs under the case, however many dimensions" ):
    e = an_entry()
    leaf, root = R.dirs_for( Path( "/out" ), e, { }, "host" )
    assert leaf.parent == root            # the run is straight under the case
    assert leaf.name == f"{R.stamp()}-host", leaf.name
    # A matrix is more NAMES, never more levels: `cd` to a run, not through one.
    deep, _ = R.dirs_for( Path( "/out" ), e, { "n": 5000, "method": "newton" }, "gpu@box" )
    assert deep.parent == root
    assert deep.name.endswith( "-gpu@box-method=newton,n=5000" ), deep.name


if test( "a parameter set too long to read is cut, and stays distinct" ):
    e = an_entry()
    long_a = { "label": "x" * 80, "n": 1 }
    long_b = { "label": "x" * 80, "n": 2 }
    a, b = R.params_tag( long_a ), R.params_tag( long_b )
    assert len( a ) <= R.ROOM + 7 and a != b, ( a, b )
    assert a.startswith( "label=xxxx" ), a


if test( "one stamp for a whole command, however many processes it becomes" ):
    import os
    import subprocess
    import sys

    # The child works out the same directory as the parent predicted for it --
    # which is the entire reason a path can be known before the run exists.
    child = subprocess.run( [ sys.executable, "-c",
                              "from errand import results; print( results.stamp() )" ],
                            capture_output = True, text = True,
                            env = { **os.environ, R.STAMP_ENV: R.stamp() } )
    assert child.stdout.strip() == R.stamp(), child


if test( "the order of parameters does not change the hash" ):
    assert R.param_hash( { "a": 1, "b": 2 } ) == R.param_hash( { "b": 2, "a": 1 } )


if test( "two entries of the same name in different files do not collide" ):
    a = R.label( an_entry( file = "one/solvers.py" ) )
    b = R.label( an_entry( file = "two/others.py" ) )
    assert a != b


if test( "a container is part of where it ran" ):
    assert R.place() == R.place( None )
    # Two environments on one machine are two sets of numbers, and a directory
    # each: before this, the second silently cleared the first.
    assert R.place( "gpu" ).endswith( "@" + R.place() )
    assert R.place( "gpu" ) != R.place( "cpu" )


if test( "summaries are rebuilt from the tree, at every level" ):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path( tmp )
        e = an_entry()

        for n, seconds in ( ( 1000, 1.0 ), ( 2000, 4.0 ) ):
            leaf, entry_root = R.dirs_for( out, e, { "n": n }, "host" )
            leaf.mkdir( parents = True )
            R.write_result( leaf, entry = e, root = out, env_name = "default",
                            where = "host", tags = { }, status = "PASS", error = None,
                            duration_s = seconds, ram = 1.0, params = { "n": n },
                            results = { "seconds": seconds, "count": n },
                            output_text = "", version = "t" )
        R.refresh( entry_root )

        top = R.yamlish.read( entry_root / R.SUMMARY )
        assert top[ "passed" ] == 2 and top[ "failed" ] == 0 and top[ "runs" ] == 2
        # per key, never one interval across unrelated quantities
        assert top[ "seconds" ] == [ 1.0, 4.0 ]
        assert top[ "count" ]   == [ 1000, 2000 ]


if test( "a single value does not read as a spread" ):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path( tmp )
        e = an_entry()
        leaf, entry_root = R.dirs_for( out, e, { "n": 1 }, "host" )
        leaf.mkdir( parents = True )
        R.write_result( leaf, entry = e, root = out, env_name = "default", where = "host",
                        tags = { }, status = "PASS", error = None, duration_s = 2.0,
                        ram = 1.0, params = { "n": 1 }, results = { "seconds": 2.0 },
                        output_text = "", version = "t" )
        R.refresh( entry_root )
        assert R.yamlish.read( entry_root / R.SUMMARY )[ "seconds" ] == 2.0


if test( "a failure is counted, not lost" ):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path( tmp )
        e = an_entry()
        for n, status in ( ( 1, "PASS" ), ( 2, "FAIL" ) ):
            leaf, entry_root = R.dirs_for( out, e, { "n": n }, "host" )
            leaf.mkdir( parents = True )
            R.write_result( leaf, entry = e, root = out, env_name = "default", where = "host",
                            tags = { }, status = status, error = None, duration_s = 1.0,
                            ram = 1.0, params = { "n": n }, results = { }, output_text = "",
                            version = "t" )
        R.refresh( entry_root )
        top = R.yamlish.read( entry_root / R.SUMMARY )
        assert ( top[ "passed" ], top[ "failed" ] ) == ( 1, 1 )


if test( "a value that never meant to be written degrades instead of crashing" ):
    class Opaque:
        def __repr__( self ): return "<opaque>"

    assert R._plain( { "x": Opaque() } ) == { "x": "<opaque>" }


if test( "the record says when, and not only which day" ):
    import datetime

    with tempfile.TemporaryDirectory() as tmp:
        out = Path( tmp )
        e = an_entry()
        leaf, _ = R.dirs_for( out, e, { }, "host" )
        leaf.mkdir( parents = True )
        data = R.write_result( leaf, entry = e, root = out, env_name = "default",
                               where = "host", tags = { }, status = "PASS", error = None,
                               duration_s = 1.0, ram = 1.0, params = { }, results = { },
                               output_text = "", version = "t" )
        # The directory carries the day -- that is all a path can carry and stay
        # readable -- so the record has to carry the hour, with its offset.
        when = datetime.datetime.fromisoformat( data[ "date" ] )
        assert when.tzinfo is not None, data[ "date" ]
        assert abs( ( datetime.datetime.now().astimezone() - when ).total_seconds() ) < 120
        assert R.yamlish.read( leaf / R.RESULT )[ "date" ] == data[ "date" ]
