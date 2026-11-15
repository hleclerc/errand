"""The ledger: the machines this one has sent work to, so `errand status` knows where to look ( ADR 0008 ).

    ~/.cache/errand/ledger/<id>.json      { "target", "name", "last" }

One entry per machine reached through its agent ( `agents.open` ), whatever the project: what runs
there is then asked of that machine itself ( `table` ), which knows it better than any record kept
here could -- work started from elsewhere, or by a command that was killed, included.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .. import bootstrap

LEDGER   = "ledger"
FORGET   = 14 * 86400.0       # a machine not reached for this long is not asked any more
REFRESH  = 60.0               # an entry is rewritten at most this often


def _dir() -> Path:
    return bootstrap.local_cache() / LEDGER


def note( target: dict ):
    """`target` was reached: a machine to ask. Only ssh hosts: the other agents ( environments,
    guests, allocations ) live on a host, and are found there."""
    if target.get( "kind" ) != "ssh":
        return
    from .upstream import identity, name
    key = identity( target )
    path = _dir() / f"{hashlib.sha1( key.encode() ).hexdigest()[ : 12 ]}.json"
    try:
        if time.time() - path.stat().st_mtime < REFRESH:
            return
    except OSError:
        pass
    try:
        path.parent.mkdir( parents = True, exist_ok = True )
        tmp = path.with_suffix( ".tmp" )
        tmp.write_text( json.dumps( { "target": target, "name": name( target ), "last": time.time() } ) )
        tmp.replace( path )
    except OSError:
        pass              # a ledger that cannot be written must not stop the work


def machines() -> list:
    """The machines reached lately, most recent first: [ { target, name, last } ]."""
    out = [ ]
    for p in _dir().glob( "*.json" ) if _dir().is_dir() else [ ]:
        try:
            rec = json.loads( p.read_text() )
        except ( OSError, ValueError ):
            continue
        if time.time() - rec.get( "last", 0 ) > FORGET:
            p.unlink( missing_ok = True )
            continue
        out.append( rec )
    return sorted( out, key = lambda r: -r.get( "last", 0 ) )
