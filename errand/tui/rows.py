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


TABS = ( "runs", "machines", "caches" )


def build( machines, *, folded = (), opened = (), query = "", only = None, mine = (), shown = 50, tab = "runs",
           days = 30, every = False, unfold = False, reach = None ) -> list:
    """The rows of a tab. `runs`: what runs, what waits, what is done, of every machine watched
    ( `runs_rows` ). `machines`: each machine, its gauges, its VMs and their guests' work. `only`: the
    project names to keep ( `p` ), None for all; `mine`: those of the current project. `shown`: how many
    runs done."""
    if tab == "runs":
        return runs_rows( machines, query = query, only = only, mine = mine, shown = shown, folded = folded, opened = opened,
                          unfold = unfold, reach = reach )
    if tab == "caches":
        from . import caches            # ADR 0022: `days` unused, `every` entry or the flagged ones only
        return caches.rows( machines, folded = folded, opened = opened, query = query, days = days, every = every )
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


def runs_rows( machines, *, query = "", only = None, mine = (), shown = 50, folded = (), opened = (), unfold = False,
               reach = None ) -> list:
    """The runs tab: what runs, what waits, then every run as a tree ( ADR 0023, `runtree` ): the directories of its
    file, the file, the entry, its parameter sets as a table, their runs -- every machine watched in one tree. A machine
    not watched ( `dormant` ) is not asked: it says nothing."""
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
    rows = [ ]
    # in the tree, every run of this machine's record ( ADR 0025 ), those running at their place too ( marked )
    running = { x for m, p in work if p.get( "leaf" ) for x in ( rel_of( p[ "leaf" ] ), p[ "leaf" ] ) } - { None }
    every = record_runs( machines, running, query = query, only = only )
    work.sort( key = lambda mp: mp[ 1 ].get( "started" ) or 0 )
    for title, which in ( ( "running", lambda p: not p.get( "waiting" ) ), ( "waiting", lambda p: p.get( "waiting" ) ) ):
        these = [ ( m, p ) for m, p in work if which( p ) ]
        if these:
            is_open = ( "day", title ) not in folded
            rows.append( Row( f"{title} ( {len( these )} )", kind = "day", data = ( None, title ), open = is_open ) )
            rows += [ _work_row( m, p, mine ) for m, p in these ] if is_open else [ ]
    from . import runtree as T
    tree = tree_of( every )
    if reach is not None:                      # a row looked up by its key: what is above it opened, nothing else
        path = { f"t:{i}" for i in T.path_to( tree, reach ) }
        opened, folded = set( opened ) | path, set( folded ) - path
    rows += T.rows( tree, folded = folded, opened = opened, query = query, now = time.time(), unfold = unfold )
    if not rows:
        asking = any( m.table is None and not getattr( m, "dormant", False ) for m in machines )
        rows = [ Row( "asking the machines…" if asking else "nothing runs, nothing was run lately", kind = "note" ) ]
    return rows


# ── this machine's record of runs ( ADR 0025 ) ───────────────────────────────

RUNS_ANCHOR = "/errand-outputs/runs/"


def rel_of( leaf ) -> str | None:
    """a run's path under its project's `runs/`: the same here and on the machine it ran on"""
    leaf = str( leaf or "" )
    i = leaf.find( RUNS_ANCHOR )
    return leaf[ i + len( RUNS_ANCHOR ) : ].strip( "/" ) if i >= 0 else None


class Elsewhere:
    """a machine a run ran on that errand does not watch ( a hostname only ): named, never asked"""
    here, dormant, table, history, error = False, True, None, None, None

    def __init__( self, name ):
        self.name = name

    def ask( self, *_, **__ ):
        raise RuntimeError( f"{self.name}: no agent errand knows of there" )


_elsewhere: dict = { }


