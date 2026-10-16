"""What was run from here, so it can be run again.

One command per line, oldest first, in `.errand/history` ( errand's state, see `config.state` ). Plain text on
purpose: it is meant to be read, grepped and pasted into a shell, and the
whole point of the file is that what it holds is a COMMAND -- not a record of
some internal state that only errand could replay.

A repeat moves its line to the end rather than adding a second copy: a history
is a list of distinct things worth running again, not a log.
"""
from __future__ import annotations

import shlex
from pathlib import Path


LIMIT   = 300


def path( root: Path ) -> Path:
    from . import config
    return config.state( root ) / "history"


def load( root: Path ) -> list:
    try:
        return [ line for line in path( root ).read_text().splitlines() if line.strip() ]
    except OSError:
        return [ ]


def push( root: Path, argv ) -> None:
    """Record `argv` as the command it was. Never fatal: a history that cannot
    be written is worth less than the run it would have described."""
    line = " ".join( shlex.quote( str( a ) ) for a in argv ).strip()
    lines = [ l for l in load( root ) if l != line ] + [ line ]
    try:
        p = path( root )
        p.parent.mkdir( parents = True, exist_ok = True )
        p.write_text( "\n".join( lines[ -LIMIT : ] ) + "\n" )
    except OSError:
        pass
