"""One grammar, read over environments, over entries, and inside a file."""
from errand import test
from errand.expr import format_tags, matches, names


ENV = { "driver": "jax", "cuda": True, "fp": "64" }


if test( "a bare name asks only that the tag is there" ):
    assert matches( "cuda", ENV )
    assert matches( "driver", ENV )
    assert not matches( "rocm", ENV )


if test( "a value has to agree" ):
    assert matches( "fp=64", ENV )
    assert not matches( "fp=32", ENV )
    assert matches( "driver=jax", ENV )


if test( "a bare true reads as the name alone" ):
    assert matches( "cuda=True", ENV )
    assert matches( "cuda=true", ENV )
    assert not matches( "cuda=false", ENV )


if test( "negation" ):
    assert matches( "!rocm", ENV )
    assert not matches( "!cuda", ENV )
    assert matches( "!fp=32", ENV )


if test( "and binds tighter than or" ):
    assert matches( "cuda & fp=64", ENV )
    assert not matches( "cuda & fp=32", ENV )
    assert matches( "cuda & fp=32 | driver=jax", ENV )      # (a & b) | c
    assert not matches( "rocm & driver=jax | fp=32", ENV )


if test( "an empty expression asks for nothing" ):
    assert matches( "", ENV )
    assert matches( None, ENV )


if test( "a list of entry tags reads the same way" ):
    marks = [ "slow", "gpu" ]
    assert matches( "slow", marks )
    assert matches( "slow & !flaky", marks )
    assert not matches( "!slow", marks )


if test( "the names an expression mentions" ):
    assert names( "cuda & !fp=32 | driver=torch" ) == { "cuda", "fp", "driver" }


if test( "formatting is what crosses an ssh hop" ):
    assert format_tags( ENV ) == "cuda,driver=jax,fp=64"
    # ...and comes back meaning the same thing
    back = { }
    for item in format_tags( ENV ).split( "," ):
        k, _, v = item.partition( "=" )
        back[ k ] = v if v else True
    assert matches( "cuda & driver=jax & fp=64", back )
