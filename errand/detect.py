"""What a directory is made of, read from its content -- and the errand-project.py that says so.

errand with no `errand-project.py` still has to find the work. For entries that are
errand's own that is a text check ( see `discovery` ); for a suite that already
exists it is a guess about the layout, because every framework locates its
tests by assuming something. This module makes that guess, cheaply -- it lists
directories and reads a few files, and runs nothing -- so that it can be

* announced before a run ( the guess is never silent ), and
* written down by `errand --init`, which is how a guess becomes a declaration.

A guess is a `Guess`: the provider to use, the line of `errand-project.py` that
would build it, and a short label for the announcement.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .discovery import MARKER, SKIP_DIRS

# Where a suite usually lives, tried in this order before looking anywhere else.
PY_DIRS  = ( "tests", "test" )
CPP_DIRS = ( "tests", "test", "cpp", "tests/cpp", "src" )
DEPTH    = 2          # how far below the root a manifest or a C++ suite is looked for


@dataclass
class Guess:
    kind  : str        # "pytest" | "catch2" | "cargo"
    label : str        # "pytest (tests/)"
    line  : str        # the errand-project.py line that says the same thing
    make  : object     # () -> Provider


def _walk( root: Path, depth: int = DEPTH ):
    """Directories below `root`, nearest first, without the ones nobody means."""
    from .config import config_in
    level = [ root ]
    for _ in range( depth + 1 ):
        nxt = [ ]
        for d in level:
            yield d
            try:
                children = sorted( c for c in d.iterdir() if c.is_dir() )
            except OSError:
                continue
            nxt += [ c for c in children
                     if c.name not in SKIP_DIRS and not c.name.endswith( ".egg-info" )
                     and config_in( c ) is None ]
        level = nxt


def _read( path: Path ) -> str:
    try:
        return path.read_text( errors = "ignore" )
    except OSError:
        return ""


def _is_foreign_python( path: Path ) -> bool:
    """A pytest-style file that is NOT written in errand's own guard."""
    return not MARKER.search( _read( path ) )


def _pytest( root: Path ):
    from .providers import Pytest

    def foreign( d: Path ):
        return [ p for pat in ( "test_*.py", "*_test.py" ) for p in d.glob( pat )
                 if _is_foreign_python( p ) ]

    dirs = [ d for d in PY_DIRS if foreign( root / d ) ]
    if not dirs and foreign( root ):
        dirs = [ "." ]
    if not dirs:
        # a configured pytest without the conventional directory name
        for d in _walk( root, 1 ):
            if d != root and foreign( d ) and d.name not in ( "examples", "docs" ):
                dirs.append( str( d.relative_to( root ) ) )
    if not dirs:
        return None
    args = ", ".join( repr( d ) for d in dirs )
    return Guess( "pytest", "pytest (" + ", ".join( d.rstrip( "/" ) + "/" if d != "." else "./"
                                                   for d in dirs ) + ")",
                  f"errand.provider( errand.Pytest( dirs = [ {args} ] ) )",
                  lambda: Pytest( dirs = dirs, root = root ) )


def _catch2( root: Path ):
    from .providers import Catch2

    for d in _walk( root ):
        found = [ p for p in d.glob( "test_*.cpp" ) if "catch" in _read( p ).lower() ]
        if not found:
            continue
        rel = d.relative_to( root ).as_posix()
        rel = "." if rel == "." else rel
        build = f"make -C {rel}" if ( d / "Makefile" ).exists() else None
        line = f"errand.provider( errand.Catch2( dir = {rel!r}" + ( f", build = {build!r}" if build else "" ) + " ) )"
        return Guess( "catch2", f"catch2 ({rel}/)", line,
                      lambda: Catch2( dir = root / rel, build = build ) )
    return None


def _cargo( root: Path ):
    from .providers import Cargo

    for d in _walk( root ):
        if ( d / "Cargo.toml" ).is_file():
            rel = ( d / "Cargo.toml" ).relative_to( root ).as_posix()
            line = ( "errand.provider( errand.Cargo( ) )" if rel == "Cargo.toml"
                     else f"errand.provider( errand.Cargo( manifest = {rel!r} ) )" )
            where = "./" if rel == "Cargo.toml" else rel.rsplit( "/", 1 )[ 0 ] + "/"
            return Guess( "cargo", f"cargo ({where})", line,
                          lambda: Cargo( manifest = root / rel ) )
    return None


def guess( root: Path ) -> list[ Guess ]:
    """The existing suites below `root`, as providers would adopt them."""
    return [ g for g in ( _pytest( root ), _catch2( root ), _cargo( root ) ) if g ]


