"""What a run asks of the machine, and what it is remembered to need ( ADR 0014 ).

Three ways to ask, one claim, each over the one before: the environment
( `Env( needs = … )` ), the command line ( `--gpus`, `--gpu-ram`, `-x` ), and
the run's own code ( `errand.require` ), which grows the claim while it runs.

With `errand.configure( remember_needs = True )`, what the code required is
remembered on the machine that ran it, by environment and target:

    errand-outputs/state/needs.json     { host: { env: { target: needs } } }

and claimed up front the next time, as if it had been on the command line. It
then rarely grows while running, and its cards are known from its first line.
A target that no longer calls `require` drops what was remembered after one
run. Another machine, another capacity: each learns its own.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import config, queue

FILE = "needs.json"


def target_of( e, root ) -> str:
    """How a target is named in what is remembered: its file from the root, and its name."""
    try:
        rel = Path( e.file ).resolve().relative_to( Path( root ).resolve() ).as_posix()
    except ValueError:
        rel = Path( e.file ).name
    return f"{rel}::{e.name}"


def _path( root ) -> Path:
    return config.state( Path( root ) ) / FILE


def _read( root ) -> dict:
    try:
        return json.loads( _path( root ).read_text() )
    except ( OSError, ValueError ):
        return { }


def remembered( root, env_name: str, target: str ) -> dict:
    """What `target` required the last time it ran in `env_name` on this machine ( `exclusive` included )."""
    return dict( ( ( _read( root ).get( queue.host() ) or { } ).get( env_name ) or { } ).get( target ) or { } )


def remember( root, env_name: str, target: str, row: dict ):
    """Keep what a run's claim says its code came to ( `wanted`, `required_exclusive` ): the total,
    not the calls, so that a `require( extra = True )` is not added twice the next time. Forget it
    when the code required nothing this time."""
    got = dict( row.get( "wanted" ) or { } )
    if row.get( "required_exclusive" ):
        got[ "exclusive" ] = True
    if remembered( root, env_name, target ) == got:
        return
    path = _path( root )
    with queue._lock():                     # several runs of one machine may end at once
        data = _read( root )
        place = data.setdefault( queue.host(), { } ).setdefault( env_name, { } )
        if got:
            place[ target ] = got
        else:
            place.pop( target, None )
        try:
            path.parent.mkdir( parents = True, exist_ok = True )
            tmp = path.with_suffix( f".{os.getpid()}.tmp" )
            tmp.write_text( json.dumps( data, indent = 1, sort_keys = True ) )
            os.replace( tmp, path )
        except OSError:
            pass                            # a read-only tree remembers nothing, and runs as well


def of_env( env_name: str ) -> tuple:
    """( needs, exclusive ) of the environment `env_name`, as declared."""
    env = config.envs.get( env_name )
    declared = dict( getattr( env, "needs", None ) or { } )
    return { k: v for k, v in declared.items() if k != "exclusive" }, bool( declared.get( "exclusive" ) )


def asked( env_name: str, resources: dict, command: dict, exclusive: bool, *, root = None,
           target = None ) -> tuple:
    """( needs, exclusive, remembered ) of one run: the environment's, under the entry's own
    ( `ranks` ), under the command line's; then what it required last time, added to them."""
    base, excl = of_env( env_name )
    needs = queue.normalize( { **base, **( resources or { } ), **( command or { } ) } )
    excl = excl or exclusive
    mem = remembered( root, env_name, target ) if root is not None and target and config.settings.remember_needs else { }
    if mem:
        excl = excl or bool( mem.pop( "exclusive", False ) )
        needs = { **needs, **queue.merged( needs, queue.normalize( mem ) ) }
    return needs, excl, mem


def shown( needs: dict ) -> str:
    return ", ".join( f"{k}={v if isinstance( v, str ) else f'{v:g}'}" for k, v in needs.items() if k != "exclusive" ) + \
        ( ", exclusive" if needs.get( "exclusive" ) else "" )


def run_claimed( e, *, env_name, ask, root, queued, run, echo, whole_if_unasked = False ):
    """Claim what one run asks, run it ( `run( handed, devices )` ), remember what it required, and
    run it again, once, when its `require` was stopped in a cycle ( `errand.Rerun` ).

    The claim is taken OUTSIDE the timing: waiting for the machine is not part of how long the work
    takes. `whole_if_unasked`: in an allocation errand holds, what says nothing of its needs takes
    all of it ( ADR 0009 )."""
    target = target_of( e, root )
    label = ask.label or f"{e.file.name}::{e.name}"
    stopped = { }                   # what the first attempt came to, when it was stopped to run again
    for attempt in ( 1, 2 ):
        needs, exclusive, mem = asked( env_name, e.resources, ask.resources, ask.exclusive,
                                       root = root, target = target )
        # what it is started with by what it is told, that `require( extra = True )` adds to
        base = asked( env_name, e.resources, ask.resources, ask.exclusive )[ 0 ]
        if stopped:
            exclusive = exclusive or bool( stopped.get( "exclusive" ) )
            needs = { **needs, **queue.merged( needs, queue.normalize( stopped ) ) }
        elif mem and queued:
            echo( f"  claimed up front, as it required last time: {shown( mem )}" )
        whole = whole_if_unasked and not needs and not exclusive
        with queue.claim( needs, exclusive = exclusive or whole, label = label, enabled = queued,
                          echo = echo, base = base ) as granted:
            # Being told WHICH card is the whole point of asking for one. Everything this entry
            # starts inherits the claim: an errand it runs must not queue for a machine its own
            # parent is holding.
            handed = { **granted.env(), **granted.handed_down() }
            devices = granted.devices if granted.devices and granted.path else None
            result = run( handed, devices )
            row = granted.row()
        if granted.path is not None and config.settings.remember_needs:
            remember( root, env_name, target, row )
        if attempt == 2 or not row.get( "rerun" ):
            return result
        stopped = { **( row.get( "wanted" ) or { } ), "exclusive": bool( row.get( "required_exclusive" ) ) }
        echo( f"  {label}: run again, with what it required up front ( {shown( stopped )} )" )
