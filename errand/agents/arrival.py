"""Arrivals ( ADR 0009 ): what a process waits for, said to its owner.

A process waiting for something that is not owned yet where it will run -- a Slurm job in the
queue, room on a machine, a VM booting -- says so in its record, `$ERRAND_PROC_DIR/waiting`:

    { "what": "slurm job 81234 pending", "since": <epoch>, "job": "81234" }

`table` reads it, and `errand status` shows it. `waiting()` again when the state changes ( `since`
is kept while `key` is the same ); `arrived()` when the wait is over. A process that no agent
started ( no `ERRAND_PROC_DIR` ) has nobody to tell: both do nothing.

Shell scripts write the same file ( `SHELL_WAITING` ).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ENV  = "ERRAND_PROC_DIR"
NAME = "waiting"

# `waiting "<what>" [job]`, `arrived`: the same, for a shell script run by an agent. `since` is the
# time of the first `waiting` after the last `arrived`.
SHELL_WAITING = r'''
waiting() {
    [ -n "$ERRAND_PROC_DIR" ] || return 0
    [ -n "$errand_since" ] || errand_since=$( date +%s )
    printf '{"what": "%s", "since": %s, "job": "%s"}\n' "$1" "$errand_since" "$2" \
        > "$ERRAND_PROC_DIR/waiting.tmp" 2>/dev/null && mv "$ERRAND_PROC_DIR/waiting.tmp" "$ERRAND_PROC_DIR/waiting"
}
arrived() {
    errand_since=""
    [ -n "$ERRAND_PROC_DIR" ] && rm -f "$ERRAND_PROC_DIR/waiting"
    return 0
}
'''

_since = { }


def _path() -> Path | None:
    d = os.environ.get( ENV )
    return Path( d ) / NAME if d else None


def waiting( what: str, job = None, key = "" ):
    """Waiting for `what` ( said as a person reads it ). `key`: what the wait is, so that a change of
    state keeps its start ( "queued", then "booting", one wait )."""
    path = _path()
    if path is None:
        return
    since = _since.setdefault( key, time.time() )
    try:
        tmp = path.with_suffix( ".tmp" )
        tmp.write_text( json.dumps( { "what": what, "since": since, "job": job } ) )
        tmp.replace( path )
    except OSError:
        pass


def arrived( key = "" ):
    _since.pop( key, None )
    path = _path()
    if path is not None:
        try:
            path.unlink()
        except OSError:
            pass


def read( mark: Path ) -> dict | None:
    try:
        return json.loads( ( mark / NAME ).read_text() )
    except ( OSError, ValueError ):
        return None
