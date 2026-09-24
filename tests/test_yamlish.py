"""errand writes YAML without PyYAML; what it writes it must read back."""
import math

from errand import test
from errand.yamlish import dump, load


SHAPES = [
    { "name": "cost", "line": 42, "ok": True, "error": None },
    { "params": { "n": 5000, "method": "newton" }, "results": { "seconds": 12.406 } },
    { "tags": { "driver": "jax", "cuda": True, "fp": "64" } },
    { "list": [ 1, 2, 3 ], "empty_list": [ ], "empty_map": { } },
    { "entries": { "a": { "status": "PASS", "runs": 1 },
                   "b": { "status": "FAIL", "runs": 2 } } },
]


if test( "round trip" ):
    for shape in SHAPES:
        assert load( dump( shape ) ) == shape, shape


if test( "strings that could be mistaken for something else" ):
    tricky = {
        "version"  : "64",          # must come back a string, not an int
        "empty"    : "",
        "colon"    : "a: b",
        "hash"     : "a #b",
        "quote"    : "it's",
        "brace"    : "{ x }",
        "yes"      : "yes",
        "nullish"  : "null",
        "leading"  : " padded",
    }
    assert load( dump( tricky ) ) == tricky


if test( "floats survive" ):
    values = { "tiny": 1e-18, "big": 1e18, "third": 1 / 3, "neg": -0.0 }
    back = load( dump( values ) )
    for k, v in values.items():
        assert back[ k ] == v, ( k, v, back[ k ] )


if test( "not-a-number does not take the file down" ):
    # A run that produced inf or nan should still get a readable result file.
    text = dump( { "x": float( "inf" ), "y": float( "nan" ) } )
    back = load( text )
    assert isinstance( back[ "x" ], str ) and "inf" in back[ "x" ]
    assert isinstance( back[ "y" ], str ) and "nan" in back[ "y" ]


if test( "output is plain YAML" ):
    # If PyYAML happens to be around, it must agree with us -- the promise is
    # that the file is readable by anything, not only by errand.
    try:
        import yaml
    except ImportError:
        pass
    else:
        for shape in SHAPES:
            assert yaml.safe_load( dump( shape ) ) == shape, shape
