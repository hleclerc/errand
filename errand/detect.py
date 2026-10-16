"""What `errand init` suggests: a starting `errand-envs.py`, and an `errand-project.py`
with the runner lines that would fit what is in the directory.

Nothing here is used to RUN anything: what a target means is read from the
command line alone. A suggestion is only ever written down, in comments, for
somebody to read and keep -- it lists directories and reads a few files, and
runs nothing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .discovery import SKIP_DIRS
from .runner import MARKER

# Where a suite usually lives, tried in this order before looking anywhere else.
PY_DIRS  = ( "tests", "test" )
CPP_DIRS = ( "tests", "test", "cpp", "tests/cpp", "src" )
DEPTH    = 2          # how far below the root a manifest or a C++ suite is looked for


@dataclass
class Guess:
    kind  : str        # "pytest" | "catch2" | "cargo"
    label : str        # "pytest (tests/)"
    line  : str        # the errand-project.py line that says the same thing
    make  : object     # () -> Runner
    targets: tuple = ( )   # what a bare `errand run` would mean for it


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
    from .runner import Pytest

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
                  f"errand.runners.replace( errand.Pytest( dirs = [ {args} ] ) )",
                  lambda: Pytest( dirs = dirs ),
                  tuple( "**::*" if d == "." else f"{d.rstrip( '/' )}/**::*" for d in dirs ) )


def _catch2( root: Path ):
    from .runner import Catch2

    for d in _walk( root ):
        found = [ p for p in d.glob( "test_*.cpp" ) if "catch" in _read( p ).lower() ]
        if not found:
            continue
        rel = d.relative_to( root ).as_posix()
        rel = "." if rel == "." else rel
        build = f"make -C {rel}" if ( d / "Makefile" ).exists() else None
        line = f"errand.runners.replace( errand.Catch2( dir = {rel!r}" + ( f", build = {build!r}" if build else "" ) + " ) )"
        return Guess( "catch2", f"catch2 ({rel}/)", line,
                      lambda: Catch2( dir = root / rel, build = build ),
                      ( "**::*" if rel == "." else f"{rel}/**::*", ) )
    return None


def _cargo( root: Path ):
    from .runner import Cargo

    for d in _walk( root ):
        if ( d / "Cargo.toml" ).is_file():
            rel = ( d / "Cargo.toml" ).relative_to( root ).as_posix()
            line = ( "errand.runners.replace( errand.Cargo( ) )" if rel == "Cargo.toml"
                     else f"errand.runners.replace( errand.Cargo( manifest = {rel!r} ) )" )
            where = "./" if rel == "Cargo.toml" else rel.rsplit( "/", 1 )[ 0 ] + "/"
            return Guess( "cargo", f"cargo ({where})", line,
                          lambda: Cargo( manifest = root / rel ) )
    return None


def guess( root: Path ) -> list[ Guess ]:
    """The existing suites below `root`, as configured runners would adopt them."""
    return [ g for g in ( _pytest( root ), _catch2( root ), _cargo( root ) ) if g ]


# ── errand-project.py, written ───────────────────────────────────────────────────

def has_entries( root: Path, exclude = ( ) ) -> bool:
    from .discovery import errand_files
    return bool( errand_files( root, exclude ) )


def render( root: Path ) -> str:
    """The text of an `errand-project.py`, with the runner lines that would fit
    what is here written as suggestions -- in comments, never active."""
    found = guess( root )
    own   = has_entries( root )
    out = [
        '"""What this project does: how its work is run, and what a bare `errand run` means.',
        "",
        "Written by `errand init`; edit freely. Everything here is optional -- `errand run <command>`",
        "works without it. This file is versioned; where the project RUNS ( environments, which",
        "depend on the user and the machine ) is `errand-envs.py`, which is not.",
        '"""',
        "import errand",
        "",
    ]
    if found:
        out += [ "# What was recognised here. pytest, Catch2 and cargo are runners already: these lines",
                 "# only matter if the defaults do not fit ( a directory, a build command ). Uncomment to keep." ]
        out += [ "# " + g.line for g in found ]
        out += [ "" ]
    if found or own:
        targets = [ t for g in found for t in g.targets ]
        shown = ", ".join( repr( t ) for t in dict.fromkeys( targets or [ "**::*" ] ) )
        out += [ "# What a bare `errand run` runs: targets from the project root.",
                 f"# errand.default_run = [ {shown} ]", "" ]
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
        "# errand.envs[ 'local' ] = errand.Env( [ errand.Micromamba( 'myproject', python = '3.13',",
        "#                                                         requirements = 'requirements.txt' ) ] )",
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
    """Write `errand-project.py` and a commented `errand-envs.py`."""
    from .config import CONFIG_FILE, ENVS_FILE, VARS_FILE, config_in

    path = config_in( root )
    if path is not None and not force:
        echo( f"  {path.name} already exists here; init does not overwrite it "
              f"( errand init --force to replace it )" )
        return 1
    ( root / CONFIG_FILE ).write_text( render( root ) )
    echo( f"  wrote {CONFIG_FILE}    ( what the project does; versioned )" )
    if not ( root / ENVS_FILE ).exists():
        ( root / ENVS_FILE ).write_text( render_envs() )
        echo( f"  wrote {ENVS_FILE}    ( where YOU run it; not versioned )" )

    _ignore( root, ".errand/", echo )
    _ignore( root, "runs/", echo )
    _ignore( root, ENVS_FILE, echo )
    _ignore( root, VARS_FILE, echo )
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