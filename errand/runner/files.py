"""The file runners: a `.py` run by the interpreter of the place, anything else run as it is.
No entries inside: the whole file, or command, is the one thing that runs.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .base import Outcome, RunContext, Runner


#
# A bare target -- no `::` -- is one run of one thing: a script, an executable, a
# command. Its output is the run's, streamed as it comes, and its exit code the
# status. `ERRAND_OUT_DIR` is set only when an output directory was asked for
# ( `-o` ): nobody is handed a directory they did not want.

INTERPRETERS = ( "python", "python3" )

# What a run of a plain command may write numbers to, and what it gets as
# `ERRAND_OUT_DIR` when one was asked for: set by the core in `RunContext.env`.
OUT_DIR = "ERRAND_OUT_DIR"


class _WholeFile( Runner ):
    whole_files   = True
    takes_entries = False

    def command( self, key: str ) -> list:
        raise NotImplementedError

    def collect( self, specs ):
        return [ self.entry( name = Path( key ).name, file = Path( key ), key = str( key ) )
                 for key in self.files_of( specs ) ]

    def run( self, entry, ctx: RunContext ) -> Outcome:
        argv = [ *ctx.wrap, *( str( a ) for a in self.command( entry.key ) ), *ctx.args ]
        # A directory only when one was asked for, which `ctx.env` says.
        env = { **{ k: v for k, v in os.environ.items() if k != OUT_DIR },
                **( { "ERRAND_BUILD_DIR": str( ctx.build_dir ) } if ctx.build_dir else { } ),
                **ctx.env }
        try:
            child = subprocess.Popen( argv, cwd = str( ctx.root ), env = env, text = True,
                                      stdout = subprocess.PIPE, stderr = subprocess.STDOUT,
                                      errors = "replace" )
        except OSError as err:
            return Outcome( status = "FAIL", error = f"{argv[ 0 ]}: {err.strerror or err}" )
        # Line by line, as it comes: a build or a long computation that says
        # nothing until it is over is one nobody can follow -- here, in
        # `output.txt`, or on the screen.
        for line in child.stdout:
            sys.stdout.write( line )
            sys.stdout.flush()
        code = child.wait()
        if code == SKIP_CODE:
            return Outcome( status = "SKIP", error = "exit 77" )
        return Outcome( status = "PASS" if code == 0 else "FAIL",
                        error = None if code == 0 else f"exit {code}" )


# The exit code that means "this does not apply here", as automake and ctest have it.
SKIP_CODE = 77


class Python( _WholeFile ):
    """A `.py`, run by the interpreter of the place it runs in."""

    name = "python"

    def command( self, key ):
        return [ sys.executable, key ]


class Executable( _WholeFile ):
    """Anything else, run as it is: a file of the project ( `./bench`, a script
    with a shebang ), or a command of the place ( `make`, `cmake`, `pytest` ).
    A first word that names an interpreter is the interpreter of the place."""

    name = "executable"

    def command( self, key ):
        if key in INTERPRETERS:
            return [ sys.executable ]
        path = Path( key )
        if path.parent != Path( "." ) or self._under_root( path ).is_file():
            return [ str( self._under_root( path ).resolve() ) ]
        return [ key ]
