"""`errand init` reads a directory for what it holds, and writes suggestions down -- in comments.

Nothing here runs a toolchain, and nothing here decides what a run does: detection lists
directories and reads a few files, and only `errand init` uses it.
"""
import tempfile
from pathlib import Path

from errand import test, detect

from _infra import run_errand


def project( files: dict ) -> Path:
    root = Path( tempfile.mkdtemp( prefix = "errand-detect-" ) )
    for name, text in files.items():
        ( root / name ).parent.mkdir( parents = True, exist_ok = True )
        ( root / name ).write_text( text )
    return root


if test( "a conventional layout is recognised, all three of them" ):
    root = project( {
        "tests/test_api.py": "def test_x():\n    assert True\n",
        "cpp/test_geo.cpp":  '#include <catch2/catch_test_macros.hpp>\nTEST_CASE("a"){}\n',
        "cpp/Makefile":      "all:\n",
        "rust/Cargo.toml":   '[package]\nname = "x"\n',
    } )
    got = {g.kind: g for g in detect.guess( root )}
    assert set( got ) == { "pytest", "catch2", "cargo" }, got
    assert got[ "pytest" ].line == "errand.runners.replace( errand.Pytest( dirs = [ 'tests' ] ) )"
    assert got[ "catch2" ].line == "errand.runners.replace( errand.Catch2( dir = 'cpp', build = 'make -C cpp' ) )"
    assert got[ "cargo" ].line == "errand.runners.replace( errand.Cargo( manifest = 'rust/Cargo.toml' ) )"
    assert got[ "pytest" ].targets == ( "tests/**::*", )


if test( "files written in errand's own guard are not pytest's to collect" ):
    root = project( { "tests/test_a.py": "from errand import test\nif test( 'a' ):\n    pass\n" } )
    assert detect.guess( root ) == [ ]


if test( "a C++ file that never mentions Catch is not a Catch2 suite" ):
    root = project( { "tests/test_a.cpp": "int main(){}\n" } )
    assert detect.guess( root ) == [ ]


if test( "`errand init` writes the suggestions down, in comments, and refuses to overwrite" ):
    root = project( { "tests/test_api.py": "def test_x():\n    pass\n", ".git/HEAD": "ref: x\n" } )
    rc, out = run_errand( root, "init" )
    assert rc == 0, out
    text = ( root / "errand-project.py" ).read_text()
    assert "# errand.runners.replace( errand.Pytest( dirs = [ 'tests' ] ) )" in text
    assert "# errand.default_run = [ 'tests/**::*' ]" in text
    compile( text, "errand-project.py", "exec" )
    ignored = ( root / ".gitignore" ).read_text()
    assert ".errand/" in ignored and "runs/" in ignored

    rc, out = run_errand( root, "init" )
    assert rc == 1 and "already exists" in out, out


if test( "`errand init` in an empty directory still gives a file worth editing" ):
    root = project( { } )
    rc, out = run_errand( root, "init" )
    assert rc == 0, out
    text = ( root / "errand-project.py" ).read_text()
    compile( text, "errand-project.py", "exec" )
    envs = ( root / "errand-envs.py" ).read_text()
    compile( envs, "errand-envs.py", "exec" )
    assert "Micromamba" in envs and "Apptainer" in envs      # where it runs, in view from the start
