"""Colours on a terminal and nowhere else, and capturing what a run prints.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path


BOLD, DIM, GREEN, RED, YELLOW, CYAN, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[0m" )

if not sys.stdout.isatty() or os.environ.get( "NO_COLOR" ):
    BOLD = DIM = GREEN = RED = YELLOW = CYAN = RESET = ""


def dim( s ):   return f"{DIM}{s}{RESET}"
def head( s ):  return f"{BOLD}{CYAN}{s}{RESET}"
def bad( s ):   return f"{RED}{s}{RESET}"
def good( s ):  return f"{GREEN}{s}{RESET}"
def warn( s ):  return f"{YELLOW}{s}{RESET}"


class Tee:
    def __init__( self, *streams ):
        self._streams = streams

    def write( self, s ):
        for st in self._streams:
            st.write( s )
        return len( s )

    def flush( self ):
        for st in self._streams:
            st.flush()

    def isatty( self ):
        return False


@contextlib.contextmanager
def capture( path: Path | None = None, log = None ):
    """Mirror stdout/stderr into a buffer -- and into `path` -- while still
    printing live.

    The file is written AS IT GOES, not at the end: it is the only place a case
    running elsewhere, or beside seven others under `-j`, says anything at all.
    `tail -f` works on it, and so does the screen, which is the same thing.
    """
    buf = io.StringIO()
    handles = [ ]
    for where in ( path, log ):
        if where is not None:
            try:
                handles.append( open( where, "a" if where == log else "w", buffering = 1 ) )
            except OSError:
                pass                     # a run must not fail over its own log
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = Tee( old_out, buf, *handles ), Tee( old_err, buf, *handles )
    try:
        yield buf
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        for handle in handles:
            handle.close()
