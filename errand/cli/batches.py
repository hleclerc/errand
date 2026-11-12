"""`--batch`: launching and letting go; `status` and `watch`: looking back.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from .. import batch, layers as L, results as R
from .style import bad, BOLD, dim, good, head, RESET, warn
from .project import child_env_for
from .plans import plan_path, read_plan


def submit( targets, rest, argv, *, root, out_root ):
    """Launch each environment's share and come straight back.

    Where a run has to be sized from what preparing finds, the preparation is
    what is launched, and it submits the run itself once it knows."""
    ident = batch.new_id( root )
    stripped = [ a for a in argv if a != "--batch" ]
    forward = list( rest )

    places = [ ]
    for env, tags in targets:
        log = batch.batch_dir( root ) / f"{ident}-{R.slug( env.name )}.log"
        two = env.wraps_anything( tags ) and not env.single_pass( tags )
        got = batch.detach( env, tags,
                            [ "run", "--phase", "prepare", *forward ] if two else [ "run", *forward ],
                            root = root, log = log, child_env = child_env_for( env, tags ),
                            phase = "prepare" if two else "run",
                            then = [ "run", "--submit-run", *forward ] if two else None )
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


def submit_run( env, tags, rest, *, root ):
    """The end of a preparation launched by `--batch`: submit the run it has
    just prepared, sized from its plan, and say which job that is.

    This process is on the machine the scheduler is, inside the preparation's
    allocation but outside the layers after its scheduler -- so the run goes
    through the run phase's layers from here on, the leading `Ssh` aside."""
    import json
    plan = read_plan( root, env.name )
    if plan is None:
        print( bad( f"  {env.name}: no plan to submit a run from" ) )
        return 1
    stack = env.stack_for( "run", tags )
    if L.ssh_of( stack ) is not None:
        stack = stack[ 1 : ]
    ctx = L.Context( root = root, tags = tags, batch = True, phase = "run", needs = plan[ "needs" ] )
    cmd = L.Command( [ sys.executable, "-m", "errand", "run", "--from-plan", *rest ],
                     child_env_for( env, tags ) )
    if L.batch_of( stack ) is None:
        # Nothing to submit to: the session this runs in is the detachment,
        # and the run simply follows the preparation in it.
        ctx.batch = False
        wrapped = L.compose( stack, cmd, ctx )
        return subprocess.run( wrapped.argv, cwd = root, env = { **os.environ, **wrapped.env } ).returncode
    wrapped = L.compose( stack, cmd, ctx )
    got = subprocess.run( wrapped.argv, cwd = root, capture_output = True, text = True,
                          env = { **os.environ, **wrapped.env } )
    record = batch._from_submission( got, kind = "batch" )
    batch.submitted_path( plan_path( root, env.name ) ).write_text( json.dumps( record ) )
    if record[ "kind" ] == "failed":
        print( bad( f"  {env.name}: could not submit the run - {record.get( 'error', '' )}" ) )
        return 1
    print( dim( f"  submitted the run of {env.name}: job {record[ 'handle' ]}" ) )
    return 0


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


def show_batches( root, live = False ):
    records = batch.load_all( root )
    if not records:
        print( dim( "  nothing launched from here" ) )
        return 0
    try:
        while True:
            for record in records:
                batch.collect( root, record )
            if live:
                print( "\033[2J\033[H", end = "" )
            everything = [ ]
            for record in records:
                rows = batch.states( root, record )
                everything += rows
                _show_one( root, record, rows )
            if not live or batch.finished( everything ):
                return 0
            time.sleep( 2.0 )
    except KeyboardInterrupt:
        return 0


def _show_one( root, record, rows ):
    done = sum( 1 for r in rows if r[ "state" ] == batch.DONE )
    bar = "#" * ( 8 * done // max( 1, len( rows ) ) )
    print( head( f"\n{record[ 'id' ]}  {record[ 'command' ] or '(everything)'}" )
           + dim( f"   {record[ 'when' ]}   {done}/{len( rows )} [{bar:<8}]" ) )
    for place in record.get( "places", [ ] ):
        then = batch.run_job( root, place )
        state = batch.alive( then if then is not None else place )
        how = "running" if state else ( "finished" if state is False else "unknown" )
        job = f"{place[ 'kind' ]} {place.get( 'handle' ) or '-'}" + (
            f", then {then[ 'kind' ]} {then.get( 'handle' ) or '-'}" if then is not None else "" )
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
