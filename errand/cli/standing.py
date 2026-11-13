"""What stays between commands, and what is still running: `errand agents`, and the head of `errand status`.

    errand agents                 the hub, and every agent it keeps a stream to
    errand agents stop [NAME]     those whose name holds NAME go now ( all of them, and the hub, without )

An agent with something running is left alone, unless `--force`. An allocation held warm goes
with its agent: the job ends.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import agents, bootstrap, config
from ..agents import upstream as U
from .style import bad, dim, good, head, warn


def _ago( seconds: float ) -> str:
    s = int( max( 0, seconds ) )
    return f"{s} s" if s < 90 else f"{s // 60} min" if s < 5400 else f"{s // 3600} h {s % 3600 // 60:02d}"


def hubs( ) -> list:
    """The directories of the hubs here, the current one first."""
    base = Path.home() / bootstrap.BASE
    current = U.hub_dir()
    others = sorted( d for d in base.glob( "hub-*" ) if d.is_dir() and d != current )
    return [ current, *others ]


def show( ) -> int:
    seen = 0
    for root in hubs():
        got = agents.ask_hub( root, { "op": "streams" } )
        if got is None:
            continue
        seen += 1
        older = "" if root == U.hub_dir() else "   ( older sources )"
        print( head( f"\n  hub  pid {got[ 'pid' ]}  up {_ago( got[ 'up' ] )}" ) + dim( f"   {root}{older}" ) )
        streams = got.get( "streams" ) or [ ]
        if not streams:
            print( dim( "    no agent reached yet" ) )
        width = max( [ len( s[ "id" ] ) for s in streams ] + [ 8 ] )
        for s in sorted( streams, key = lambda s: s[ "id" ] ):
            # An open call is not always work: an environment agent's stream goes through its host's.
            opened = f", {s[ 'calls' ]} open" if s[ "calls" ] else ""
            busy = dim( f"last used {_ago( s[ 'idle' ] )} ago{opened}; kept {_ago( s[ 'keep' ] )} unused" )
            lost = "" if s[ "alive" ] else warn( "  ( stream lost )" )
            print( f"    {s[ 'id' ]:<{width}}  " + busy + lost )
    if not seen:
        print( dim( "  no hub running: nothing kept between commands" ) )
    return 0


def stop( match: str | None, force = False ) -> int:
    seen = 0
    for root in hubs():
        got = agents.ask_hub( root, { "op": "stop", "match": match, "force": force }, timeout = 120 )
        if got is None:
            continue
        seen += 1
        for s in got.get( "stopped" ) or [ ]:
            line = f"  {s[ 'id' ]}: {s[ 'how' ]}"
            print( warn( line + "  ( --force stops it )" ) if s[ "how" ].startswith( "left" ) else dim( line ) )
        if got.get( "hub" ):
            print( dim( f"  hub {root.name}: stopped" ) )
    if not seen:
        print( dim( "  no hub running: nothing to stop" ) )
    return 0


def main( words: list, force = False ) -> int:
    if not words:
        return show()
    if words[ 0 ] == "stop" and len( words ) <= 2:
        return stop( words[ 1 ] if len( words ) == 2 else None, force )
    print( bad( f"errand agents: unknown action {' '.join( words )!r} ( `errand agents`, `errand agents stop [NAME]` )" ) )
    return 2


# ── left running ─────────────────────────────────────────────────────────────

def show_live( root: Path, ask = True ) -> int:
    """The commands whose connection was lost while their work went on: what `errand attach` follows.
    With `ask`, the agent says whether it is still running -- through the hub, when one is up."""
    lives = sorted( ( config.state( root ) / "live" ).glob( "*.json" ) )
    if not lives:
        return 0
    print( head( "\nleft running" ) + dim( "   ( errand attach [ID] follows it again and brings it back )" ) )
    for path in lives:
        try:
            rec = json.loads( path.read_text() )
        except ( OSError, ValueError ):
            continue
        where = rec[ "ssh" ][ "host" ] if rec.get( "ssh" ) else "this machine"
        state = dim( "?" )
        if ask:
            state = _state( rec )
        print( f"  {rec[ 'id' ]}  {rec[ 'env' ]} on {where}  " + state )
    return len( lives )


def processes( rec ) -> list:
    """What the agent says of the sessions a live record names: one dict each, None for one whose
    output is gone over there. Raises when the agent cannot be asked."""
    conn = agents.open( rec[ "target" ] )
    call = conn.open( { "op": "list", "store": rec.get( "store" ), "ids": [ str( p ) for p in rec[ "procs" ] ] } )
    try:
        procs = { str( p[ "id" ] ): p for p in call.reply( 20 ).get( "procs", [ ] ) }
    finally:
        call.close()
    return [ procs.get( str( pid ) ) for pid in rec[ "procs" ] ]


def _state( rec ) -> str:
    try:
        mine = processes( rec )
    except Exception as err:
        return warn( f"cannot say: {err}" )
    if any( p is None for p in mine ):
        return warn( "its output is gone over there" ) + dim( ": attach brings back what it wrote" )
    running = sum( 1 for p in mine if p[ "code" ] is None )
    if running:
        return good( f"running ( {running}/{len( mine )} )" )
    failed = sum( 1 for p in mine if p[ "code" ] )
    return ( bad( "finished, with failures" ) if failed else good( "finished" ) ) + dim( ": attach to bring it back" )
