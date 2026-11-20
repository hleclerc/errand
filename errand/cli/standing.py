"""What stays between commands, and what is still running: `errand agents`, and the head of `errand status`.

    errand agents                 the hub, and every agent it keeps a stream to
    errand agents stop [NAME]     those whose name holds NAME go now ( all of them, and the hub, without )

An agent with something running is left alone, unless `--force`. An allocation held warm goes
with its agent: the job ends.
"""
from __future__ import annotations

import time

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
    conn = agents.open( rec[ "target" ], noted = False )      # asking is no work sent there
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
    then = f'exec "$py" {shlex.quote( f"{cache}/{bootstrap.boot_rel()}" )} -m errand.agents table --caches\n'
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
    out = [ ( ledger.here_name(), { **T.scan(), "caches": T.caches_summary() }, None ) ]
    asked = [ ]

    def one( rec ):
        try:
            got = remote_table( rec )
            if got.get( "host" ) != here:
                asked.append( ( rec[ "name" ], got, None ) )
        except Exception as err:
            asked.append( ( rec[ "name" ], None, str( err ).strip().splitlines()[ -1 ] if str( err ).strip() else type( err ).__name__ ) )

    # A machine no work was sent to for a day is not contacted ( `ledger.dormant` ): no agent of errand's
    # started for nothing on a machine others share.
    threads = [ threading.Thread( target = one, args = ( rec, ), daemon = True ) for rec in ledger.groups()
                if ledger.watched( rec ) ]                # each machine once, whatever names reach it
    for t in threads:
        t.start()
    for t in threads:
        t.join( 120 )
    return out + sorted( asked, key = lambda a: a[ 0 ] )


def _rows( machine, table ) -> list:
    """Every process of a table, with where it runs: guests under their host."""
    now = table.get( "time" ) or 0
    rows = [ { **p, "machine": machine, "age": now - ( p.get( "started" ) or now ), "now": now }
             for p in table.get( "procs", [ ] ) ]
    for g in table.get( "guests", [ ] ):
        for p in g.get( "procs", [ ] ):
            rows.append( { **p, "machine": f"{machine} > windows {g[ 'vm' ][ : 8 ]}",
                           "age": now - ( p.get( "started" ) or now ), "now": now } )
    for n in table.get( "nodes", [ ] ):                         # an allocation's agents, read on its node
        for p in n.get( "procs", [ ] ):
            rows.append( { **p, "machine": f"{machine} > {n[ 'node' ]}",
                           "age": now - ( p.get( "started" ) or now ), "now": now } )
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


def _state_of( r, now = None ) -> str:
    if r[ "state" ] == "running" and r.get( "waiting" ):
        w = r[ "waiting" ]
        since = f", {_ago( ( now or 0 ) - w[ 'since' ] )}" if now and w.get( "since" ) else ""
        return warn( f"waiting: {w.get( 'what' )}" ) + dim( since )
    if r[ "state" ] == "running":
        from .. import steps
        said = steps.line( r.get( "step" ) )            # ADR 0010
        return good( "running" ) + ( dim( f" · {said}" ) if said else "" )
    if r[ "state" ] == "orphaned":
        return bad( "orphaned: its agent is gone, the next one there stops it" )
    # Found by its environment only: an errand from before records said who a process is.
    return bad( "unowned" ) + dim( f": no agent holds it any more; `kill -- -{r.get( 'pgid' )}` on {r[ 'machine' ]} stops it" )


