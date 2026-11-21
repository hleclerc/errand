"""Every agent of this machine stopped, found by its directory: those of every errand ( older sources included ),
whether a hub holds a stream to them or not ( `errand agents stop`, `errand agents restart` ).

The hub stops what it has a stream to; an agent no hub reaches -- the host agent serving the page, an agent of older
sources, one whose hub is gone -- is found here, by its lock ( `table.served` ). Each is asked to go ( its `stop` ); one
of sources too old to know that op is sent a SIGTERM, its pid from its `ping`. One that runs something stays, unless
`force`: what runs goes with it then. On another machine, its agent of these sources does the same there ( `stop_here` ).
"""
from __future__ import annotations

import os
import signal
import time
from pathlib import Path

GONE_WITHIN = 10.0          # seconds an agent asked to go is given before it is said to be still there


def _order( d: Path ):
    """the deepest first: an environment's agent, an allocation's, then the host's ( what they run goes through it )"""
    return ( d.name.startswith( "host-" ), -len( d.parts ), d.name )


def _dirs( roots ) -> list:
    """the agents' directories under errand's per-user ones ( `agents/<name>`, `alloc/<name>/<job>`, `vm-agent` ): each
    holds its lock -- one that never started anything has no `proc/` ( `table.agent_dirs` wants one ). Not the hubs':
    they are asked first, and go once their agents have."""
    seen = [ ]
    for base in roots:
        for d in [ *base.glob( "agents/*" ), *base.glob( "alloc/*/*" ), base / "vm-agent" ]:
            if d.is_dir() and ( d / "lock" ).exists() and d not in seen:
                seen.append( d )
    return seen


def held_on( d: Path ) -> str | None:
    """the machine that holds the agent of `d`, when it said ( its `host` ) and it is not this one: a node sharing the
    file system, where its socket answers"""
    import socket
    try:
        host = ( d / "host" ).read_text().strip()
    except OSError:
        return None
    return host if host and host != socket.gethostname() else None


def sweep( match: str = "", force = False, spare = None, roots = None, only = None, hop = True ) -> list:
    """The agents here whose directory name holds `match`, asked to go: [ { "id", "how" } ], `how` starting with
    `left` for one left running ( no `force` ). `spare`: a directory left alone ( the agent doing this ). `only`: these
    directory names only. One held by another node of a shared file system is stopped there, over ssh ( `hop` )."""
    from . import table as T
    spare = Path( spare ).resolve() if spare else None
    dirs = [ d for d in _dirs( roots or T.roots() ) if match in d.name and d.resolve() != spare
             and ( only is None or d.name in only ) ]
    out, elsewhere = [ ], { }
    for d in sorted( dirs, key = _order ):
        if not T.served( d ):
            continue
        if ( host := held_on( d ) ) is not None:
            elsewhere.setdefault( host, [ ] ).append( d.name )
            continue
        how = _stop_one( d, force )
        if not how.startswith( ( "left", "unreachable" ) ):
            deadline = time.monotonic() + GONE_WITHIN
            while T.served( d ) and time.monotonic() < deadline:
                time.sleep( 0.1 )
            if T.served( d ):
                how += ", still there"
        out.append( { "id": d.name, "how": how } )
    for host, names in elsewhere.items():
        out += _hop( host, names, match, force ) if hop else \
            [ { "id": n, "how": f"unreachable: held on {host}" } for n in names ]
    return out


def _hop( host: str, names: list, match: str, force: bool ) -> list:
    """the agents `names` held on `host`, a node sharing this file system: stopped there by the same sweep, over ssh,
    with this errand's sources ( the same path there ) and this Python"""
    import json
    import shlex
    import subprocess
    import sys
    from ..bootstrap import PACKAGE
    req = json.dumps( { "match": match, "force": force, "only": names } )
    cmd = " ".join( shlex.quote( a ) for a in ( sys.executable, str( PACKAGE / "_boot.py" ), "-m", "errand.agents", "stop", req ) )
    try:
        got = subprocess.run( [ "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, cmd ],
                              capture_output = True, text = True, timeout = 180, stdin = subprocess.DEVNULL )
        line = next( l for l in got.stdout.splitlines() if l.startswith( "errand-stop " ) )
        said = json.loads( line[ len( "errand-stop " ) : ] )
    except Exception as err:
        why = ( got.stderr.strip().splitlines() or [ "" ] )[ -1 ] if "got" in locals() else f"{type( err ).__name__}: {err}"
        return [ { "id": n, "how": f"unreachable: on {host}, {why or 'it said nothing'}" } for n in names ]
    return [ { "id": f"{host}: {s[ 'id' ]}", "how": s[ "how" ] } for s in said ]


def _stop_one( d: Path, force: bool ) -> str:
    from . import ask_hub, table as T
    got = ask_hub( d, { "op": "stop", "force": force }, timeout = 15 )
    if got is not None and got.get( "ok" ):
        return "stopped"
    if got is not None and got.get( "running" ):
        return f"left: {got[ 'running' ]} running"
    # No answer to `stop`: an agent of sources older than that op. Its work said by its directory, its pid by `ping`.
    running = len( T.procs_of( d, True ) )
    if running and not force:
        return f"left: {running} running"
    pid = ( ask_hub( d, { "op": "ping" }, timeout = 10 ) or { } ).get( "pid" )
    if not pid:
        return "unreachable: it holds its lock and answers nothing ( on another node of a shared file system? )"
    try:
        os.kill( int( pid ), signal.SIGTERM )
    except OSError as err:
        return f"unreachable: {err}"
    return "stopped ( older sources: terminated )"


def remote( match: str = "", force = False, say = print ) -> int:
    """Every machine of the ledger ( watched or not: `errand status` leaves some aside, a stop must not ): on each, its agent of these sources
    stops the others there ( `stop_here` ), then goes. -> how many machines could not be reached."""
    from . import ledger, upstream as U
    failed = 0
    for rec in ledger.machines():
        target = rec.get( "target" ) or { }
        if target.get( "kind" ) != "ssh":         # ( every one: watched or not, to leave nothing behind )
            continue
        name = rec.get( "name" ) or target.get( "host" )
        try:
            conn = U.direct( target )                 # ( not through the hub: it was just stopped )
            try:
                call = conn.open( { "op": "stop_here", "match": match, "force": force } )
                got = call.reply( 120 )
                call.close()
                for s in got.get( "stopped" ) or [ ]:
                    say( f"{name}: {s[ 'id' ]}", s[ "how" ] )
                call = conn.open( { "op": "stop", "force": force } )
                got = call.reply( 30 )
                call.close()
                say( f"{name}: its agent", "stopped" if got.get( "ok" ) else f"left: {got.get( 'running' )} running" )
            finally:
                conn.close()
        except Exception as err:
            failed += 1
            say( f"{name}", f"unreachable: {type( err ).__name__}: {err}" )
    return failed
