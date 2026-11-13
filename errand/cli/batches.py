"""`--batch`: launching and letting go; `status` and `watch`: looking back.
"""
from __future__ import annotations

import time

from .. import batch, layers as L, results as R
from .style import bad, BOLD, dim, good, head, RESET, warn
from .project import child_env_for
from .plans import plan_path


def submit( targets, rest, argv, *, root, known, kinds ):
    """Launch each environment's share and come straight back.

    An environment with layers is prepared first, here ( `cli/drive.submit` ), so the run
    is sized from what was found; then the run is submitted and let go of. One with none
    is this errand, detached."""
    from . import drive
    from .here import Report
    from .. import setup

    ident = batch.new_id( root )
    stripped = [ a for a in argv if a != "--batch" ]

    places = [ ]
    for env, tags in targets:
        log = batch.batch_dir( root ) / f"{ident}-{R.slug( env.name )}.log"
        if env.wraps_anything( tags ) and drive.eligible( env, tags ):
            if not known.no_setup and setup.ensure( root, env, L.Context( root = root, tags = tags ),
                                                    echo = lambda s: print( dim( s ), flush = True ) ):
                got = { "kind": "failed", "handle": "", "error": f"could not prepare {env.name}" }
            else:
                print( dim( f"\n  -> {env.name}  {env.describe()}" ), flush = True )
                got = drive.submit( env, tags, known, root = root, kinds = kinds, report = Report(), log = log )
        else:
            got = batch.detach( env, tags, [ "run", *rest ], root = root, log = log,
                                child_env = child_env_for( env, tags ) )
        got[ "env" ] = env.name
        got[ "plan" ] = str( plan_path( root, env.name ).relative_to( root ) )
        places.append( got )

    record = { "id": ident, "when": batch.now(), "command": " ".join( stripped ),
               "stamp": R.stamp(), "places": places }
    batch.save( root, record )

    failed = [ p for p in places if p[ "kind" ] == "failed" ]
    shown = ", ".join( f"{p[ 'env' ]} on {p.get( 'host' ) or 'this machine'} ({p[ 'kind' ]} {p[ 'handle' ]})"
                       for p in places if p not in failed )
    print( f"  submitted {BOLD}{ident}{RESET}" + ( f" - {shown}" if shown else "" ) )
    for p in failed:
        print( bad( f"  {p[ 'env' ]}: could not start - {p.get( 'error', '' )}" ) )
    print( dim( f"  errand status    errand watch" ) )
    return 1 if failed else 0


def _without_value( argv, flag ):
    out, skip_next = [ ], False
    for a in argv:
        if skip_next:
            skip_next = False
            continue
        if a == flag:
            skip_next = True
            continue
        if a.startswith( flag + "=" ):
            continue
        out.append( a )
    return out


MARKS = { batch.DONE: "ok", batch.RUNNING: "..", batch.LOST: "??" }


RECENT = 86400.0       # a launch settled longer ago than this is only counted, not shown


def settle( root, record, rows ) -> bool:
    """Finished, everywhere it ran, and brought back: then it is `settled`, said so in its record,
    and nobody is asked about it again."""
    if record.get( "settled" ):
        return True
    if not rows or not batch.finished( rows ) or any( batch.alive( p ) for p in record.get( "places", [ ] ) ):
        return False
    record[ "settled" ] = True
    batch.save( root, record )
    return True


def _age( record ) -> float:
    import datetime
    try:
        return time.time() - datetime.datetime.fromisoformat( str( record.get( "when" ) ) ).timestamp()
    except ValueError:
        return 0.0


def show_batches( root, live = False, quiet_if_none = False ):
    records = batch.load_all( root )
    if not records:
        if not quiet_if_none:
            print( dim( "  nothing launched from here" ) )
        return 0
    try:
        while True:
            for record in records:
                if not record.get( "settled" ):
                    batch.collect( root, record )
            if live:
                print( "\033[2J\033[H", end = "" )
            everything, older = [ ], 0
            for record in records:
                rows = batch.states( root, record )
                everything += rows
                if settle( root, record, rows ) and _age( record ) > RECENT:
                    older += 1
                    continue
                _show_one( root, record, rows )
            if older:
                print( dim( f"\n  and {older} older launch{'es' if older > 1 else ''}, finished"
                            f"   ( errand forget finished drops them; their results stay )" ) )
            if not live or batch.finished( everything ):
                return 0
            time.sleep( 2.0 )
    except KeyboardInterrupt:
        return 0


def forget_finished( root ) -> int:
    """`errand forget finished`: every launch that is over, gone from the list. Results stay."""
    dropped = 0
    for record in batch.load_all( root ):
        if not record.get( "settled" ):
            batch.collect( root, record )
        if settle( root, record, batch.states( root, record ) ):
            batch.forget( root, record[ "id" ] )
            dropped += 1
    print( dim( f"  {dropped} finished launch{'es' if dropped != 1 else ''} forgotten; their results stay" ) )
    return 0


def _show_one( root, record, rows ):
    done = sum( 1 for r in rows if r[ "state" ] == batch.DONE )
    bar = "#" * ( 8 * done // max( 1, len( rows ) ) )
    print( head( f"\n{record[ 'id' ]}  {record[ 'command' ] or '(everything)'}" )
           + dim( f"   {record[ 'when' ]}   {done}/{len( rows )} [{bar:<8}]" ) )
    for place in record.get( "places", [ ] ):
        state = False if record.get( "settled" ) else batch.alive( place )
        how = "running" if state else ( "finished" if state is False else "unknown" )
        job = f"{place[ 'kind' ]} {place.get( 'handle' ) or '-'}"
        print( dim( f"    {place[ 'env' ]}: {job} on {place.get( 'host' ) or 'this machine'} - {how}" ) )

    # Parameters down, places across: that is the shape a matrix actually has,
    # and a flat list of eight lines hides the one axis that was varied.
    places = sorted( { r[ "place" ] for r in rows } )
    keys = sorted( { _key( r ) for r in rows } )
    width = max( [ len( k ) for k in keys ] + [ 8 ] )
    print( "      " + f"{'':<{width}}  " + "  ".join( f"{p[ :22 ]:<22}" for p in places ) )
    for key in keys:
        cells = [ ]
        for place in places:
            row = next( ( r for r in rows if _key( r ) == key and r[ "place" ] == place ), None )
            cells.append( f"{_cell( row ):<22}" )
        print( "      " + f"{key:<{width}}  " + "  ".join( cells ) )


def _key( row ):
    params = ", ".join( f"{k}={v}" for k, v in ( row.get( "params" ) or { } ).items() )
    return f"{row[ 'label' ]}" + ( f"  {params}" if params else "" )


def _cell( row ):
    if row is None:
        return "-"
    if row[ "state" ] != batch.DONE:
        return { batch.RUNNING: "...", batch.PREPARING: "preparing" }.get( row[ "state" ], "lost" )
    mark = good( "ok" ) if row.get( "status" ) == "PASS" else (
        warn( "skip" ) if row.get( "status" ) == "SKIP" else bad( "FAIL" ) )
    numbers = [ f"{k}={v:g}" for k, v in ( row.get( "results" ) or { } ).items()
                if isinstance( v, ( int, float ) ) and not isinstance( v, bool ) ]
    seconds = row.get( "seconds" )
    detail = numbers[ 0 ] if numbers else ( f"{seconds:g}s" if seconds else "" )
    return f"{mark} {detail}".strip()