def machine_of( machines ):
    """-> `of( host )`: the machine a run's `result.yaml` names ( its `host` ), as errand shows it -- this one ( whatever
    number the network gave its name: `hugos-macbook-pro14`, `…23` ), one of the ledger's, or a name only"""
    import re
    import socket
    from ..agents import ledger
    by_host = { }
    try:
        for g in ledger.groups():
            if g.get( "host" ):
                by_host[ g[ "host" ].split( "." )[ 0 ] ] = g.get( "name" )
    except Exception:
        pass
    for m in machines:
        if getattr( m, "_host", None ):
            by_host[ m._host.split( "." )[ 0 ] ] = m.name
    named = { m.name: m for m in machines }
    here = next( ( m for m in machines if getattr( m, "here", False ) ), None )
    me = socket.gethostname().split( "." )[ 0 ].lower()
    stem = re.sub( r"\d+$", "", me )
    known: dict = { }

    def of( host ):
        h = str( host or "" ).split( "." )[ 0 ]
        got = known.get( h )
        low = h.lower()
        if got is None:
            if not h or low == me or ( stem and re.sub( r"\d+$", "", low ) == stem ) or by_host.get( h ) == getattr( here, "name", None ):
                got = here
            elif by_host.get( h ) in named:
                got = named[ by_host[ h ] ]
            else:
                got = _elsewhere.setdefault( h, Elsewhere( h ) )
            known[ h ] = got
        return got
    return of


def record_runs( machines, running = (), query = "", only = None ) -> list:
    """`( machine, record, running )` for every run of this machine's record, as the runs' tree reads them, and those the
    check found on another machine only ( `there_only` ). Kept for the same record, check, runs running, filter and
    machines ( the same list: the tree built from it is kept too )"""
    from ..agents import registry as G
    reg = G.shared()
    reg.refresh( every = 3.0 )
    recs = _records( reg )
    key = ( _recs[ 0 ], CHECKED_V[ 0 ], frozenset( running ), query, None if only is None else frozenset( only ),
            tuple( ( m.name, getattr( m, "_host", None ) ) for m in machines ) )
    if _every[ 0 ] == key:
        return _every[ 1 ]
    of = machine_of( machines )
    named = { m.name: m for m in machines }
    out = [ ]
    for m, r in [ ( of( r.get( "host" ) ), r ) for r in recs ] + \
                [ ( named.get( n ) or Elsewhere( n ), r ) for n, rs in CHECKED.items() for r in rs ]:
        if m is None:
            continue
        if ( only is None and not query ) or ( ( only is None or project_of( r ) in only ) and
                                               _matches( query, m.name, project_of( r ), r.get( "what" ), r.get( "env" ), r.get( "status" ) ) ):
            out.append( ( m, r, ( r.get( "rel" ) in running or r.get( "leaf" ) in running ) and not r.get( "status" ) ) )
    _every[ 0 ], _every[ 1 ] = key, out
    return out


# ── the check ( ADR 0025 ): the runs a machine noted that this one's record does not hold ─────────────────────────

CHECKED: dict = { }                 # machine name -> [ records of runs there only ]
CHECKED_V = [ 0 ]
CHECKED_AT: dict = { }              # machine name -> when it was checked, or why it could not be


def check( machines ) -> str:
    """every machine watched asked for all the runs it noted; those whose path under `runs/` is not in this machine's
    record are listed, marked, at their place ( `there_only` ). -> what was found, said"""
    from ..agents import registry as G
    from . import removal as RM
    reg = G.shared()
    reg.refresh( force = True )
    here_rels = { r.rel for r in list( reg.runs.values() ) }
    asked = [ m for m in machines if not getattr( m, "here", False ) and not getattr( m, "dormant", False ) ]
    got = RM._each( { m.name: ( m, None ) for m in asked },
                    lambda m, _: m.ask( { "op": "seen", "limit": 1 << 30 }, timeout = 120 ) )
    said = [ ]
    for m in asked:
        answer = got.get( m.name )
        if isinstance( answer, Exception ) or answer is None:
            CHECKED_AT[ m.name ] = f"not reached: {answer}"
            said.append( f"{m.name}: not reached" )
            continue
        only = [ ]
        for h in answer.get( "runs", [ ] ):
            rel = rel_of( h.get( "leaf" ) )
            if rel and rel not in here_rels:
                only.append( { **h, "rel": rel, "there": True, "host": getattr( m, "_host", None ) or m.name,
                               "project": _local_root_of( rel, reg.roots ) or f"{m.name}: {h.get( 'project' ) or '?'}",
                               "remote_project": h.get( "project" ) } )
        CHECKED[ m.name ] = only
        CHECKED_AT[ m.name ] = time.time()
        said.append( f"{m.name}: {len( only )} there only" if only else f"{m.name}: all here" )
    CHECKED_V[ 0 ] += 1
    return "checked: " + ", ".join( said ) if said else "no other machine watched to check"


