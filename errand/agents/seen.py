"""What ran on this machine: one link per run, to the run's own directory ( its leaf ).

    ~/.cache/errand/seen/<id>.json      { "leaf", "project", "what", "env", "started" }

Written by `run_case` where the run happens, whoever asked for it. Nothing else is kept: status,
duration and output are read in the leaf ( `result.yaml`, `output.txt` ) when someone looks. A link
whose leaf is gone is dropped when read, so this directory is as big as the runs one keeps.

The leaf of the case running now is also said to the process's owner, `$ERRAND_PROC_DIR/leaf`
( as `waiting`, ADR 0009 ): `table` reports it, so its files can be read before the run ends.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .. import bootstrap

SEEN = "seen"


def _dir() -> Path:
    return bootstrap.local_cache() / SEEN


def ident( leaf ) -> str:
    """A run's short name, from its directory over there: its link's name here, and in the page's address ( `/r/<id>` )."""
    return hashlib.sha1( str( leaf ).encode() ).hexdigest()[ : 16 ]


def note( leaf: Path, project: Path, what: str, env: str | None ):
    """A run starts in `leaf`. Never fatal: a link that cannot be written costs only the link."""
    leaf = Path( leaf ).resolve()
    mark = os.environ.get( "ERRAND_PROC_DIR" )
    try:
        if mark:
            ( Path( mark ) / "leaf" ).write_text( str( leaf ) )
        d = _dir()
        d.mkdir( parents = True, exist_ok = True )
        path = d / f"{ident( leaf )}.json"
        tmp = path.with_suffix( ".tmp" )
        tmp.write_text( json.dumps( { "leaf": str( leaf ), "project": str( project ), "what": what,
                                      "env": env, "started": time.time() } ) )
        tmp.replace( path )
    except OSError:
        pass


def runs( limit = 50 ) -> dict:
    """The runs whose leaf is still there, newest first: { "runs": [ … ], "more": how many left out }.
    Each with what its `result.yaml` says, once there is one."""
    from .. import yamlish
    found = [ ]
    for p in _dir().glob( "*.json" ) if _dir().is_dir() else [ ]:
        try:
            rec = json.loads( p.read_text() )
        except ( OSError, ValueError ):
            continue
        if not Path( rec.get( "leaf", "" ) ).is_dir():
            p.unlink( missing_ok = True )
            continue
        found.append( rec )
    found.sort( key = lambda r: -r.get( "started", 0 ) )
    for rec in found[ : limit ]:
        try:
            result = yamlish.read( Path( rec[ "leaf" ] ) / "result.yaml" ) or { }
        except Exception:
            result = { }
        rec.update( status = result.get( "status" ), duration = result.get( "duration_s" ),
                    **( { "file": result[ "file" ] } if result.get( "file" ) else { } ) )
    return { "runs": found[ : limit ], "more": max( 0, len( found ) - limit ) }
