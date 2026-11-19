"""The list on the left, built from what the machines answered: no terminal here, so it is tested
without one.

    ▾ lmo                                         3 running · 1 waiting · read 2 s ago
        sdot-ffi    test_solve.py::solve  lmo-jax          12 min  iteration 41 ▕████▌   ▏ 41 %
        otrec       python grid2d.py                         4 h   waiting: slurm job 81234 pending, 2 min
        windows vm 3fa2c1                                          ready · 8 cpus 16G
          sdot-ffi  run ping                                 3 min  running
      ▸ history ( 37 )
"""
from __future__ import annotations

import time
from pathlib import Path

from .. import steps
from .panes import Row


def ago( seconds: float ) -> str:
    s = int( max( 0, seconds ) )
    return f"{s} s" if s < 90 else f"{s // 60} min" if s < 5400 else f"{s // 3600} h {s % 3600 // 60:02d}" \
        if s < 2 * 86400 else f"{s // 86400} d"


def project_of( p: dict ) -> str:
    return Path( str( p.get( "project" ) or "?" ) ).name


def state_of( p: dict, now: float ) -> tuple:
    """( mark, words ) of a process."""
    if p[ "state" ] == "running" and p.get( "waiting" ):
        w = p[ "waiting" ]
        since = f", {ago( now - w[ 'since' ] )}" if w.get( "since" ) else ""
        return "wait", f"waiting: {w.get( 'what' )}{since}"
    if p[ "state" ] == "running":
        return "run", "running"
    if p[ "state" ] == "orphaned":
        return "orph", "orphaned: its agent is gone"
    return "lost", "unowned: no agent holds it"


def step_words( s: dict | None ) -> str:
    """A process's row says its step ( ADR 0010 ): the text, and a bar when it says how far it is."""
    if not s:
        return ""
    said = [ s[ "text" ] ] if s.get( "text" ) else [ ]
    if s.get( "done" ) is not None:
        said.append( f"{steps.bar( s[ 'done' ], 8 )} {int( 100 * s[ 'done' ] )} %" )
    return " ".join( said )


def step_facts( s: dict | None, now: float ) -> list:
    """What the detail says of a step: ( name, value ) pairs, one per curve."""
    if not s:
        return [ ]
    out = [ ( "step", s[ "text" ] ) ] if s.get( "text" ) else [ ]
    if s.get( "done" ) is not None:
        eta = f"  {steps.duration( s[ 'eta' ] )} left" if s.get( "eta" ) is not None else ""
        out.append( ( "progress", f"{steps.bar( s[ 'done' ], 20 )} {int( 100 * s[ 'done' ] )} %{eta}" ) )
    if s.get( "t" ):
        out.append( ( "said", f"{ago( now - s[ 't' ] )} ago" ) )
    for k, v in ( s.get( "curves" ) or { } ).items():
        out.append( ( k, f"{steps.spark( v )}  {steps.number( v[ -1 ] )}" ) )
    return out


def _matches( query: str, *texts ) -> bool:
    hay = " ".join( str( t ) for t in texts if t ).lower()
    return all( w in hay for w in query.lower().split() )


def _proc_row( m, p, depth, mine ) -> Row:
    now = m.now()
    mark, words = state_of( p, now )
    project = project_of( p )
    env = f"  {p[ 'env' ]}" if p.get( "env" ) else ""
    label = f"{project:<14} {p[ 'what' ]}{env}"
    age = ago( now - p[ "started" ] ) if p.get( "started" ) else "?"
    if mark == "run" and p.get( "step" ):
        words = step_words( p[ "step" ] ) or words
    return Row( label, f"{age}  {words}", kind = "proc", data = ( m.name, p ), depth = depth, mark = mark,
                hits = range( len( project ) ) if project in mine else ( ) )


TABS = ( "runs", "machines" )


