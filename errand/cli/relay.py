"""The side that drives a run, answering what it asks up the chain ( ADR 0013 ).

A run over there that cannot reach a URL says what it wants ( `downloads.ask_up` ); its session says it
here as a mark ( `sessions.follow` ). Then, in order:

    1. the agent of the host over there downloads it into the copy ( `op: download` ): a cluster's login
       node often reaches what its compute nodes do not, and shares their disk;
    2. failing that, it is downloaded into the project here, and sent into the copy through that agent
       ( `syncop.send_files` ), with the answer the run waits for.
"""
from __future__ import annotations

from pathlib import Path

from .style import dim, warn

WAIT = 24 * 3600.0


def through( conn_of, local_root: Path, where: str, say = None ):
    """The relay of runs whose copy `conn_of()` ( the host agent's connection ) reaches."""
    say = say or ( lambda s: print( s, flush = True ) )
    return lambda want: serve( conn_of, Path( local_root ), want, where, say )


def serve( conn_of, local_root: Path, want: dict, where: str, say ):
    from .. import downloads as D
    from ..agents import syncop
    name, url = want[ "name" ], want[ "url" ]
    say( dim( f"  {name}: the run cannot reach {url} -- asking {where}" ) )
    try:
        call = conn_of().open( { "op": "download", "want": want } )
        try:
            got = call.reply( timeout = WAIT )
        finally:
            call.close()
    except Exception as err:
        got = { "failed": f"{type( err ).__name__}: {err}", "offline": True }
    if got.get( "sha256" ):
        say( dim( f"  {name}: downloaded on {where}" ) )
        return
    if not got.get( "offline" ):
        say( warn( f"  {name}: {got.get( 'failed' )}" ) )       # said to the run too, by the agent
        return
    keys, body = [ ], None
    try:
        p = D.download( url, want.get( "sha256" ), name, root = local_root, relay = False, wait = 0 )
        keys, body = [ f"{p.parent.name}/{name}" ], { "sha256": p.parent.name }
        say( dim( f"  {name}: downloaded here, sent to {where}" ) )
    except Exception as err:
        body = { "error": f"not from {where} ( {got.get( 'failed' )} ), nor from here ( {err} )" }
        say( warn( f"  {name}: {body[ 'error' ]}" ) )
    try:
        syncop.send_files( conn_of(), D.downloads_dir( local_root ), want[ "dir" ], keys,
                           answer = { "path": want[ "answer" ], "body": body } )
    except Exception as err:
        say( warn( f"  {name}: could not be sent to {where}: {err}" ) )