def announce( guesses: list ) -> str:
    return "no errand-*.py; guessed:  " + "  ·  ".join( g.label for g in guesses )


# ── errand-project.py, written ───────────────────────────────────────────────────

def has_entries( root: Path, exclude = ( ) ) -> bool:
    from .discovery import candidates
    return bool( candidates( root, exclude ) )


def render( root: Path ) -> str:
    """The text of an `errand-project.py` that says what errand would otherwise guess."""
    found = guess( root )
    own   = has_entries( root )
    out = [
        '"""What this project does: where its work is, and how it is built and run.',
        "",
        "Written by `errand --init` from what was found in the directory; edit freely. Everything",
        "here is optional -- errand works without this file -- but writing it down turns a guess",
        "into a declaration that is visible, versioned and arguable.",
        "",
        "errand reads every `errand-*.py` at the root. This one is versioned; where it RUNS",
        "( environments, which depend on the user and the machine ) is `errand-envs.py`, which is not.",
        '"""',
        "import errand",
        "",
        'errand.configure( out = "runs" )          # the one directory errand writes to',
        "",
    ]
    if found:
        out += [ "# Existing suites, adopted unmodified. Their own runner, assertions and marks stay",
                 "# theirs; what they gain is a directory per run, environments, a queue, summaries." ]
        out += [ g.line for g in found ]
        out += [ "" ]
    if own:
        out += [ "# Entries written with errand ( `if test( ... ):` ) are found without any line here." , "" ]
    if not found and not own:
        out += [ "# Nothing was found to run yet. Either point a provider at an existing suite:",
                 "#",
                 "#     errand.provider( errand.Pytest( dirs = [ 'tests' ] ) )",
                 "#     errand.provider( errand.Catch2( dir = 'cpp', build = 'make -C cpp' ) )",
                 "#     errand.provider( errand.Cargo( ) )",
                 "#",
                 "# or declare a piece of work next to the code it exercises ( see the docs ).",
                 "" ]
    return "\n".join( out )


def render_envs( ) -> str:
    """The text of an `errand-envs.py`: where THIS user runs the project, as a commented example."""
    return "\n".join( [
        '"""Where this project runs, for this user on this machine. Not versioned.',
        "",
        "An environment is a stack of layers ( micromamba, uv, Apptainer, Ssh, Slurm, ... ), read",
        "left to right, outermost first. Uncomment and adapt.",
        '"""',
        "import errand",
        "",
        "# errand.envs[ 'local' ] = errand.Env( [ errand.Micromamba( 'myproject', python = '3.13' ) ] )",
        "#",
        "# errand.envs[ 'cluster' ] = errand.Env(",
        "#     [ errand.Ssh( host = 'my-cluster', root = '~/errand/myproject' ),",
        "#       errand.Slurm( partition = 'gpu', time = '00:30:00' ),",
        "#       errand.Apptainer( image = 'containers/main.sif' ) ],",
        "#     gpu = True )",
        "#",
        "# errand.default_env = 'local'      # used when nothing is asked for; else the first declared",
        "",
    ] )


def init( root: Path, *, force: bool = False, echo = print ) -> int:
    """Write `errand-project.py` and a commented `errand-envs.py`, and make the output directory real."""
    from .config import CONFIG_FILE, ENVS_FILE, config_in

    path = config_in( root )
    if path is not None and not force:
        echo( f"  {path.name} already exists here; --init does not overwrite it "
              f"( --init=force to replace it )" )
        return 1
    ( root / CONFIG_FILE ).write_text( render( root ) )
    echo( f"  wrote {CONFIG_FILE}    ( what the project does; versioned )" )
    if not ( root / ENVS_FILE ).exists():
        ( root / ENVS_FILE ).write_text( render_envs() )
        echo( f"  wrote {ENVS_FILE}    ( where YOU run it; not versioned )" )

    out = root / "runs"
    out.mkdir( exist_ok = True )
    echo( "  made runs/    ( what errand writes; the output tree )" )
    _ignore( root, "runs/", echo )
    _ignore( root, ENVS_FILE, echo )
    return 0


def _ignore( root: Path, pattern: str, echo ):
    """Say to git that `pattern` is not source, if there is a git to tell."""
    if not ( root / ".git" ).exists():
        return
    gi = root / ".gitignore"
    text = _read( gi )
    bare = pattern.rstrip( "/" )
    if any( line.strip().rstrip( "/" ) in ( bare, "/" + bare ) for line in text.splitlines() ):
        return
    with gi.open( "a" ) as f:
        f.write( ( "" if not text or text.endswith( "\n" ) else "\n" ) + pattern + "\n" )
    echo( f"  added {pattern} to .gitignore" )