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
    base = bootstrap.local_cache()
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
    _show_kept_here()
    return 0


def _show_kept_here():
    """What this machine keeps warm besides agents: imports ( zygotes ), virtual machines. Each goes
    with its owner -- `errand agents stop` for a zygote, `errand vm stop` for a machine."""
    from ..agents import table as T
    got = T.scan( guests = False )
    for z in got.get( "zygotes", [ ] ):
        print( dim( f"  imports kept warm beside {z[ 'agent' ]}  pid {z[ 'pid' ]}  ( goes with that agent )" ) )
    for vm in got.get( "vms", [ ] ):
        print( dim( f"  windows vm {vm[ 'name' ][ : 8 ]}  {vm[ 'state' ]}  keeper pid {vm[ 'keeper' ]}  ( errand vm stop )" ) )


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

def show_live( root: Path, ask = True, got = None ) -> int:
    """The commands whose connection was lost while their work went on: what `errand attach` follows.
    With `got` ( `tables()` ), whether it still runs is read there: no agent is asked, none started.
    Otherwise, with `ask`, the agent says -- through the hub, when one is up."""
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
        if got is not None:
            state = _state_read( rec, got )
        elif ask:
            state = _state( rec )
        if rec.get( "stop_requested" ):
            state = bad( "a stop was asked, and could not reach it  " ) + state
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


def _state_read( rec, got ) -> str:
    ids = { str( p ) for p in rec[ "procs" ] }
    running = sum( 1 for _, table, _ in got if table for r in _rows( "", table ) if r[ "id" ] in ids )
    if running:
        return good( f"running ( {running}/{len( ids )} )" )
    if any( table is None for _, table, _ in got ):
        return warn( "cannot say: a machine did not answer" )
    return dim( "not running any more: attach brings back what it wrote" )


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


# ── running, everywhere ────────────────────────────────────────────────────────

def remote_table( rec: dict, timeout = 90 ) -> dict:
    """What a machine of the ledger says runs there ( `agents.table` ), over one ssh that starts no
    agent: errand's sources shipped if they are not there, a Python found, the table read from disk."""
    import shlex
    import subprocess
    from ..layers.gateways import ssh_options
    target = rec[ "target" ]
    host, options = target[ "host" ], target.get( "options" ) or [ ]
    cache = bootstrap.ship( host, options, agent = False )
    then = f'exec "$py" {shlex.quote( f"{cache}/{bootstrap.boot_rel()}" )} -m errand.agents table\n'
    line = " ".join( shlex.quote( a ) for a in ( "sh", "-c", bootstrap._script( then, target.get( "python" ) or "python3" ) ) )
    got = subprocess.run( [ "ssh", *ssh_options( options ), host, line ], capture_output = True, text = True,
                          timeout = timeout, stdin = subprocess.DEVNULL )
    from ..agents.table import _parsed
    table = _parsed( got )
    if table is None:
        raise RuntimeError( ( got.stderr or got.stdout or "" ).strip()[ -300 : ] or f"exit {got.returncode}" )
    return table


def tables( ) -> list:
    """( machine, table or None, error ) for this machine and every machine of the ledger, asked at once."""
    import socket
    import threading
    from ..agents import ledger, table as T
    here = socket.gethostname()
    out = [ ( here.split( "." )[ 0 ], T.scan(), None ) ]
    asked = [ ]

    def one( rec ):
        try:
            got = remote_table( rec )
            if got.get( "host" ) != here:
                asked.append( ( rec[ "name" ], got, None ) )
        except Exception as err:
            asked.append( ( rec[ "name" ], None, str( err ).strip().splitlines()[ -1 ] if str( err ).strip() else type( err ).__name__ ) )

    threads = [ threading.Thread( target = one, args = ( rec, ), daemon = True ) for rec in ledger.machines() ]
    for t in threads:
        t.start()
    for t in threads:
        t.join( 120 )
    return out + sorted( asked, key = lambda a: a[ 0 ] )


def _rows( machine, table ) -> list:
    """Every process of a table, with where it runs: guests under their host."""
    now = table.get( "time" ) or 0
    rows = [ { **p, "machine": machine, "age": now - ( p.get( "started" ) or now ) } for p in table.get( "procs", [ ] ) ]
    for g in table.get( "guests", [ ] ):
        for p in g.get( "procs", [ ] ):
            rows.append( { **p, "machine": f"{machine} > windows {g[ 'vm' ][ : 8 ]}", "age": now - ( p.get( "started" ) or now ) } )
    return rows


