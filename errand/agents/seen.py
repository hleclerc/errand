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
        from . import look
        look.ring()                                  # its agents' watchers see it now ( ADR 0024 )
    except OSError:
        pass


# What this process read already ( an agent asks every few seconds, `look.Watch` ): a link by its name and date, a
# `result.yaml` by its leaf and date, the listing by the directory's date. A machine keeps tens of thousands of links
# ( a test suite run often ): read again, they cost a second each time; remembered, a few `stat`.
_links: dict = { }                 # path -> ( mtime_ns, record )
_results: dict = { }               # leaf -> ( mtime_ns, result )
_listing = [ None, [ ] ]           # [ ( the directory, its mtime_ns ), the names ]
_swept = [ 0.0 ]                   # when every leaf was last checked ( `SWEEP` )
SWEEP = 600.0


def _records( d: Path ) -> list:
    try:
        mtime = d.stat().st_mtime_ns
    except OSError:
        return [ ]
    if ( str( d ), mtime ) != _listing[ 0 ]:
        _listing[ 0 ], _listing[ 1 ] = ( str( d ), mtime ), [ str( d / n ) for n in os.listdir( d ) if n.endswith( ".json" ) ]
    names = set( _listing[ 1 ] )
    for gone in [ n for n in _links if n not in names ]:
        del _links[ gone ]
    out = [ ]
    for n in _listing[ 1 ]:
        p = Path( n )
        got = _links.get( n )
        if got is None:                                    # a link is written once ( `note` ): read once
            try:
                got = _links[ n ] = ( 0, json.loads( p.read_text() ) )
            except ( OSError, ValueError ):
                continue
        out.append( ( p, got[ 1 ] ) )
    return out


def _result( leaf: str ) -> dict:
    """what its `result.yaml` says, else what its `launch.yaml` does ( it runs: what it is, not yet how it went )"""
    from .. import yamlish
    for name in ( "result.yaml", "launch.yaml" ):
        path = Path( leaf ) / name
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            continue
        got = _results.get( leaf )
        if got is None or got[ 0 ] != ( name, mtime ):
            try:
                got = _results[ leaf ] = ( ( name, mtime ), yamlish.read( path ) or { } )
            except Exception:
                return { }
        return got[ 1 ]
    _results.pop( leaf, None )
    return { }


def runs( limit = 50 ) -> dict:
    """The runs whose leaf is still there, newest first: { "runs": [ … ], "more": how many left out }.
    Each with what its `result.yaml` says, once there is one. The leaves of the runs said are checked each time; all
    of them every `SWEEP` seconds ( a link whose leaf is gone goes )."""
    d = _dir()
    if not d.is_dir():
        return { "runs": [ ], "more": 0 }
    records = _records( d )
    if time.time() - _swept[ 0 ] >= SWEEP:
        _swept[ 0 ] = time.time()
        kept = [ ]
        for p, rec in records:
            if Path( rec.get( "leaf", "" ) ).is_dir():
                kept.append( ( p, rec ) )
            else:
                p.unlink( missing_ok = True )
        records = kept
    records.sort( key = lambda pr: -pr[ 1 ].get( "started", 0 ) )
    found, at = [ ], 0
    while len( found ) < limit and at < len( records ):
        p, rec = records[ at ]
        at += 1
        if not Path( rec.get( "leaf", "" ) ).is_dir():
            p.unlink( missing_ok = True )
            continue
        result = _result( rec[ "leaf" ] )
        found.append( { **rec, "status": result.get( "status" ), "duration": result.get( "duration_s" ),
                        **( { "file": result[ "file" ] } if result.get( "file" ) else { } ),
                        # what the runs tab puts in a table ( ADR 0023 ): the entry's name, its parameters, its results
                        **{ k: result[ k ] for k in ( "name", "params", "results" ) if isinstance( result.get( k ), ( str, dict ) ) } } )
    return { "runs": found, "more": max( 0, len( records ) - at ) }