def build( machines, *, folded = (), opened = (), query = "", only = None, mine = (), shown = 50, tab = "runs" ) -> list:
    """The rows of a tab. `runs`: what runs, what waits, what is done, of every machine watched
    ( `runs_rows` ). `machines`: each machine, its gauges, its VMs and their guests' work. `only`: the
    project names to keep ( `p` ), None for all; `mine`: those of the current project. `shown`: how many
    runs done."""
    if tab == "runs":
        return runs_rows( machines, query = query, only = only, mine = mine, shown = shown, folded = folded )
    rows = [ ]
    mine = set( mine )

    def kept( m, p ):
        return ( only is None or project_of( p ) in only ) and _matches( query, m.name, project_of( p ), p.get( "what" ),
                                                                         p.get( "env" ), state_of( p, m.now() )[ 1 ] )

    for m in machines:
        table = m.table or { }
        # the work: neither a VM's keeper nor an agent kept warm ( errand's own, said in the detail )
        procs = [ p for p in table.get( "procs", [ ] ) if not p.get( "vm" ) and p.get( "kind" ) != "agent" ]
        vms = table.get( "vms", [ ] )
        guests = { g[ "vm" ]: g for g in table.get( "guests", [ ] ) }
        work = [ p for p in procs if kept( m, p ) ]
        waiting = sum( 1 for p in procs if p.get( "waiting" ) )
        # running / waiting: short, the same width whatever it says, so that the gauges line up
        said = [ f"{len( procs ) - waiting}/{waiting}" ]
        if m.error:
            said = [ "✗" ]                                  # why: in the detail
        elif not m.table:
            said = [ "…" ]
        elif time.time() - m.read_at > 30:
            said.append( f"silent {ago( time.time() - m.read_at )}" )
        name = m.name + ( " (here)" if m.here else "" )
        if getattr( m, "dormant", False ):
            # not contacted: greyed, how long without work, and nothing under it until `a`
            rows.append( Row( name, "off" if m.watch_set is False else ago( time.time() - ( m.last or 0 ) ),
                              kind = "dormant", data = ( m.name, None ) ) )
            continue
        is_open = m.name not in folded
        rows.append( Row( name, " · ".join( said ), kind = "machine" if not m.error else "broken", data = ( m.name, None ),
                          open = is_open, meters = meters( table.get( "resources" ) ) ) )
        if not is_open:
            continue
        for vm in vms:
            g = guests.get( vm[ "name" ] ) or { }
            inside = [ p for p in g.get( "procs", [ ] ) if kept( m, p ) ]
            if query and not inside and not _matches( query, m.name, "windows vm", vm[ "name" ], vm[ "state" ] ):
                continue
            size = f" · {vm[ 'cpus' ]} cpus {vm[ 'ram' ]}" if vm.get( "cpus" ) else ""
            state = "orphaned: QEMU without its keeper" if vm[ "state" ] == "orphaned" else vm[ "state" ]
            rows.append( Row( f"windows vm {vm[ 'name' ][ : 8 ]}", f"{state}{size}", kind = "vm", data = ( m.name, vm ),
                              depth = 1, mark = "orph" if vm[ "state" ] == "orphaned" else "" ) )
            if g.get( "error" ):
                rows.append( Row( f"cannot say: {g[ 'error' ]}", kind = "note", data = ( m.name, None ), depth = 2 ) )
            for p in inside:
                rows.append( _proc_row( m, { **p, "guest": vm[ "name" ] }, 2, mine ) )
        for z in table.get( "zygotes", [ ] ) if not query else [ ]:
            rows.append( Row( f"imports kept warm beside {z[ 'agent' ]}", f"pid {z[ 'pid' ]}", kind = "note",
                              data = ( m.name, None ), depth = 1 ) )
    return rows


def _where( m ) -> str:
    return m.name if len( m.name ) <= 12 else m.name[ : 11 ] + "…"


def _at( t: float, now: float ) -> str:
    """When it started: the hour today, the day and the hour before."""
    if time.localtime( t )[ : 3 ] == time.localtime( now )[ : 3 ]:
        return time.strftime( "%H:%M", time.localtime( t ) )
    return time.strftime( "%d %b %H:%M", time.localtime( t ) )


def _work_row( m, p, mine ) -> Row:
    """What runs or waits: its sign, its machine, what it is; its step, or what it waits for, and when it started."""
    mark, words = state_of( p, m.now() )
    env = f"  {p[ 'env' ]}" if p.get( "env" ) else ""
    said = step_words( p.get( "step" ) ) if mark == "run" else words
    when = _at( p[ "started" ], time.time() ) if p.get( "started" ) else ""
    return Row( f"{_where( m ):<12} {p[ 'what' ]}{env}", f"{said}  {when}".strip(), kind = "proc", data = ( m.name, p ),
                mark = mark )


