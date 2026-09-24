"""Declaring work: presets, traits, parameters and matrices."""
from errand import test, bench, experiment, entry, Param
from errand import entries as E
from errand.cli import expand


def collected_of( fn ):
    """Run `fn` in the collect phase and hand back what it registered."""
    E.reset_collection()
    fn()
    return list( E.collected )


if test( "the presets are traits, nothing more" ):
    got = collected_of( lambda: ( test( "a" ), bench( "b" ), experiment( "c" ) ) )
    by_name = { e.name: e for e in got }
    assert by_name[ "a" ].traits == { "bulk": True,  "keep": False, "exclusive": False,
                                      "stable_path": False }
    assert by_name[ "b" ].traits == { "bulk": False, "keep": True,  "exclusive": True,
                                      "stable_path": False }
    assert by_name[ "c" ].traits == { "bulk": False, "keep": False, "exclusive": False,
                                      "stable_path": True }


if test( "a preset can be contradicted on the spot" ):
    got = collected_of( lambda: bench( "b", exclusive = False ) )
    assert got[ 0 ].traits[ "exclusive" ] is False
    assert got[ 0 ].traits[ "keep" ] is True       # the rest of the preset stands


if test( "kinds follow from traits" ):
    got = collected_of( lambda: ( test( "a" ), bench( "b" ), experiment( "c" ) ) )
    assert [ e.kind for e in got ] == [ "test", "bench", "experiment" ]


if test( "an entry is its call site, so two may share a name" ):
    def two( ):
        test( "same" )
        test( "same" )
    got = collected_of( two )
    assert len( got ) == 2
    assert got[ 0 ].key != got[ 1 ].key
    # and the site is the USER's line, not the preset's inside errand
    assert all( e.file.name == "test_entries.py" for e in got )


if test( "a Param is a parameter; anything else must be a known word" ):
    got = collected_of( lambda: entry( "e", n = Param( 10 ), cpus = 2, keep = True ) )
    assert list( got[ 0 ].params ) == [ "n" ]
    assert got[ 0 ].resources == { "cpus": 2 }
    assert got[ 0 ].traits[ "keep" ] is True

    try:
        collected_of( lambda: entry( "e", nonsense = 3 ) )
    except TypeError as err:
        assert "nonsense" in str( err ) and "Param" in str( err )
    else:
        assert False, "a typo in a keyword has to be an error, not a silent no-op"


if test( "tags read the same given either way" ):
    a = collected_of( lambda: test( "x", [ "slow" ] ) )[ 0 ]
    b = collected_of( lambda: test( "x", tags = [ "slow" ] ) )[ 0 ]
    assert a.tags == b.tags == [ "slow" ]
    c = collected_of( lambda: test( "x", "slow" ) )[ 0 ]
    assert c.tags == [ "slow" ]


if test( "a guard is falsy while collecting, so no body runs" ):
    E.reset_collection()
    ran = [ ]
    if test( "never" ):
        ran.append( 1 )
    assert ran == [ ]


# --- parameters -------------------------------------------------------------

if test( "a default stands when nothing overrides it" ):
    params = { "n": Param( 1000 ), "method": Param( "cg" ) }
    assert E.resolve_params( params, { } ) == { "n": 1000, "method": "cg" }


if test( "an override is read as the type of the default" ):
    params = { "n": Param( 1000 ) }
    assert E.resolve_params( params, { "n": "5000" } ) == { "n": 5000 }


if test( "an override that cannot be read says so" ):
    try:
        E.resolve_params( { "n": Param( 1000 ) }, { "n": "banana" } )
    except ValueError as err:
        assert "--n" in str( err ) and "int" in str( err )
    else:
        assert False, "a bad value must not silently become the default"


if test( "a comma is a matrix" ):
    params = { "n": Param( 1 ), "m": Param( "a" ) }
    combos = expand( { "n": "1,2", "m": "x,y" }, params )
    assert len( combos ) == 4
    assert { tuple( sorted( values.items() ) ) for _, values in combos } == {
        ( ( "m", "x" ), ( "n", 1 ) ), ( ( "m", "y" ), ( "n", 1 ) ),
        ( ( "m", "x" ), ( "n", 2 ) ), ( ( "m", "y" ), ( "n", 2 ) ),
    }


if test( "only what actually varied is called out" ):
    params = { "n": Param( 1 ), "m": Param( "a" ) }
    combos = expand( { "n": "1,2", "m": "x" }, params )
    assert [ sorted( varied ) for varied, _ in combos ] == [ [ "n" ], [ "n" ] ]


if test( "no override at all is one silent combination" ):
    assert expand( { "n": None }, { "n": Param( 1 ) } ) == [ ( { }, { } ) ]


if test( "choices are checked before anything runs" ):
    params = { "m": Param( "cg", choices = [ "cg", "direct" ] ) }
    try:
        expand( { "m": "cg,newton" }, params )
    except ValueError as err:
        assert "newton" in str( err )
    else:
        assert False, "a value outside choices must not reach the body"
