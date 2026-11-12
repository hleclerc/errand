"""What every runner is: the `Runner` interface, how well it fits a file ( `Level` ), what it is
handed to run an entry ( `RunContext` ) and what it hands back ( `Outcome` ).
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from ..entries import Entry, TRAITS
from ..targets import name_matches


class Level( IntEnum ):
    """How well an entry runner fits a file. The highest wins; a tie at the top is an error."""
    NONE      = 0    # not this runner's
    FALLBACK  = 1    # kept for runners of a project's own that rank themselves low
    LANGUAGE  = 2
    FRAMEWORK = 3    # a suite of a framework it adopts: pytest, Catch2, cargo
    ERRAND    = 4    # a file declaring errand's own entries


NONE, FALLBACK, LANGUAGE, FRAMEWORK, ERRAND = Level.NONE, Level.FALLBACK, Level.LANGUAGE, \
                                              Level.FRAMEWORK, Level.ERRAND

# A file declares errand's own work when it IMPORTS errand, not when it merely
# says the word. A comment explaining that a suite is collected by errand, a
# docstring, a string in somebody's fixture -- all of those mention it, and none
# of them should be imported and executed on the strength of that.
MARKER = re.compile( r"^[ \t]*(from[ \t]+errand(\.[\w.]+)?[ \t]+import|import[ \t]+errand\b)",
                     re.MULTILINE )


def _read( path: Path, limit = 1 << 20 ) -> str:
    try:
        with open( path, errors = "ignore" ) as f:
            return f.read( limit )
    except OSError:
        return ""


@dataclass
class Outcome:
    status : str                                  # PASS | FAIL | SKIP
    error  : str | None = None
    results: dict = field( default_factory = dict )
    output : str = ""


@dataclass
class RunContext:
    root    : Path
    out_dir : Path
    params  : dict = field( default_factory = dict )
    env     : dict = field( default_factory = dict )
    # The `::name` part of the target that selected this entry, unconsumed: a
    # runner whose entries are whole files hands it to the file as a filter.
    selector: str | None = None
    # This environment's own build directory ( `build/<env>/` ): `{build_dir}`
    # in a runner's build command and binary path, `ERRAND_BUILD_DIR` for them.
    build_dir: Path | None = None
    # What was written after the target: its own arguments, the declared
    # parameters among them as they were resolved for this run.
    args    : list = field( default_factory = list )
    # What a plain command runs under: a memory ceiling, a lower priority.
    wrap    : list = field( default_factory = list )


class Runner:
    """The parts every runner shares. Subclasses fill in `suitability`,
    `collect` and `run`."""

    name = "runner"

    # The highest level `suitability` can answer.
    level = NONE

    # An entry runner answers `x::y`; a file runner ( `python`, `executable` )
    # answers a bare `x`, and is never asked to claim anything.
    takes_entries = True

    # True when an entry IS a whole file -- a script, or a compiled suite whose
    # cases cannot be enumerated before it is built. A `::name` then belongs to
    # the file, not to the entry: the core must not filter entries by it.
    whole_files = False
    # ...and the runner hands it on as the file's own filter ( Catch2 takes a
    # case name, `cargo test` a test name ). Without it, `file::x` is refused.
    takes_selector = False

    # The project root, set when the project's configuration has been read:
    # what a runner's own relative paths ( `dirs`, `manifest` ) are relative to.
    root = None

    # True when what a file holds can only be listed once it is built: then
    # `prepare` runs BEFORE `collect`, during the preparation, in the place --
    # and `collect` finds the build where `context.build_dir` says.
    builds_to_collect = False
    # What the preparation is being done with: the root, this environment's
    # build directory. Set by discovery before `prepare` and `collect`.
    context = None

    def suitability( self, path: Path ) -> Level:
        return NONE

    def collect( self, specs ) -> list:
        return [ ]

    def prepare( self, entries, ctx: RunContext ):
        """Once, before any of `entries` runs. -> None, or why it cannot.

        Building belongs here and not in `run`: a suite is built once, not once
        per file, and `-j` would otherwise have several processes writing the
        same binary at the same time.
        """
        return None

    def run( self, entry, ctx: RunContext ) -> Outcome:
        raise NotImplementedError

    def __repr__( self ):
        return f"<{type( self ).__name__} runner>"

    # -- helpers ------------------------------------------------------------

    def _under_root( self, rel ) -> Path:
        rel = Path( rel )
        return rel if rel.is_absolute() else Path( self.root or "." ) / rel

    def _inside( self, path: Path, dirs ) -> bool:
        """Whether `path` is under one of `dirs` -- every path, when there are none."""
        if dirs is None:
            return True
        real = os.path.realpath( path )
        return any( ( real + os.sep ).startswith( os.path.realpath( self._under_root( d ) ) + os.sep )
                    for d in dirs )

    def files_of( self, specs ):
        return list( dict.fromkeys( f for matched, _ in specs for f in matched ) )

    def entry( self, *, name, file, key = None, tags = ( ), traits = None, line = 0,
               params = None ):
        """One entry of this runner's.

        `params` are ordinary errand parameters, so a suite that can be asked
        to run two ways -- a device, a precision -- is a MATRIX like any other:
        `--device cpu,cuda` is two runs, two directories, two rows.
        """
        made = Entry( name, list( tags ), dict( params or { } ),
                      dict( TRAITS, **( traits or { } ) ), { },
                      file, line, f"{self.name}:{file}" )
        made.runner = self
        made.key = key if key is not None else name
        return made

    def shell( self, argv, ctx: RunContext, *, cwd = None, timeout = None ):
        """Run something and bring back its output, whatever it did."""
        extra = { "ERRAND_BUILD_DIR": str( ctx.build_dir ) } if ctx.build_dir else { }
        return subprocess.run( [ str( a ) for a in argv ], cwd = str( cwd or ctx.root ),
                               env = { **os.environ, **extra, **ctx.env }, capture_output = True,
                               text = True, timeout = timeout )

    def matching( self, specs, path: Path, names ):
        """The names of `path` that the specs asked for."""
        out = [ ]
        for matched, name_glob in specs:
            if path not in matched:
                continue
            if name_glob is None:
                return list( names )
            out += [ n for n in names if name_matches( name_glob, n ) ]
        return out


def selector_of( specs, path: Path ) -> str | None:
    """The `::name` that selected `path`, for a runner that runs whole files --
    none for `::*`, which asks for everything and filters nothing."""
    for matched, name_glob in specs:
        if path in matched and name_glob and name_glob != "*":
            return name_glob
    return None