def _project_names( root: Path ) -> set:
    """What the current project is called over there: its name, and the roots its `Ssh` layers give it."""
    names = { root.name }
    try:
        from .. import layers as L
        for env in config.envs.values():
            ssh = L.ssh_of( env.stack_for( "run" ) )
            if ssh is not None:
                names.add( Path( str( ssh.remote_root( L.Context( root = root ) ) ) ).name )
    except Exception:
        pass
    return names


def _state_of( r ) -> str:
    if r[ "state" ] == "running":
        return good( "running" )
    if r[ "state" ] == "orphaned":
        return bad( "orphaned: its agent is gone, the next one there stops it" )
    # Found by its environment only: an errand from before records said who a process is.
    return bad( "unowned" ) + dim( f": no agent holds it any more; `kill -- -{r.get( 'pgid' )}` on {r[ 'machine' ]} stops it" )


def show_running( root: Path, everything = False, got = None ) -> int:
    """What runs on errand's behalf, on this machine and on every machine work was sent to, whoever
    started it: this project in full, one line per other project ( `--all`: all in full ), the
    machines errand boots, and the machines that could not be asked. -> how many processes."""
    got = tables() if got is None else got
    rows, machines, failed, warm = [ ], [ ], [ ], [ ]
    for machine, table, error in got:
        if table is None:
            failed.append( ( machine, error ) )
            continue
        rows += _rows( machine, table )
        machines += [ { **vm, "machine": machine } for vm in table.get( "vms", [ ] ) ]
        warm += [ { **z, "machine": machine } for z in table.get( "zygotes", [ ] ) ]
        failed += [ ( f"{machine} > windows {g[ 'vm' ][ : 8 ]}", g[ "error" ] ) for g in table.get( "guests", [ ] ) if g.get( "error" ) ]
    work = [ r for r in rows if not r.get( "vm" ) ]
    mine = _project_names( root )
    projects = { }
    for r in work:
        projects.setdefault( Path( str( r.get( "project" ) or "?" ) ).name, [ ] ).append( r )

    print( head( "\nrunning" ) + dim( f"   ( on {', '.join( m for m, _, _ in got )}: this machine"
                                       + ( ", and every machine work was sent to from it )" if got[ 1 : ] else " )" ) ) )
    if not work and not machines:
        print( dim( "  nothing" ) )
    current = sorted( ( n for n in projects if n in mine ) )
    for name in current + sorted( n for n in projects if n not in mine and everything ):
        print( f"  {head( name )}" )
        for r in sorted( projects[ name ], key = lambda r: -r[ "age" ] ):
            state = _state_of( r )
            env = f"  --env {r[ 'env' ]}" if r.get( "env" ) else ""
            print( f"    {r[ 'machine' ]:<12} {r[ 'id' ] if r[ 'id' ].startswith( 'pgid' ) else r[ 'id' ][ : 8 ]}  {r[ 'what' ]}{dim( env )}  " + dim( f"{_ago( r[ 'age' ] )}  " ) + state )
    if not everything:
        for name in sorted( n for n in projects if n not in mine ):
            by = { }
            for r in projects[ name ]:
                by.setdefault( ( r[ "machine" ], r[ "state" ] ), 0 )
                by[ ( r[ "machine" ], r[ "state" ] ) ] += 1
            said = ", ".join( f"{n} {s if s == 'running' else bad( s )} on {m}" for ( m, s ), n in sorted( by.items() ) )
            print( f"  {name}: " + said )
    for vm in machines:
        size = f", {vm[ 'cpus' ]} cpus {vm[ 'ram' ]}" if vm.get( "cpus" ) else ""
        state = bad( "orphaned: QEMU without its keeper" ) if vm[ "state" ] == "orphaned" else vm[ "state" ]
        print( f"  {vm[ 'machine' ]}: windows vm {vm[ 'name' ][ : 8 ]} " + state + dim( size ) )
    if everything:
        for z in warm:
            print( dim( f"  {z[ 'machine' ]}: imports kept warm beside {z[ 'agent' ]} ( pid {z[ 'pid' ]} )" ) )
    elif warm:
        print( dim( f"  {len( warm )} zygote{'s' if len( warm ) > 1 else ''} keeping imports warm ( --all lists them )" ) )
    for machine, error in failed:
        print( warn( f"  {machine}: cannot say" ) + dim( f" ( {error} )" ) )
    return len( work )
