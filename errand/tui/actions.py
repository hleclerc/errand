"""What a key of `errand tui`, or a button of `errand web`, does to the machines: kill, forget, watch,
rename. Both ask first what they would do ( `kill_plan`: what a window of confirmation says ), then do it.
"""
from __future__ import annotations

from typing import NamedTuple

from . import rows as R


class Plan( NamedTuple ):
    """What a kill would do: `title`, the `lines` of what it touches, the requests to send to `machine`."""
    title   : str
    lines   : list
    machine : object
    reqs    : list                  # ( request, what to call it )


def kill_plan( row, m ) -> Plan:
    """What `k` on `row` kills: on a machine's row, everything errand runs there ( its runs, its agents,
    its VMs ); else the process or the VM's keeper. ValueError, said plainly, when nothing can be."""
    if row is not None and row.kind in ( "machine", "broken" ):
        procs = [ p for p in ( m.table or { } ).get( "procs", [ ] ) if p.get( "pgid" ) ]
        if not procs:
            raise ValueError( f"nothing of errand's runs on {m.name}" + ( "" if m.table else " ( not read yet )" ) )
        reqs = [ ( { "op": "kill", "pgid": p[ "pgid" ], "since": p.get( "since" ), "mark": p.get( "mark" ) },
                   f"{R.project_of( p )} {p.get( 'what' ) or ''}".strip() ) for p in procs ]
        shown = [ said for _, said in reqs[ : 12 ] ] + ( [ f"… and {len( reqs ) - 12} more" ] if len( reqs ) > 12 else [ ] )
        return Plan( f"kill everything errand runs on {m.name}? {len( reqs )} process group" + ( "s" if len( reqs ) > 1 else "" ),
                     shown, m, reqs )
    req, said = R.stop_request( row, m )
    return Plan( f"kill {said}?", [ "INT, then TERM, then KILL, to its whole process group" ], m, [ ( req, said ) ] )


def send( plan: Plan ) -> str:
    """The kill done -> what to say of it."""
    m, failed = plan.machine, [ ]
    for req, said in plan.reqs:
        try:
            m.ask( req, timeout = 30 )
        except Exception as err:
            failed.append( f"{said}: {err}" )
    m.wake.set()
    return ( f"killing {len( plan.reqs ) - len( failed )} on {m.name}: INT, then TERM, then KILL"
             + ( f" · could not: {failed[ 0 ]}" if failed else "" ) )


def forget_lines( m ) -> list:
    return [ "errand stops asking it what runs there, until work is sent there again",
             "nothing stops over there: k on its row kills what runs" ]


def forget( m, machines: list ) -> str:
    """`m` not asked any more ( `ledger.forget` ), out of `machines`, until work is sent there again."""
    from ..agents import ledger
    if m.here:
        raise ValueError( "this machine is always shown: nothing to forget" )
    for n in m.names:
        ledger.forget( n )
    m.stopped = True
    m.wake.set()
    if m in machines:
        machines.remove( m )
    return f"{m.name} forgotten: not asked any more, until work is sent there again"


def toggle_watch( m ) -> str:
    """`m` contacted or not, from now on -- saved, `errand status` follows it ( `ledger.set_watch` )."""
    from ..agents import ledger
    if m.here:
        raise ValueError( "this machine is always watched" )
    if m.dormant:
        ledger.set_watch( m.names[ 0 ], True )
        m.watch_set = True
        m.activate()
        return f"watching {m.name}, from now on"
    ledger.set_watch( m.names[ 0 ], False )
    m.watch_set = False
    m.deactivate()
    return f"{m.name} is not watched any more ( a again, or work sent there, watches it )"


def rename( m, label: str ) -> str:
    """`m` shown as `label`, every name it is reached by alike; this machine too ( its hostname until then )."""
    from ..agents import ledger
    label = label.strip()
    if not label or label == m.name:
        return "nothing done"
    if m.here:
        ledger.rename_here( label )
        said = f"this machine is shown as {label}"
    else:
        ledger.rename( m.names[ 0 ], label )
        said = f"{m.name} is shown as {label}" + ( f" ( reached as {', '.join( m.names )} )" if len( m.names ) > 1 else "" )
    m.name = label
    return said


def rename_title( m ) -> str:
    reached = "this machine" if m.here else ", ".join( m.names ) if len( m.names ) > 1 else ""
    return f"name {m.name}" + ( f" ( {reached} )" if reached else "" )
