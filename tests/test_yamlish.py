"""errand writes YAML without PyYAML; what it writes it must read back."""
import math
import pathlib

from errand import test
from errand.yamlish import dump, load


SHAPES = [
    { "name": "cost", "line": 42, "ok": True, "error": None },
    { "params": { "n": 5000, "method": "newton" }, "results": { "seconds": 12.406 } },
    { "tags": { "driver": "jax", "cuda": True, "fp": "64" } },
    { "list": [ 1, 2, 3 ], "empty_list": [ ], "empty_map": { } },
    { "layers": { "0:venv:python3": "abc", "1:apptainer:cuda.sif": "def" } },
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


if test( "a key may hold a colon, or a comma" ):
    # `0:venv:python3` is unambiguous to a human and a trap for a parser: there
    # is nothing in the line that says which colon separates key from value.
    keyed = { "0:venv:python3": "abc", "a, b": 1, "plain": 2 }
    assert load( dump( keyed ) ) == keyed
    nested = { "layers": { "0:venv:python3": "abc", "1:apptainer:cuda.sif": "def" } }
    assert load( dump( nested ) ) == nested


if test( "a failure cannot corrupt the record of itself" ):
    # An assertion message is exactly the kind of value that has newlines in
    # it, and it is written to the same file that says the run failed.
    messy = { "error": "AssertionError: two lines\nand a\ttab",
              "trace": 'File "x.py", line 3\n  assert a == b\n' }
    assert load( dump( messy ) ) == messy


if test( "an unreadable file costs its own row, not the rebuild" ):
    import tempfile
    from errand.yamlish import read
    with tempfile.TemporaryDirectory() as tmp:
        broken = pathlib.Path( tmp ) / "result.yaml"
        broken.write_text( "  this was never ours\n:::\n" )
        assert read( broken ) is None
        assert read( pathlib.Path( tmp ) / "absent.yaml" ) is None


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