def _run_row( m, r, mine, depth = 0 ) -> Row:
    """A run done: its sign, its machine, what it was; when it started."""
    status = r.get( "status" ) or ""
    # no result and not running: it ended without saying how ( killed, its machine gone )
    mark = { "PASS": "ok", "FAIL": "FAIL", "SKIP": "skip" }.get( status, "lost" )
    env = f"  {r[ 'env' ]}" if r.get( "env" ) else ""
    return Row( f"{_where( m ):<12} {r.get( 'what' )}{env}", time.strftime( "%H:%M", time.localtime( r.get( "started", 0 ) ) ),
                kind = "run", data = ( m.name, r ), depth = depth, mark = mark )


def _day( t: float, now: float ) -> str:
    day, today = time.localtime( t ), time.localtime( now )
    if day[ : 3 ] == today[ : 3 ]:
        return "done today"
    if day[ : 3 ] == time.localtime( now - 86400 )[ : 3 ]:
        return "yesterday"
    return time.strftime( "%a %d %b", day )


def runs_rows( machines, *, query = "", only = None, mine = (), shown = 50, folded = () ) -> list:
    """The runs tab: what runs, what waits, then what is done, newest first under the day it started --
    every machine watched in one list. A machine not watched ( `dormant` ) is not asked: it says nothing."""
    watched = [ m for m in machines if not getattr( m, "dormant", False ) ]
    work, done = [ ], [ ]
    for m in watched:
        for p in ( m.table or { } ).get( "procs", [ ] ):
            if p.get( "vm" ) or p.get( "kind" ) == "agent":
                continue
            if ( only is None or project_of( p ) in only ) and _matches( query, m.name, project_of( p ), p.get( "what" ),
                                                                       p.get( "env" ), state_of( p, m.now() )[ 1 ] ):
                work.append( ( m, p ) )
        for g in ( m.table or { } ).get( "guests", [ ] ):
            for p in g.get( "procs", [ ] ):
                if ( only is None or project_of( p ) in only ) and _matches( query, m.name, project_of( p ), p.get( "what" ) ):
                    work.append( ( m, { **p, "guest": g[ "vm" ] } ) )
        for r in ( m.history or { } ).get( "runs", [ ] ):
            if ( only is None or project_of( r ) in only ) and _matches( query, m.name, project_of( r ), r.get( "what" ),
                                                                       r.get( "env" ), r.get( "status" ) ):
                done.append( ( m, r ) )
    rows = [ ]
    # a run that still runs is under `running`, not done as well ( its record has no result yet )
    running = { ( m.name, p.get( "leaf" ) ) for m, p in work if p.get( "leaf" ) }
    done = [ ( m, r ) for m, r in done if r.get( "status" ) or ( m.name, r.get( "leaf" ) ) not in running ]
    work.sort( key = lambda mp: mp[ 1 ].get( "started" ) or 0 )
    for title, which in ( ( "running", lambda p: not p.get( "waiting" ) ), ( "waiting", lambda p: p.get( "waiting" ) ) ):
        these = [ ( m, p ) for m, p in work if which( p ) ]
        if these:
            is_open = ( "day", title ) not in folded
            rows.append( Row( f"{title} ( {len( these )} )", kind = "day", data = ( None, title ), open = is_open ) )
            rows += [ _work_row( m, p, mine ) for m, p in these ] if is_open else [ ]
    done.sort( key = lambda mr: -( mr[ 1 ].get( "started" ) or 0 ) )
    day, now = None, time.time()
    days = { }
    for m, r in done[ : shown ]:
        days[ _day( r.get( "started", 0 ), now ) ] = days.get( _day( r.get( "started", 0 ), now ), 0 ) + 1
    for m, r in done[ : shown ]:
        d = _day( r.get( "started", 0 ), now )
        if d != day:
            day = d
            is_open = ( "day", d ) not in folded
            rows.append( Row( d if is_open else f"{d} ( {days[ d ]} )", kind = "day", data = ( None, d ), open = is_open ) )
        if ( "day", d ) not in folded:
            rows.append( _run_row( m, r, mine ) )
    if len( done ) > shown:
        rows.append( Row( f"{len( done ) - shown} more ( enter )", kind = "more", data = ( None, "more" ) ) )
    if not rows:
        asking = any( m.table is None and not getattr( m, "dormant", False ) for m in machines )
        rows = [ Row( "asking the machines…" if asking else "nothing runs, nothing was run lately", kind = "note" ) ]
    return rows


