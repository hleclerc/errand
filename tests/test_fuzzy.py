"""Finding a case by typing a little of it."""
from errand import test
from errand import fuzzy as F


def best( query, candidates, **kw ):
    """The order `query` puts those candidates in."""
    ranked = F.rank( query, candidates, lambda s: { "it": ( s, 1.0 ) } )
    return [ item for item, _, _ in ranked ]


if test( "the letters have to be there, in order" ):
    assert F.score( "abc", "xaxbxc" ) is not None
    assert F.score( "abc", "cba" ) is None
    assert F.score( "abc", "ab" ) is None, "all of them, not most of them"
    assert F.score( "", "anything" ) == ( 0.0, [ ] )


if test( "what matched comes back with it" ):
    got = F.score( "tsq", "test_shapes_quick" )
    assert got is not None
    _, where = got
    assert "".join( "test_shapes_quick"[ i ] for i in where ) == "tsq"
    # And it lands on the starts of the words, which is where a reader looks.
    assert where == [ 0, 5, 12 ], where


if test( "together beats scattered, and the start of a word beats the middle" ):
    assert F.score( "ab", "abxxxx" )[ 0 ] > F.score( "ab", "axbxxx" )[ 0 ]
    assert F.score( "sh", "test_shapes" )[ 0 ] > F.score( "sh", "flushed_x" )[ 0 ]
    # Shorter wins when nothing else separates them.
    assert F.score( "ab", "ab" )[ 0 ] > F.score( "ab", "ab_and_more_of_it" )[ 0 ]


if test( "what an editor's go-to-file does, on real names" ):
    files = [ "tests/test_shapes.py", "tests/test_queue.py", "src/shapes.py",
              "bench/shapes_gpu.py", "tests/_infra.py" ]
    # The case everybody types: initials of the words.
    assert best( "tsq", files )[ 0 ] == "tests/test_queue.py"
    # A word, and the file named after it comes first -- not the one that
    # merely contains the letters.
    assert best( "shapes", files )[ 0 ] == "src/shapes.py"
    assert "tests/_infra.py" not in best( "shapes", files )


if test( "a second word narrows, it does not rewrite" ):
    rows = [ "solve  bench/solvers.py  gpu fp64",
             "solve  bench/solvers.py  cpu",
             "gradient  bench/solvers.py  gpu" ]
    ranked = best( "solve gpu", rows )
    assert ranked[ 0 ] == rows[ 0 ], ranked
    assert rows[ 1 ] not in ranked, "the row without gpu is out"
    # `solve` does reach `solvers.py`, so the third row is in -- lower, which
    # is the difference between a filter and a ranking.
    assert rows[ 2 ] in ranked
    # Every word has to find something; one that does not drops the row.
    assert best( "solve nowhere", rows ) == [ ]


if test( "a word may be found in any of the fields, and the best one counts" ):
    # The name says shapes, the tags say gpu: two words, two fields, one row.
    entries = [ { "name": "shapes", "file": "tests/test_geometry.py", "tags": "gpu slow" },
                { "name": "shapes", "file": "tests/test_geometry.py", "tags": "cpu" } ]
    ranked = F.rank( "shapes gpu", entries, lambda e: {
        "name": ( e[ "name" ], 1.0 ), "file": ( e[ "file" ], 0.8 ), "tags": ( e[ "tags" ], 0.9 ) } )
    assert [ e[ "tags" ] for e, _, _ in ranked ] == [ "gpu slow" ]
    _, _, marks = ranked[ 0 ]
    assert "name" in marks and "tags" in marks, marks


if test( "a candidate longer than anybody reads is cut, not refused" ):
    long_one = "x" * 5000 + "needle"
    assert F.score( "needle", long_one ) is None
    assert F.score( "x", long_one ) is not None