def show_running( root: Path, everything = False, got = None ) -> int:
    """What runs on errand's behalf, on this machine and on every machine work was sent to, whoever
    started it: this project in full, one line per other project ( `--all`: all in full ), the
    machines errand boots, and the machines that could not be asked. -> how many processes."""
    got = tables() if got is None else got
    rows, machines, failed, warm, served = [ ], [ ], [ ], [ ], [ ]
    for machine, table, error in got:
        if table is None:
            failed.append( ( machine, error ) )
            continue
        rows += _rows( machine, table )
        machines += [ { **vm, "machine": machine } for vm in table.get( "vms", [ ] ) ]
        warm += [ { **z, "machine": machine } for z in table.get( "zygotes", [ ] ) ]
        served += [ { **v, "machine": machine } for v in table.get( "services", [ ] ) ]
        failed += [ ( f"{machine} > windows {g[ 'vm' ][ : 8 ]}", g[ "error" ] ) for g in table.get( "guests", [ ] ) if g.get( "error" ) ]
        failed += [ ( f"{machine} > {n[ 'node' ]} ( slurm job {n[ 'job' ]} )", n[ "error" ] ) for n in table.get( "nodes", [ ] ) if n.get( "error" ) ]
    # The bridges to environment agents are what is kept warm, not work: counted, listed under --all.
    agents_up = [ r for r in rows if r.get( "kind" ) == "agent" and not r.get( "waiting" ) and r[ "state" ] == "running" ]
    # A service's keeper is said as the service, below, not as work ( ADR 0018 ).
    work = [ r for r in rows if not r.get( "vm" ) and r not in agents_up and "errand.serve keep" not in str( r.get( "what" ) ) ]
    mine = _project_names( root )
    projects = { }
    for r in work:
        projects.setdefault( Path( str( r.get( "project" ) or "?" ) ).name, [ ] ).append( r )

    print( head( "\nrunning" ) + dim( f"   ( on {', '.join( m for m, _, _ in got )}: this machine"
                                       + ( ", and every machine work was sent to from it )" if got[ 1 : ] else " )" ) ) )
    from ..agents import ledger
    asleep = [ r[ "name" ] + ( " ( off )" if r.get( "watch" ) is False else "" ) for r in ledger.groups() if not ledger.watched( r ) ]
    if asleep:
        print( dim( f"  not asked: {', '.join( asleep )} ( no work sent there lately, or switched off: `a` in errand tui,"
                    " `errand machines watch NAME on` )" ) )
    if not work and not machines and not served:
        print( dim( "  nothing" ) )
    current = sorted( ( n for n in projects if n in mine ) )
    for name in current + sorted( n for n in projects if n not in mine and everything ):
        print( f"  {head( name )}" )
        for r in sorted( projects[ name ], key = lambda r: -r[ "age" ] ):
            state = _state_of( r, r.get( "now" ) )
            env = f"  --env {r[ 'env' ]}" if r.get( "env" ) else ""
            print( f"    {r[ 'machine' ]:<12} {r[ 'id' ] if r[ 'id' ].startswith( 'pgid' ) else r[ 'id' ][ : 8 ]}  {r[ 'what' ]}{dim( env )}  " + dim( f"{_ago( r[ 'age' ] )}  " ) + state )
    if not everything:
        for name in sorted( n for n in projects if n not in mine ):
            by = { }
            for r in projects[ name ]:
                state = "waiting" if r[ "state" ] == "running" and r.get( "waiting" ) else r[ "state" ]
                by.setdefault( ( r[ "machine" ], state ), 0 )
                by[ ( r[ "machine" ], state ) ] += 1
            said = ", ".join( f"{n} {s if s in ( 'running', 'waiting' ) else bad( s )} on {m}" for ( m, s ), n in sorted( by.items() ) )
            print( f"  {name}: " + said )
    for vm in machines:
        size = f", {vm[ 'cpus' ]} cpus {vm[ 'ram' ]}" if vm.get( "cpus" ) else ""
        state = bad( "orphaned: QEMU without its keeper" ) if vm[ "state" ] == "orphaned" else vm[ "state" ]
        print( f"  {vm[ 'machine' ]}: windows vm {vm[ 'name' ][ : 8 ]} " + state + dim( size ) )
    for v in served:
        ports = v.get( "ports" ) or { }
        where = " ".join( f"{n}={p[ 'address' ]}" for n, p in ports.items() ) if len( ports ) > 1 else v.get( "address" ) or ""
        conns = f", {v[ 'connections' ]} connection{'s' * ( v[ 'connections' ] != 1 )}" if v.get( "connections" ) else ""
        queued = f", {v[ 'waiting' ]} waiting" if v.get( "waiting" ) else ""
        print( f"  {v[ 'machine' ]}: service {v[ 'name' ]} " + ( good( v[ "state" ] ) if v[ "state" ] in ( "busy", "in use" )
                                                                  else v[ "state" ] )
               + dim( f"  {where}{conns}{queued}" + ( f"  {v[ 'detail' ]}" if v.get( "detail" ) and not conns else "" ) ) )
    if everything:
        for a in agents_up:
            print( dim( f"  {a[ 'machine' ]}: {a[ 'what' ]} kept warm for {Path( str( a.get( 'project' ) or '?' ) ).name}" ) )
    elif agents_up:
        print( dim( f"  {len( agents_up )} environment agent{'s' if len( agents_up ) > 1 else ''} kept warm ( --all lists them )" ) )
    if everything:
        for z in warm:
            print( dim( f"  {z[ 'machine' ]}: imports kept warm beside {z[ 'agent' ]} ( pid {z[ 'pid' ]} )" ) )
    elif warm:
        print( dim( f"  {len( warm )} zygote{'s' if len( warm ) > 1 else ''} keeping imports warm ( --all lists them )" ) )
    for machine, error in failed:
        print( warn( f"  {machine}: cannot say" ) + dim( f" ( {error} )" ) )
    return len( work )


