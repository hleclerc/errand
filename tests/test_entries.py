"""Declaring work: its four names, parameters and matrices."""
from errand import test, bench, experiment, entry, track, Param
from errand import entries as E
from errand.cli import expand


def collected_of( fn ):
    """Run `fn` in the collect phase and hand back what it registered."""
    E.reset_collection()
    fn()
    return list( E.collected )


if test( "test, bench, track and experiment are one declaration under four names" ):
    got = collected_of( lambda: ( test( "a" ), bench( "b" ), track( "t" ), experiment( "c" ) ) )
    assert [ e.name for e in got ] == [ "a", "b", "t", "c" ]
    assert all( e.resources == { } and e.params == { } for e in got )


if test( "what an entry used to say of the machine is the command's now, and it is told so" ):
    for word, where in ( ( "exclusive", "-x" ), ( "cpus", "--cpus" ), ( "bulk", "default_run" ),
                         ( "keep", "comparable" ), ( "stable_path", "latest/" ) ):
        try:
            collected_of( lambda: bench( "b", **{ word: True } ) )
            raise AssertionError( f"{word} was taken" )
        except TypeError as err:
            assert word in str( err ) and where in str( err ), err


if test( "an entry is its call site, so two may share a name" ):
    def two( ):
        test( "same" )
        test( "same" )
    got = collected_of( two )
    assert len( got ) == 2
    assert got[ 0 ].site != got[ 1 ].site
    # and the site is the USER's line, not the preset's inside errand
    assert all( e.file.name == "test_entries.py" for e in got )


if test( "a Param is a parameter; anything else must be a known word" ):
    got = collected_of( lambda: entry( "e", n = Param( 10 ), ranks = 4 ) )
    assert list( got[ 0 ].params ) == [ "n" ]
    assert got[ 0 ].resources == { "ranks": 4 }

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


if test( "with a separator, several values are a matrix" ):
    params = { "n": Param( 1 ), "m": Param( "a" ) }
    combos = expand( { "n": "1,2", "m": "x,y" }, params, sep = "," )
    assert len( combos ) == 4
    assert { tuple( sorted( ( k, v ) for k, v in values.items() if k != "args" ) ) for _, values in combos } == {
        ( ( "m", "x" ), ( "n", 1 ) ), ( ( "m", "y" ), ( "n", 1 ) ),
        ( ( "m", "x" ), ( "n", 2 ) ), ( ( "m", "y" ), ( "n", 2 ) ),
    }


if test( "only what actually varied is called out" ):
    params = { "n": Param( 1 ), "m": Param( "a" ) }
    combos = expand( { "n": "1,2", "m": "x" }, params, sep = "," )
    assert [ sorted( varied ) for varied, _ in combos ] == [ [ "n" ], [ "n" ] ]


if test( "no override at all is one silent combination" ):
    assert expand( { "n": None }, { "n": Param( 1 ) } ) == [ ( { }, { "args": [ ] } ) ]


if test( "choices are checked before anything runs" ):
    params = { "m": Param( "cg", choices = [ "cg", "direct" ] ) }
    try:
        expand( { "m": "cg,newton" }, params, sep = "," )
    except ValueError as err:
        assert "newton" in str( err )
    else:
        assert False, "a value outside choices must not reach the body"
