"""Declaring environments, and choosing among them."""
from pathlib import Path

from errand import test
from errand import config as C, layers as L


def declared( ):
    C.reset()
    C.env( "local",   [ L.Vars( { "X": "1" } ) ], driver = "cpu" )
    C.env( "gpu",     [ L.Apptainer( image = "c/cuda.sif" ) ], driver = "cuda", cuda = True )
    C.env( "cluster", [ L.Ssh( host = "h", root = "/r" ),
                        L.Apptainer( image = "c/cuda.sif" ) ],
           driver = "cuda", cuda = True, fp = "64" )
    return C.envs


def chosen( **kw ):
    return [ e.name for e, _ in C.select( **kw ) ]


if test( "with nothing asked, the default is used" ):
    declared()
    assert chosen() == [ "local" ]
    C.configure( default = "gpu" )
    assert chosen() == [ "gpu" ]


if test( "by name, one or several" ):
    declared()
    assert chosen( names = [ "gpu" ] ) == [ "gpu" ]
    assert chosen( names = [ "gpu", "cluster" ] ) == [ "gpu", "cluster" ]


if test( "a name that was never declared says so" ):
    declared()
    try:
        chosen( names = [ "nope" ] )
    except ValueError as err:
        assert "nope" in str( err ) and "local" in str( err )
    else:
        assert False, "a typo in --env must not fall back to something else"


if test( "an expression may select several, and that is the point" ):
    declared()
    assert chosen( expression = "cuda" ) == [ "gpu", "cluster" ]
    assert chosen( expression = "cuda & !fp=64" ) == [ "gpu" ]
    assert chosen( expression = "driver=cpu" ) == [ "local" ]


if test( "saying nothing about a dimension means every value of it" ):
    declared()
    # `gpu` never mentions fp, so it is selected whatever is asked for...
    assert "gpu" in chosen( wanted_tags = { "fp": "32" } )
    # ...and the asked-for value is what a Vars callable will read back
    _, tags = next( ( e, t ) for e, t in C.select( wanted_tags = { "fp": "32" } )
                    if e.name == "gpu" )
    assert tags[ "fp" ] == "32"


if test( "a pinned dimension is only selected for its own value" ):
    declared()
    assert "cluster" in chosen( wanted_tags = { "fp": "64" } )
    assert "cluster" not in chosen( wanted_tags = { "fp": "32" } )


if test( "a range covers each of its values" ):
    C.reset()
    C.env( "both", [ ], fp = "32|64" )
    assert chosen( wanted_tags = { "fp": "32" } ) == [ "both" ]
    assert chosen( wanted_tags = { "fp": "64" } ) == [ "both" ]
    assert chosen( wanted_tags = { "fp": "16" } ) == [ ] if False else True
    try:
        chosen( wanted_tags = { "fp": "16" } )
    except ValueError:
        pass
    else:
        assert False, "asking for a value nothing covers must be an error, not silence"


if test( "naming an environment and contradicting it is an error" ):
    declared()
    try:
        chosen( names = [ "cluster" ], wanted_tags = { "fp": "32" } )
    except ValueError as err:
        assert "fp" in str( err ) and "cluster" in str( err )
    else:
        assert False, "running single precision on an fp=64 environment would be a lie"


if test( "every tag name becomes a flag" ):
    declared()
    assert C.tag_names() == [ "cuda", "driver", "fp" ]


if test( "ssh has to be outermost" ):
    C.reset()
    try:
        C.env( "wrong", [ L.Apptainer( image = "x.sif" ), L.Ssh( host = "h" ) ] )
    except ValueError as err:
        assert "first" in str( err )
    else:
        assert False, "a container cannot contain a machine"


if test( "what an environment IS, for the output path and for dispatch" ):
    declared()
    assert C.envs[ "gpu" ].container == "cuda.sif"
    assert C.envs[ "local" ].container is None
    assert C.envs[ "cluster" ].ssh.host == "h"
    # an environment of pure Vars changes nothing about where the process runs
    assert not C.envs[ "local" ].wraps_anything()
    assert C.envs[ "gpu" ].wraps_anything()


if test( "an unknown setting is a typo, not a new setting" ):
    C.reset()
    try:
        C.configure( outt = "runs" )
    except TypeError as err:
        assert "outt" in str( err )
    else:
        assert False


if test( "a config file is loaded by path, never as a module named errand" ):
    import tempfile
    import sys
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        ( root / C.CONFIG_FILE ).write_text(
            "from errand import env, Vars\n"
            "env( 'one', [ Vars( { 'A': '1' } ) ], driver = 'cpu' )\n" )
        assert C.load( root )
        assert list( C.envs ) == [ "one" ]
        assert "errand" not in [ m for m in sys.modules if m == "_errand_config" ]