def show_caches( got ) -> int:
    """The library caches each machine holds ( ADR 0022 ): entries, size, what is dead, what has not served for
    30 days. A directory reached from two machines ( NFS ) is said once. -> how many caches."""
    from .. import caches as C
    from .caches import cache_line
    said, seen = [ ], set()
    for machine, table, _ in got:
        rep = ( table or { } ).get( "caches" )
        if not rep:
            continue
        if rep.get( "error" ):
            said.append( warn( f"  {machine}: caches cannot be read ( {rep[ 'error' ]} )" ) )
            continue
        for d in rep.get( "dirs", [ ] ):
            if d.get( "id" ) in seen or not d.get( "caches" ):
                continue
            seen.add( d.get( "id" ) )
            project = Path( d[ "project" ] ).name if d.get( "project" ) else Path( d[ "path" ] ).parent.parent.name
            for c in d[ "caches" ]:
                said.append( f"  {machine:<12} {project}/{cache_line( c )}" )
    if said:
        print( head( "\ncaches" ) + dim( "   ( errand caches [MACHINE] tidies them; the tui's tab 3 removes by hand )" ) )
        for line in said:
            print( line )
    return len( said )


def machines_main( words ) -> int:
    """`errand machines`: the machines errand asks what runs there ( the ledger, ADR 0008 ), each once
    whatever names it is reached by, most recently used first. `errand machines forget NAME...`: not asked
    any more, until work is sent there again; `errand machines rename NAME LABEL`: shown as LABEL."""
    from ..agents import ledger
    from .style import bad, dim
    if not words:
        rows = ledger.groups()
        if not rows:
            print( dim( "  no machine: work was never sent elsewhere from here ( or not for two weeks )" ) )
            return 0
        width = max( len( r[ "name" ] ) for r in rows )
        for r in rows:
            also = [ n for n in r[ "names" ] if n != r[ "name" ] ]
            state = "" if ledger.watched( r ) else "  off" if r.get( "watch" ) is False else "  dormant: not asked"
            print( f"  {r[ 'name' ]:{width}}  {dim( _ago( time.time() - r[ 'last' ] ) + ' ago' )}" + dim( state )
                   + ( dim( f"  also {', '.join( also )}" ) if also else "" ) )
        print( dim( "  errand machines forget NAME · rename NAME LABEL · watch NAME on|off|auto" ) )
        return 0
    if words[ 0 ] == "watch" and len( words ) == 3 and words[ 2 ] in ( "on", "off", "auto" ):
        names = ledger.set_watch( words[ 1 ], { "on": True, "off": False, "auto": None }[ words[ 2 ] ] )
        if not names:
            print( bad( f"  {words[ 1 ]}: no such machine" ) )
            return 1
        print( f"  {', '.join( names )}: " + { "on": "watched", "off": "not watched", "auto": "watched while work is sent there" }[ words[ 2 ] ] )
        return 0
    if words[ 0 ] == "rename" and len( words ) == 3:
        names = ledger.rename( words[ 1 ], words[ 2 ] )
        if not names:
            print( bad( f"  {words[ 1 ]}: no such machine" ) )
            return 1
        print( f"  {', '.join( names )}: shown as {words[ 2 ]}" )
        return 0
    if words[ 0 ] != "forget" or len( words ) < 2:
        print( bad( "errand machines: `errand machines`, `errand machines forget NAME...`, `errand machines rename NAME LABEL`" ) )
        return 2
    rc = 0
    for name in words[ 1 : ]:
        gone = ledger.forget( name )
        if gone:
            print( f"  {', '.join( gone )}: forgotten" )
        else:
            known = sorted( { n for g in ledger.groups() for n in g[ "names" ] } )
            print( bad( f"  {name}: no such machine" ) + dim( f" ( known: {', '.join( known ) or 'none'} )" ) )
            rc = 1
    return rc


def _ago( s: float ) -> str:
    if s < 120:
        return f"{s:.0f} s"
    if s < 7200:
        return f"{s / 60:.0f} min"
    if s < 172800:
        return f"{s / 3600:.0f} h"
    return f"{s / 86400:.0f} days"