def key( row: Row ):
    """What a row stands for, kept across rebuilds: the cursor stays on it."""
    machine, what = row.data if isinstance( row.data, tuple ) else ( None, None )
    kind = row.kind
    if isinstance( what, dict ):
        # a run by its leaf: the same whether it runs or is done -- the cursor stays on it as it ends
        what = what.get( "leaf" ) or what.get( "id" ) or what.get( "name" )
        if kind in ( "proc", "run" ):
            kind = "work"
    return ( kind, machine, what )


def facts( row: Row, m ) -> list:
    """What the detail says of `row` first: ( name, value ) pairs, the empty ones left out. The
    files and the output come after, read through the agent ( `tui.screen`, `web` )."""
    out = [ ]
    machine, what = row.data if isinstance( row.data, tuple ) else ( None, None )

    def line( k, v ):
        if v not in ( None, "" ):
            out.append( ( k, str( v ) ) )

    if row.kind == "dormant":
        line( "machine", m.name )
        if m.watch_set is False:
            line( "off", "not contacted: switched off ( a switches it on again; work sent there does too )" )
        else:
            line( "dormant", f"no work sent there for {ago( time.time() - ( m.last or 0 ) )}: not contacted, so that no "
                             "agent starts there for nothing" )
            line( "a", "contacts it, now and from now on ( saved: errand status too )" )
        return out
    if row.kind in ( "machine", "broken" ):
        line( "machine", m.name + ( "  ( this machine )" if m.here else "" ) )
        if m.target:
            line( "reached", f"ssh {m.target.get( 'host' )}, through its agent" )
        line( "error", m.error )
        if m.table:
            line( "host", m.table.get( "host" ) )
            procs = [ p for p in m.table.get( "procs", [ ] ) if not p.get( "vm" ) and p.get( "kind" ) != "agent" ]
            waiting = sum( 1 for p in procs if p.get( "waiting" ) )
            line( "work", f"{len( procs ) - waiting} running, {waiting} waiting"
                  + ( f", {len( m.table.get( 'vms' ) )} vm" if m.table.get( "vms" ) else "" ) )
            kept = sum( 1 for p in m.table.get( "procs", [ ] ) if p.get( "kind" ) == "agent" )
            if kept:
                line( "agents", f"{kept} kept warm ( k on this row stops them with the rest )" )
            if time.time() - m.read_at > 30:            # pushed ( `watch` ): only a silence is worth saying
                line( "silent", f"nothing heard for {ago( time.time() - m.read_at )}" )
            for k, v in resource_facts( m.table.get( "resources" ) ):
                line( k, v )
            for z in m.table.get( "zygotes", [ ] ):
                line( "warm", f"imports kept warm beside {z[ 'agent' ]} ( pid {z[ 'pid' ]} )" )
    elif row.kind == "vm":
        for k in ( "name", "state", "keeper", "qemu", "cpus", "ram", "port", "image" ):
            line( k, what.get( k ) )
    elif row.kind == "proc":
        p = what
        line( "machine", m.name + ( f" > windows {p[ 'guest' ][ : 8 ]}" if p.get( "guest" ) else "" ) )
        line( "project", p.get( "project" ) )
        line( "what", p.get( "what" ) )
        line( "env", p.get( "env" ) )
        line( "state", state_of( p, m.now() )[ 1 ] )
        for k, v in step_facts( p.get( "step" ), m.now() ):
            line( k, v )
        line( "started", f"{ago( m.now() - p[ 'started' ] )} ago" if p.get( "started" ) else None )
        line( "pid", f"{p.get( 'pid' )}" + ( f"  group {p[ 'pgid' ]}" if p.get( "pgid" ) else "" ) )
        line( "agent", f"{p.get( 'agent' )}" + ( "" if p.get( "agent_alive" ) else "  ( gone )" ) )
        line( "id", p.get( "id" ) )
        line( "leaf", p.get( "leaf" ) )
        line( "outputs", p.get( "dir" ) )
    elif row.kind == "run":
        r = what
        line( "project", r.get( "project" ) )
        line( "what", r.get( "what" ) )
        line( "env", r.get( "env" ) )
        line( "status", r.get( "status" ) or "no result yet" )
        line( "started", f"{ago( m.now() - r.get( 'started', 0 ) )} ago" )
        line( "took", ago( r[ "duration" ] ) if r.get( "duration" ) is not None else None )
        line( "leaf", r.get( "leaf" ) )
    return out


