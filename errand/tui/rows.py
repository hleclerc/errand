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


def build( machines, *, folded = (), opened = (), query = "", only = None, mine = (), shown = 50 ) -> list:
    """The rows: per machine, its processes ( work, then VMs with their guests' work ), then its
    history, folded unless opened. `only`: the project names to keep ( `p` ), None for all; `mine`:
    those of the current project, highlighted. `shown`: how many runs of a history."""
    rows = [ ]
    mine = set( mine )

    def kept( m, p ):
        return ( only is None or project_of( p ) in only ) and _matches( query, m.name, project_of( p ), p.get( "what" ),
                                                                         p.get( "env" ), state_of( p, m.now() )[ 1 ] )

    for m in machines:
        table = m.table or { }
        procs = [ p for p in table.get( "procs", [ ] ) if not p.get( "vm" ) ]
        vms = table.get( "vms", [ ] )
        guests = { g[ "vm" ]: g for g in table.get( "guests", [ ] ) }
        work = [ p for p in procs if kept( m, p ) ]
        waiting = sum( 1 for p in procs if p.get( "waiting" ) )
        said = [ f"{len( procs ) - waiting} running" if procs else "idle" ] + ( [ f"{waiting} waiting" ] if waiting else [ ] )
        if vms:
            said.append( f"{len( vms )} vm{'s' if len( vms ) > 1 else ''}" )
        if m.error:
            said = [ f"cannot say: {m.error}" ] + ( [ "( last table shown )" ] if m.table else [ ] )
        elif not m.table:
            said = [ "asking…" ]
        else:
            said.append( f"read {ago( time.time() - m.read_at )} ago" )
        name = m.name + ( "  ( this machine )" if m.here else "" )
        is_open = m.name not in folded
        rows.append( Row( name, " · ".join( said ), kind = "machine" if not m.error else "broken", data = ( m.name, None ),
                          open = is_open ) )
        if not is_open:
            continue
        for p in sorted( work, key = lambda p: p.get( "started" ) or 0 ):
            rows.append( _proc_row( m, p, 1, mine ) )
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
        hist = ( m.history or { } ).get( "runs", [ ] )
        runs = [ r for r in hist if ( only is None or project_of( r ) in only )
                 and _matches( query, m.name, project_of( r ), r.get( "what" ), r.get( "env" ), r.get( "status" ) ) ]
        if runs:
            opened_here = m.name in opened
            rows.append( Row( f"history ( {len( runs )}{'+' if ( m.history or { } ).get( 'more' ) else ''} )", kind = "group",
                              data = ( m.name, "history" ), depth = 1, open = opened_here ) )
            if opened_here:
                for r in runs[ : shown ]:
                    rows.append( _run_row( m, r, mine ) )
                if len( runs ) > shown:
                    rows.append( Row( f"{len( runs ) - shown} more ( enter )", kind = "more", data = ( m.name, "more" ), depth = 2 ) )
    return rows


def _run_row( m, r, mine ) -> Row:
    project = project_of( r )
    status = r.get( "status" ) or ""
    mark = { "PASS": "ok", "FAIL": "FAIL", "SKIP": "skip" }.get( status, ".." )
    duration = f"  {ago( r[ 'duration' ] )}" if r.get( "duration" ) is not None else ""
    env = f"  {r[ 'env' ]}" if r.get( "env" ) else ""
    return Row( f"{project:<14} {r.get( 'what' )}{env}", f"{ago( m.now() - r.get( 'started', 0 ) )} ago{duration}",
                kind = "run", data = ( m.name, r ), depth = 2, mark = mark,
                hits = range( len( project ) ) if project in mine else ( ) )


def key( row: Row ):
    """What a row stands for, kept across rebuilds: the cursor stays on it."""
    machine, what = row.data if isinstance( row.data, tuple ) else ( None, None )
    if isinstance( what, dict ):
        what = what.get( "id" ) or what.get( "name" ) or what.get( "leaf" )
    return ( row.kind, machine, what )


def facts( row: Row, m ) -> list:
    """What the detail says of `row` first: ( name, value ) pairs, the empty ones left out. The
    files and the output come after, read through the agent ( `tui.screen`, `web` )."""
    out = [ ]
    machine, what = row.data if isinstance( row.data, tuple ) else ( None, None )

    def line( k, v ):
        if v not in ( None, "" ):
            out.append( ( k, str( v ) ) )

    if row.kind in ( "machine", "broken" ):
        line( "machine", m.name + ( "  ( this machine )" if m.here else "" ) )
        if m.target:
            line( "reached", f"ssh {m.target.get( 'host' )}, through its agent" )
        line( "error", m.error )
        if m.table:
            line( "host", m.table.get( "host" ) )
            line( "read", f"{ago( time.time() - m.read_at )} ago" )
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
