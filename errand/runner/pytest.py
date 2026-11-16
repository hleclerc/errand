"""A pytest suite, run by pytest itself: one invocation per file, the `::name` handed to it, its junit
report read back.
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
from pathlib import Path

from .base import FRAMEWORK, NONE, Outcome, RunContext, Runner, junit_outcome


# What makes a `::name` a pattern rather than a node id: then pytest is asked what the file holds.
GLOB = set( "*?[" )


class Pytest( Runner ):
    """An existing pytest suite: a file is one run, one pytest.

    Which files are pytest's is pytest's convention -- `test_*.py` and
    `*_test.py`, under `dirs` when they are given. What is in them is pytest's
    business: `x.py::test_y` is handed to it as the node id it is, and a
    pattern ( `x.py::test_a*` ) is matched against what pytest itself collects.
    Marks are pytest's too: `-m "not slow"` after the target.
    """

    name = "pytest"
    level = FRAMEWORK
    whole_files = True
    takes_selector = True
    jobs = True                          # `-j N` on one file: pytest-xdist's `-n N`

    def __init__( self, dirs = None, patterns = ( "test_*.py", "*_test.py" ), args = ( ),
                  python = None, install = "auto", spec = "pytest", zones = None ):
        self.dirs     = None if dirs is None else list( dirs )
        self.patterns = list( patterns )
        self.args     = list( args )
        self.python   = python           # None: `{python}` of the place
        self.install  = install          # "auto" | True | False
        self.spec     = spec
        self.zones    = dict( zones or { } )

    def suitability( self, path ):
        if path.suffix != ".py" or not any( fnmatch.fnmatchcase( path.name, p ) for p in self.patterns ):
            return NONE
        return FRAMEWORK if self._inside( path, self.dirs ) else NONE

    def py( self, ctx = None ) -> list:
        return [ self.python ] if self.python else self.tool( "python", ctx )

    # -- having a pytest at all ---------------------------------------------

    def _has( self, module, ctx = None ):
        return subprocess.run( [ *self.py( ctx ), "-c", f"import {module}" ],
                               capture_output = True ).returncode == 0

    def _has_pytest( self, ctx = None ):
        return self._has( "pytest", ctx )

    def _own_environment( self, ctx = None ):
        """Is the target interpreter something other than the system's?

        Installing into a micromamba environment, a venv or a container is what
        errand does for every other requirement. Installing into the system
        python is not errand's to do -- it is shared with everything else on
        the machine, and it may well refuse.
        """
        got = subprocess.run(
            [ *self.py( ctx ), "-c", "import sys; print( sys.prefix != sys.base_prefix )" ],
            capture_output = True, text = True )
        if got.stdout.strip() == "True":
            return True
        return bool( os.environ.get( "CONDA_PREFIX" ) or os.environ.get( "VIRTUAL_ENV" ) )

    def ensure( self, module, spec, echo = "say", ctx = None ):
        """-> None when `module` imports in the place's Python, else why it does not: installed first when
        the environment is errand's to install into ( `install` )."""
        if self._has( module, ctx ):
            return None
        python = " ".join( self.py( ctx ) )
        wanted = self.install is True or ( self.install == "auto" and self._own_environment( ctx ) )
        if not wanted:
            return ( f"{python} has no {spec}, and it is the system interpreter: "
                     f"installing into it is not errand's to do.\n"
                     f"  install it yourself, point the runner at another interpreter "
                     f"( Pytest( python = ... ), or the environment's tools = {{ \"python\": ... }} ), "
                     f"or say Pytest( install = True )" )
        # Never silent: installing something into somebody's environment is
        # an act, and it is said out loud even when nobody asked to watch.
        note = f"  installing {spec} into {python}"
        print( note, file = sys.stderr ) if echo == "say" else ( echo and echo( note ) )
        got = subprocess.run( [ *self.py( ctx ), "-m", "pip", "install", spec ],
                              capture_output = True, text = True )
        if got.returncode or not self._has( module, ctx ):
            return f"could not install {spec}:\n{( got.stdout + got.stderr )[ -2000 : ]}"
        return None

    def ensure_pytest( self, echo = "say", ctx = None ):
        return self.ensure( "pytest", self.spec, echo, ctx )

    def prepare( self, entries, ctx: RunContext ):
        return self.ensure_pytest( ctx = ctx )

    # -- running ------------------------------------------------------------

    def node_ids( self, path: str, selector, ctx: RunContext ):
        """-> ( [ what to hand pytest ], None ), or ( None, why ): a node id as it was written, the
        tests a pattern matches as pytest itself collects them."""
        if not selector:
            return [ path ], None
        if not GLOB & set( selector ):
            return [ f"{path}::{selector}" ], None
        got = self.shell( [ *self.py( ctx ), "-m", "pytest", "--collect-only", "-q", *self.args, path ], ctx )
        ids = [ line.strip() for line in got.stdout.splitlines() if "::" in line ]
        # Matched on what follows the file ( `TestA::test_x[3]` ), and on the test's own name.
        # What follows the file, as pytest names it: pytest names the file from its own rootdir,
        # which need not be where it is run from, so the file is put back as it was given.
        names = [ i.split( "::", 1 )[ 1 ] for i in ids ]
        wanted = [ f"{path}::{n}" for n in names
                   if fnmatch.fnmatchcase( n, selector ) or fnmatch.fnmatchcase( n.rsplit( "::", 1 )[ -1 ], selector ) ]
        if wanted:
            return wanted, None
        return None, ( f"'{path}::{selector}' matches no test" +
                       ( f" -- there: {'  '.join( names[ : 8 ] )}" if names else
                         f"\n{( got.stdout + got.stderr )[ -1500 : ]}" ) )

    def run( self, entry, ctx: RunContext ) -> Outcome:
        ids, why = self.node_ids( str( entry.key ), ctx.selector, ctx )
        if why:
            return Outcome( status = "FAIL", error = why )
        report = ctx.out_dir / "pytest.xml"
        workers = [ ]
        if ctx.jobs > 1:
            # One file, several workers: pytest-xdist, installed by the same rule as pytest.
            why = self.ensure( "xdist", "pytest-xdist", ctx = ctx )
            if why:
                print( f"  -j {ctx.jobs}: no pytest-xdist, the file runs on one worker -- {why.splitlines()[ 0 ]}",
                       file = sys.stderr )
            else:
                workers = [ "-n", str( ctx.jobs ) ]
        got = self.shell( [ *self.py( ctx ), "-m", "pytest", "-q", f"--junitxml={report}",
                            *workers, *self.args, *ids, *ctx.args ], ctx )
        text = got.stdout + got.stderr
        outcome = junit_outcome( report )
        if got.returncode == 5:
            # Nothing collected: an empty run looks exactly like a passing one.
            return Outcome( status = "FAIL", error = "pytest collected no test", output = text )
        if outcome is None:
            return Outcome( status = "PASS" if got.returncode == 0 else "FAIL",
                            error = None if got.returncode == 0 else f"exit {got.returncode}",
                            output = text )
        outcome.output = text
        return outcome