def stop_request( row: Row, m ) -> tuple:
    """What stops `row` -- a process, or a VM's keeper -- on its machine: ( the `kill` request, what
    to call it ). ValueError, said plainly, when it cannot be stopped from a watcher."""
    if row is None or row.kind not in ( "proc", "vm" ):
        raise ValueError( "put the cursor on a process or a vm" )
    what = row.data[ 1 ]
    if what.get( "guest" ):
        raise ValueError( "a guest's process stops from its command ( or stop its vm )" )
    if row.kind == "vm":
        keeper = next( ( p for p in ( m.table or { } ).get( "procs", [ ] ) if p.get( "vm" ) and p.get( "pid" ) == what.get( "keeper" ) ), None )
        req = { "op": "kill", "pgid": ( keeper or { } ).get( "pgid" ) or what.get( "keeper" ),
                "since": ( keeper or { } ).get( "since" ), "mark": ( keeper or { } ).get( "mark" ) }
        return req, f"windows vm {what[ 'name' ][ : 8 ]} on {m.name}"
    if not what.get( "pgid" ):
        raise ValueError( "no process group recorded for it: it cannot be stopped from here" )
    req = { "op": "kill", "pgid": what[ "pgid" ], "since": what.get( "since" ), "mark": what.get( "mark" ) }
    return req, f"{project_of( what )} {what.get( 'what' )} on {m.name}"


def meters( res: dict | None ) -> list:
    """A machine's gauges for its row: ( name, fraction ). The cores, the memory, each card ( their mean
    beyond two )."""
    if not res:
        return [ ]
    out = [ ]
    if res.get( "busy" ) is not None:
        out.append( ( "cpu", float( res[ "busy" ] ) ) )
    ram = res.get( "ram" ) or { }
    if ram.get( "total" ):
        out.append( ( "ram", ram[ "used" ] / ram[ "total" ] ) )
    cards = [ g for g in res.get( "gpus" ) or [ ] if g.get( "util" ) is not None ]
    if len( cards ) <= 2:
        out += [ ( f"gpu{g[ 'index' ]}", g[ "util" ] / 100 ) for g in cards ]
    else:
        out.append( ( f"gpu×{len( cards )}", sum( g[ "util" ] for g in cards ) / 100 / len( cards ) ) )
    return out


def _gb( mb ) -> str:
    return f"{mb / 1024:.0f} G" if mb >= 10 * 1024 else f"{mb / 1024:.1f} G"


def resource_facts( res: dict | None ) -> list:
    """The detail of a machine's resources: ( key, value ) lines."""
    if not res:
        return [ ]
    out = [ ]
    cpu = f"{res[ 'cpus' ]} cores"
    if res.get( "busy" ) is not None:
        cpu = f"{res[ 'busy' ] * 100:.0f} % of {cpu}"
    if res.get( "load" ) is not None:
        cpu += f" · load {res[ 'load' ]:.1f}"
    out.append( ( "cpu", cpu ) )
    ram = res.get( "ram" ) or { }
    if ram.get( "total" ):
        out.append( ( "ram", f"{_gb( ram[ 'used' ] )} of {_gb( ram[ 'total' ] )} used" ) )
    for g in res.get( "gpus" ) or [ ]:
        util = f"{g[ 'util' ]:.0f} %" if g.get( "util" ) is not None else "?"
        out.append( ( f"gpu {g[ 'index' ]}", f"{g.get( 'name', '' )} · {util} · {_gb( g[ 'used' ] )} of {_gb( g[ 'total' ] )}" ) )
    held = res.get( "held" ) or { }
    if held.get( "claims" ):
        what = "the whole machine" if held.get( "exclusive" ) else " · ".join( x for x in (
            f"{held[ 'cpus' ]:g} cpus" if held.get( "cpus" ) else "",
            _gb( held[ "ram" ] ) if held.get( "ram" ) else "",
            f"{held[ 'gpus' ]} gpu{'s' if held[ 'gpus' ] > 1 else ''}" if held.get( "gpus" ) else "" ) if x ) or "slots"
        out.append( ( "held", f"by errand: {what} ( {held[ 'claims' ]} claim{'s' if held[ 'claims' ] > 1 else ''} )" ) )
    if res.get( "scheduler" ):
        out.append( ( "scheduler", f"{res[ 'scheduler' ]} decides what runs here" ) )
    return out
