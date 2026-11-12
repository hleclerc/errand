"""A pytest suite, run by pytest itself: its collection, its marks as entry tags, its junit report
read back.
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .base import FRAMEWORK, NONE, Outcome, RunContext, Runner


COLLECT_TO = "ERRAND_COLLECT_TO"


class Pytest( Runner ):
    """An existing pytest suite, one entry per test.

    Which files are pytest's is pytest's convention -- `test_*.py` and
    `*_test.py`, under `dirs` when they are given -- and what is in them is
    asked of pytest itself rather than guessed: its rules are its own, and
    reimplementing them is how a runner starts quietly disagreeing with the
    tool it wraps. Nothing is built, so collecting is cheap.
    """

    name = "pytest"
    level = FRAMEWORK

    def __init__( self, dirs = None, patterns = ( "test_*.py", "*_test.py" ), args = ( ),
                  python = None, install = "auto", spec = "pytest" ):
        self.dirs     = None if dirs is None else list( dirs )
        self.patterns = list( patterns )
        self.args     = list( args )
        self.python   = python or sys.executable
        self.install  = install          # "auto" | True | False
        self.spec     = spec
        self._items   = { }

    def suitability( self, path ):
        if path.suffix != ".py" or not any( fnmatch.fnmatchcase( path.name, p ) for p in self.patterns ):
            return NONE
        return FRAMEWORK if self._inside( path, self.dirs ) else NONE

    # -- having a pytest at all ---------------------------------------------

    def _has_pytest( self ):
        return subprocess.run( [ self.python, "-c", "import pytest" ],
                               capture_output = True ).returncode == 0

    def _own_environment( self ):
        """Is the target interpreter something other than the system's?

        Installing into a micromamba environment, a venv or a container is what
        errand does for every other requirement. Installing into the system
        python is not errand's to do -- it is shared with everything else on
        the machine, and it may well refuse.
        """
        got = subprocess.run(
            [ self.python, "-c", "import sys; print( sys.prefix != sys.base_prefix )" ],
            capture_output = True, text = True )
        if got.stdout.strip() == "True":
            return True
        return bool( os.environ.get( "CONDA_PREFIX" ) or os.environ.get( "VIRTUAL_ENV" ) )

    def ensure_pytest( self, echo = "say" ):
        """-> None when there is a pytest to ask, else why there is not."""
        if self._has_pytest():
            return None
        wanted = self.install is True or ( self.install == "auto" and self._own_environment() )
        if not wanted:
            return ( f"{self.python} has no pytest, and it is the system interpreter: "
                     f"installing into it is not errand's to do.\n"
                     f"  install it yourself, point the runner at another interpreter "
                     f"( Pytest( python = ... ) ), or say Pytest( install = True )" )
        # Never silent: installing something into somebody's environment is
        # an act, and it is said out loud even when nobody asked to watch.
        note = f"  installing {self.spec} into {self.python}"
        print( note, file = sys.stderr ) if echo == "say" else ( echo and echo( note ) )
        got = subprocess.run( [ self.python, "-m", "pip", "install", self.spec ],
                              capture_output = True, text = True )
        if got.returncode or not self._has_pytest():
            return f"could not install {self.spec}:\n{( got.stdout + got.stderr )[ -2000 : ]}"
        return None

    def prepare( self, entries, ctx: RunContext ):
        return self.ensure_pytest( )

    # -- collecting ---------------------------------------------------------

    def items( self, files ):
        """[ { id, file, name, marks } ] of `files`, as pytest itself sees them."""
        key = tuple( sorted( str( f ) for f in files ) )
        if key in self._items:
            return self._items[ key ]
        self._items[ key ] = found = [ ]
        if not files:
            return found
        why = self.ensure_pytest( )
        if why is not None:
            # An empty suite looks exactly like a suite that passed, so the
            # reason is said out loud even though nobody asked for a status.
            print( f"  pytest: {why}", file = sys.stderr )
            return found
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path( tmp ) / "items.json"
            env = { **os.environ, COLLECT_TO: str( listing ),
                    "PYTHONPATH": os.pathsep.join(
                        [ str( Path( __file__ ).resolve().parent.parent.parent ),
                          *filter( None, [ os.environ.get( "PYTHONPATH" ) ] ) ] ) }
            got = subprocess.run(
                [ self.python, "-m", "pytest", "--collect-only", "-q",
                  "-p", "errand._pytest_plugin", *self.args, *key ],
                capture_output = True, text = True, env = env, timeout = 300,
                cwd = str( self.root or "." ) )
            if listing.exists():
                found += json.loads( listing.read_text() )
            elif got.returncode not in ( 0, 5 ):
                # No listing and a real failure: say so rather than report an
                # empty suite, which looks like success.
                found.append( { "id": "<collection failed>", "file": key[ 0 ],
                                "name": "<collection failed>", "marks": [ ],
                                "error": ( got.stdout + got.stderr )[ -2000 : ] } )
        return found

    def collect( self, specs ):
        by_file = { }
        for item in self.items( self.files_of( specs ) ):
            by_file.setdefault( Path( item[ "file" ] ).resolve(), [ ] ).append( item )

        out = [ ]
        for path, items in by_file.items():
            wanted = self.matching( specs, path, [ i[ "name" ] for i in items ] )
            for item in items:
                if item[ "name" ] in wanted:
                    out.append( self.entry( name = item[ "name" ], file = path,
                                            key = item[ "id" ], tags = item.get( "marks" ) or [ ] ) )
        return out

    # -- running ------------------------------------------------------------

    def run( self, entry, ctx: RunContext ) -> Outcome:
        report = ctx.out_dir / "pytest.xml"
        got = self.shell( [ self.python, "-m", "pytest", entry.key, "-q",
                            f"--junitxml={report}", *self.args, *ctx.args ], ctx )
        outcome = _from_junit( report )
        if outcome is None:
            return Outcome( status = "PASS" if got.returncode == 0 else "FAIL",
                            error = None if got.returncode == 0 else f"exit {got.returncode}",
                            output = got.stdout + got.stderr )
        outcome.output = got.stdout + got.stderr
        return outcome


def _from_junit( report: Path ):
    """pytest's own verdict, in its own words -- and the file stays behind."""
    if not report.exists():
        return None
    try:
        root = ET.parse( report ).getroot()
    except ET.ParseError:
        return None
    case = root.find( ".//testcase" )
    if case is None:
        return None
    results = { }
    if case.get( "time" ):
        results[ "seconds" ] = float( case.get( "time" ) )
    for kind, status in ( ( "failure", "FAIL" ), ( "error", "FAIL" ), ( "skipped", "SKIP" ) ):
        found = case.find( kind )
        if found is not None:
            return Outcome( status = status,
                            error = ( found.get( "message" ) or found.text or "" ).strip()[ : 500 ],
                            results = results )
    return Outcome( status = "PASS", results = results )