def _local_root_of( rel: str, roots ) -> str | None:
    """the project here a run's path under `runs/` belongs to: the one that holds its file's directory already"""
    from ..agents import registry as G
    parts = rel.split( "/" )
    for cut in range( len( parts ) - 1, 0, -1 ):
        for root in roots:
            if ( G.runs_dir( root ) / "/".join( parts[ : cut ] ) ).is_dir():
                return root
    return None


def forget_there( m, leaves ):
    """runs removed on a machine: out of its history and of what the check found there, at once"""
    gone = set( leaves )
    if not gone:
        return
    if isinstance( getattr( m, "history", None ), dict ):
        m.history = { **m.history, "runs": [ r for r in m.history.get( "runs", [ ] ) if r.get( "leaf" ) not in gone ] }
    if m.name in CHECKED:
        CHECKED[ m.name ] = [ r for r in CHECKED[ m.name ] if r.get( "leaf" ) not in gone ]
        CHECKED_V[ 0 ] += 1


def bring_back( m, rec: dict ) -> str:
    """a run there only, brought here ( as `-o` brings a run's directory ): it joins this machine's record"""
    from ..agents import registry as G
    from ..layers import gateways as L
    target = getattr( m, "target", None ) or { }
    remote_root, local_root = rec.get( "remote_project" ), rec.get( "project" )
    if not ( target.get( "host" ) and remote_root and local_root and local_root.startswith( "/" ) ):
        raise ValueError( f"{rec.get( 'rel' )}: where it goes here is not known" )
    import os
    rel = os.path.relpath( rec[ "leaf" ], remote_root )
    L.fetch_view( rel, target[ "host" ], remote_root, Path( local_root ), target.get( "options" ) or ( ), say = lambda *_: None, dir = True )
    CHECKED[ m.name ] = [ r for r in CHECKED.get( m.name, [ ] ) if r.get( "leaf" ) != rec[ "leaf" ] ]
    CHECKED_V[ 0 ] += 1
    G.shared().refresh( force = True )
    return f"brought back: {Path( local_root ) / rel}"


_every: list = [ None, None ]


_recs: list = [ None, None ]          # ( the registry's version, its records )


def _records( reg ) -> list:
    if _recs[ 0 ] != ( id( reg ), reg.version ):
        _recs[ 0 ], _recs[ 1 ] = ( id( reg ), reg.version ), reg.records()
    return _recs[ 1 ]


_trees: dict = { }
_keep: list = [ ]


def tree_of( every: list ):
    """the runs' tree of these runs, built once for the same runs ( 70,000 of them: built again only when they change )"""
    from . import runtree as T
    key = id( every )                         # ( `record_runs` gives the same list for the same runs )
    got = _trees.get( key )
    if got is None:
        from ..agents import registry as G
        got = _trees[ key ] = T.build( every, G.shared().roots )
        _keep.append( every )                  # ( its id stays its own while the tree is kept )
        while len( _keep ) > 4:
            _keep.pop( 0 )
        while len( _trees ) > 4:
            _trees.pop( next( iter( _trees ) ) )
    return got


def key( row: Row ):
    """What a row stands for, kept across rebuilds: the cursor stays on it."""
    machine, what = row.data if isinstance( row.data, tuple ) else ( None, None )
    kind = row.kind
    if isinstance( what, dict ) and "tree" in what:
        return ( kind, machine, what[ "tree" ] )                 # a node of the runs' tree ( ADR 0023 )
    if isinstance( what, dict ):
        # a run by its leaf: the same whether it runs or is done -- the cursor stays on it as it ends
        what = what.get( "leaf" ) or what.get( "ident" ) or what.get( "id" ) or what.get( "name" )
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

    if row.kind in ( "cache", "cachefs", "centries", "centry" ):
        from . import caches
        return caches.facts( row )
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
        line( "machine", machine )                         # where it ran ( its files may be read here, ADR 0025 )
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
