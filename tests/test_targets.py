"""Targets: paths from the cwd, `::` for an entry, the same globs on both sides."""
import os
import tempfile
from pathlib import Path

from errand import test
from errand import targets as T


def a_tree( tmp ):
    root = Path( os.path.realpath( tmp ) )
    files = [ root / p for p in ( "tests/ot/test_ot.py", "tests/ot/test_grad.py",
                                  "tests/shapes/test_ot.py", "bench/bench_fft.py" ) ]
    for f in files:
        f.parent.mkdir( parents = True, exist_ok = True )
        f.write_text( "from errand import test\n" )
    ( root / "src" ).mkdir()
    ( root / "src" / "lib.py" ).write_text( "x = 1\n" )
    return root, files


def picked( specs, root ):
    return sorted( str( f.relative_to( root ) ) for matched, _ in specs for f in matched )


if test( "a comma outside braces separates targets, and `\\,` is only a comma" ):
    assert T.split( "a.py::x,b/{c,d}.py::{e,f}" ) == [ "a.py::x", "b/{c,d}.py::{e,f}" ]
    assert T.expand( T.split( "x\\,y.py" )[ 0 ] ) == [ "x,y.py" ]


if test( "braces are alternatives, nested ones included, as a shell expands them" ):
    assert T.expand( "t/{a,b{1,2}}.py" ) == [ "t/a.py", "t/b1.py", "t/b2.py" ]
    # A brace with no comma is not an alternative, and an escaped one is a brace.
    assert T.expand( "x{y}.py" ) == [ "x{y}.py" ]
    assert T.expand( "a\\{b,c}" ) == [ "a{b,c}" ]


if test( "`**` is any depth, none included; `*` stays inside a directory" ):
    rx = T.path_regex( "/r/**/test_*.py" )
    assert rx.match( "/r/test_a.py" ) and rx.match( "/r/x/y/test_b.py" )
    assert not rx.match( "/r/x/test.py" )
    assert not T.path_regex( "/r/*.py" ).match( "/r/x/a.py" )


if test( "a class is a class on the name side too: the same glob everywhere" ):
    assert T.name_matches( "test_basic[[]3]", "test_basic[3]" )
    assert not T.name_matches( "test_basic[3]", "test_basic[3]" )
    assert T.name_matches( "[!a-c]z", "dz" ) and not T.name_matches( "[!a-c]z", "bz" )
    # What the screen writes designates that name and no other.
    for name in ( "test_basic[3]", "grad_*", "a, b", "{x}" ):
        assert T.name_matches( T.expand( T.escape( name ) )[ 0 ], name ), name
        assert not T.name_matches( T.expand( T.escape( name ) )[ 0 ], name + "x" ), name


if test( "a path is read from the cwd, and a directory is everything under it" ):
    with tempfile.TemporaryDirectory() as tmp:
        root, files = a_tree( tmp )
        specs = T.resolve( "ot/test_ot.py", files, cwd = root / "tests", root = root )
        assert picked( specs, root ) == [ "tests/ot/test_ot.py" ]
        specs = T.resolve( "../bench", files, cwd = root / "tests", root = root )
        assert picked( specs, root ) == [ "bench/bench_fft.py" ]
        specs = T.resolve( "tests/ot", files, cwd = root, root = root )
        assert picked( specs, root ) == [ "tests/ot/test_grad.py", "tests/ot/test_ot.py" ]


if test( "two files with one name are two files, and a glob takes both" ):
    with tempfile.TemporaryDirectory() as tmp:
        root, files = a_tree( tmp )
        specs = T.resolve( "**/test_ot.py::basic", files, cwd = root, root = root )
        assert picked( specs, root ) == [ "tests/ot/test_ot.py", "tests/shapes/test_ot.py" ]
        assert { name for _, name in specs } == { "basic" }
        # A glob may name a directory too.
        specs = T.resolve( "**/sha*", files, cwd = root, root = root )
        assert picked( specs, root ) == [ "tests/shapes/test_ot.py" ]


if test( "braces on the name side are several specs over the same files" ):
    with tempfile.TemporaryDirectory() as tmp:
        root, files = a_tree( tmp )
        specs = T.resolve( "tests/ot/test_ot.py::{basic,grad_*}", files, cwd = root, root = root )
        assert [ name for _, name in specs ] == [ "basic", "grad_*" ]
        assert all( spec.text == "tests/ot/test_ot.py::{basic,grad_*}" for spec in specs )


if test( "no target is everything under the cwd" ):
    with tempfile.TemporaryDirectory() as tmp:
        root, files = a_tree( tmp )
        specs = T.resolve( None, files, cwd = root / "tests" / "ot", root = root )
        assert picked( specs, root ) == [ "tests/ot/test_grad.py", "tests/ot/test_ot.py" ]
        # From outside the project, the project.
        specs = T.resolve( None, files, cwd = Path( "/" ), root = root )
        assert len( picked( specs, root ) ) == len( files )


if test( "a target that designates nothing is an error, with something to do about it" ):
    with tempfile.TemporaryDirectory() as tmp:
        root, files = a_tree( tmp )
        near = lambda typed: [ "tests/ot/test_ot.py" ]

        def refused( pattern ):
            try:
                T.resolve( pattern, files, cwd = root, root = root, suggest = near )
            except ValueError as err:
                return str( err )
            raise AssertionError( f"{pattern!r} was accepted" )

        assert "no such file or directory" in refused( "tests/ot/test_to.py" )
        assert "did you mean" in refused( "tests/ot/test_to.py" )
        assert "no entry runner takes it" in refused( "src/lib.py" )
        assert "matches no file" in refused( "**/nothing_*.py" )
        # One bad target among good ones is still a typo.
        assert "no such file" in refused( "tests/ot,tests/nope.py" )
