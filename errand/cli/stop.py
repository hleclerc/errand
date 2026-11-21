"""`errand stop ID...`: what errand runs, stopped by the id `errand status` shows -- running, or waiting in a
machine's queue --, on this machine or on any machine work was sent to.

    errand stop 6575aafc            that one ( a prefix of the id is enough, when it says only one )
    errand stop 6575aafc 0c1d2e3f   several, wherever each runs
    errand stop b558                a --batch submission, by the id it was given: wherever it was let go
    errand stop --mine              everything this project runs, on every machine
    errand stop                     at a terminal: what runs or waits everywhere, numbered, and which to stop

Each is found in what its machine says runs there ( `standing.tables`, as `errand status` reads it ), then
stopped by its owner, as `k` in `errand tui` does ( `look.kill` ): INT, TERM after 2 s, KILL after 5 s, then
what it said must happen when it stops ( its `cancel` ). A run waiting for room in a machine's queue is a
process like another: once it is gone, its place in the queue goes with it, and what waited behind it moves up.

A `--batch` submission ( `errand status`'s last part ) was let go by its handle, not given to an agent: its
session's group here, its `nohup`'s group over ssh ( INT, TERM, KILL, as above ), its job for a batch system
( `scancel` ). Its record stays, with what it wrote: `errand forget ID` drops it.
"""
from __future__ import annotations

from pathlib import Path

from .style import bad, dim, good, warn

SHORTEST = 4            # characters of an id below which a prefix is not taken: too many would match


def _rows( got ) -> list:
    """Every process of every machine that answered, with where it runs ( `standing._rows`: guests and
    allocation nodes under their machine, `_stoppable` says why those are not stopped from here )."""
    from .standing import _rows as rows
    return [ r for machine, table, _ in got if table is not None for r in rows( machine, table ) ]


def _stoppable( r ) -> str | None:
    """Why `r` cannot be stopped from here, or None."""
    if " > windows " in r[ "machine" ]:
        return "a process of a windows guest: it stops from its command ( or stop its vm: errand vm stop )"
    if " > " in r[ "machine" ]:
        return f"it runs on a node of an allocation ( {r[ 'machine' ]} ): errand agents stop, or its slurm job"
    if not r.get( "pgid" ):
        return "no process group recorded for it"
    return None


def find( words: list, rows: list ) -> tuple:
    """-> ( the rows named, what to say of each word that named none or several )."""
    picked, said = [ ], [ ]
    for w in words:
        hits = [ r for r in rows if str( r[ "id" ] ).startswith( w ) ]
        if not hits:
            said.append( f"{w}: nothing of errand's runs under that id ( errand status lists them )" )
        elif len( hits ) > 1:
            said.append( f"{w}: names {len( hits )} processes ( "
                         + ", ".join( f"{h[ 'id' ][ : 12 ]} on {h[ 'machine' ]}" for h in hits[ : 4 ] )
                         + " ): give more of the id" )
        else:
            picked += [ h for h in hits if h not in picked ]
    return picked, said


def _targets( ) -> dict:
    """The machines of the ledger, by the name `tables` gives them -> how their agent is reached."""
    from ..agents import ledger
    return { r[ "name" ]: r[ "target" ] for r in ledger.groups() if r.get( "target" ) }


def send( machine: str, req: dict, here: str, targets: dict ) -> dict:
    """The `kill` asked of the machine's agent, done before the answer comes ( `wait` ). This machine: here,
    by this command. Another: through its agent, as the screen asks it ( `tui.machines.Machine.ask` )."""
    from ..agents import look
    req = { **req, "op": "kill", "wait": True }
    if machine == here:
        got = look.answer( req )
    else:
        target = targets.get( machine )
        if target is None:
            raise RuntimeError( f"{machine} is not in the machines errand reaches any more" )
        from .. import agents
        call = agents.open( target, noted = False ).open( req )       # stopping is no work sent there
        try:
            got = call.reply( 120 )
        finally:
            call.close()
    if got.get( "error" ):
        raise RuntimeError( got[ "error" ] )
    return got


ESCALATE = ( 'pg=$( ps -o pgid= -p {h} 2>/dev/null | tr -d " " ); [ -n "$pg" ] || exit 3; '
             'for s in INT TERM KILL; do kill -$s -- -$pg 2>/dev/null || exit 0; i=0; '
             'while [ $i -lt 20 ] && kill -0 -- -$pg 2>/dev/null; do sleep 0.25; i=$((i+1)); done; done; '
             'kill -0 -- -$pg 2>/dev/null && exit 4; exit 0' )


def stop_place( place: dict ) -> str:
    """One place of a `--batch` submission stopped by its handle -> what to say; raises what went wrong."""
    import subprocess
    from .. import batch
    kind, handle = place.get( "kind" ), str( place.get( "handle" ) or "" )
    if not handle.isdigit():
        raise RuntimeError( "no handle recorded: nothing to stop" )
    if kind == "batch":
        line = f"scancel {handle}"
    elif kind in ( "local", "ssh" ):
        line = ESCALATE.format( h = handle )
    else:
        raise RuntimeError( f"a {kind} handle is not stopped from here" )
    if place.get( "host" ):
        got = batch._remote( place, line )
    else:
        got = subprocess.run( [ "sh", "-c", line ], capture_output = True, text = True, timeout = 60 )
    if got.returncode == 3:
        return "was not running any more"
    if got.returncode == 4:
        raise RuntimeError( "killed, and still there" )
    if got.returncode:
        raise RuntimeError( ( got.stderr or got.stdout or "" ).strip()[ -300 : ] or f"exit {got.returncode}" )
    return "job cancelled" if kind == "batch" else "stopped"


def stop_batches( root: Path, records: list ) -> int:
    rc = 0
    for record in records:
        for place in record.get( "places", [ ] ):
            where = f"{record[ 'id' ]}  {place.get( 'env' )} on {place.get( 'host' ) or 'this machine'}"
            try:
                print( good( f"  {where}: {stop_place( place )}" ) + dim( f"   ( {place.get( 'kind' )} {place.get( 'handle' )} )" ) )
            except Exception as err:
                print( bad( f"  {where}: could not stop it: {err}" ) )
                rc = 1
    if records:
        print( dim( f"  its record stays, with what it wrote: errand forget {records[ 0 ][ 'id' ]} drops it" ) )
    return rc


def _work( rows: list ) -> list:
    """What a person would stop: runs and what waits, not the agents kept warm, the VMs or a service's keeper
    ( as `errand status` sorts them )."""
    return [ r for r in rows if r.get( "kind" ) != "agent" and not r.get( "vm" )
             and "errand.serve keep" not in str( r.get( "what" ) ) ]


def parse_choice( text: str, count: int ) -> list:
    """`1 3`, `1,3`, `2-4`, `all` -> the indices chosen ( from 0 ); ValueError for anything else."""
    text = text.strip().lower()
    if text in ( "all", "*" ):
        return list( range( count ) )
    out = [ ]
    for part in text.replace( ",", " " ).split():
        a, sep, b = part.partition( "-" )
        lo, hi = ( int( a ), int( b ) ) if sep else ( int( a ), int( a ) )
        if not 1 <= lo <= hi <= count:
            raise ValueError( f"{part}: between 1 and {count}" )
        out += [ i - 1 for i in range( lo, hi + 1 ) if i - 1 not in out ]
    return out


def choose( root: Path, got, ask = input ) -> list:
    """`errand stop` alone, at a terminal: what runs or waits everywhere ( this project first ), and the
    `--batch` submissions not over, numbered -> the ids chosen ( [ ] for none )."""
    from .. import batch
    from . import standing as S
    mine = S._project_names( root )
    rows = sorted( _work( _rows( got ) ), key = lambda r: ( Path( str( r.get( "project" ) or "?" ) ).name not in mine,
                                                           Path( str( r.get( "project" ) or "?" ) ).name, r[ "machine" ], -r[ "age" ] ) )
    records = [ r for r in batch.load_all( root ) if not r.get( "settled" ) ]
    if not rows and not records:
        print( dim( f"  nothing runs or waits on {', '.join( m for m, t, _ in got if t is not None )}" ) )
        return [ ]
    ids, n = [ ], 0
    for r in rows:
        n += 1
        ident = r[ "id" ] if str( r[ "id" ] ).startswith( "pgid" ) else r[ "id" ][ : 8 ]
        project = Path( str( r.get( "project" ) or "?" ) ).name
        print( f"  {n:>2}  {r[ 'machine' ]:<10} {ident}  {project}  {r.get( 'what' ) or ''}  "
               + dim( f"{S._ago( r[ 'age' ] )}  " ) + S._state_of( r, r.get( "now" ) ) )
        ids.append( r[ "id" ] )
    for rec in records:
        n += 1
        where = ", ".join( f"{p.get( 'env' )} on {p.get( 'host' ) or 'this machine'}" for p in rec.get( "places", [ ] ) )
        print( f"  {n:>2}  {rec[ 'id' ]}  --batch {rec.get( 'command' ) or ''}  " + dim( f"{rec.get( 'when' )}  {where}" ) )
        ids.append( rec[ "id" ] )
    while True:
        try:
            text = ask( "  stop which? ( 1 3, 2-4, all; Enter: none ) " )
        except ( EOFError, KeyboardInterrupt ):
            print()
            return [ ]
        if not text.strip():
            return [ ]
        try:
            return [ ids[ i ] for i in parse_choice( text, len( ids ) ) ]
        except ValueError as err:
            print( bad( f"  {err}" ) )


def main( root: Path, words: list, mine = False, got = None, sender = None, ask = None ) -> int:
    """`errand stop ID...` / `errand stop --mine` / `errand stop` alone, at a terminal: chosen in a list.
    `got`: what `standing.tables` answers, when already read; `sender`: how a `kill` is sent; `ask`: how
    the choice is read ( tests ). -> 0 when every one named was stopped."""
    import sys
    from ..agents import ledger
    from . import standing as S
    if not words and not mine:
        if ask is None and not ( sys.stdin.isatty() and sys.stdout.isatty() ):
            print( bad( "errand stop: which? errand stop ID... ( the ids errand status shows ), or errand stop --mine" ) )
            return 2
        got = S.tables() if got is None else got
        words = choose( root, got, ask or input )
        if not words:
            return 0
    if words and mine:
        print( bad( "errand stop: ids, or --mine, not both" ) )
        return 2
    short = [ w for w in words if len( w ) < SHORTEST and not w.startswith( "pgid-" ) ]
    if short:
        print( bad( f"errand stop: {short[ 0 ]} is too short: give at least {SHORTEST} characters of the id" ) )
        return 2
    from .. import batch
    records = { r[ "id" ]: r for r in batch.load_all( root ) } if words else { }
    launched = [ records[ w ] for w in words if w in records ]
    words = [ w for w in words if w not in records ]
    rc = stop_batches( root, launched )
    if not words and not mine:
        return rc
    got = S.tables() if got is None else got
    rows = _rows( got )
    if mine:
        names = S._project_names( root )
        picked = [ r for r in _work( rows ) if Path( str( r.get( "project" ) or "" ) ).name in names ]
        said = [ ] if picked else [ f"nothing of {root.name} runs on {', '.join( m for m, t, _ in got if t is not None )}" ]
    else:
        picked, said = find( words, rows )
    rc = rc or ( 1 if said and not mine else 0 )
    for machine, table, error in got:
        if table is None and ( mine or said ):
            said.append( f"{machine}: could not be asked ( {error} ): what runs there is not known" )
    here = ledger.here_name()
    targets = { } if all( r[ "machine" ] == here for r in picked ) else _targets()
    sender = sender or ( lambda machine, req: send( machine, req, here, targets ) )
    for r in picked:
        name = f"{str( r[ 'id' ] )[ : 8 ] if not str( r[ 'id' ] ).startswith( 'pgid' ) else r[ 'id' ]}  {r.get( 'what' ) or ''}".rstrip()
        why = _stoppable( r )
        if why:
            print( bad( f"  {name} on {r[ 'machine' ]}: cannot be stopped from here: {why}" ) )
            rc = 1
            continue
        was = f"was waiting: {r[ 'waiting' ].get( 'what' )}" if r.get( "waiting" ) else "was running"
        try:
            ans = sender( r[ "machine" ], { "pgid": r[ "pgid" ], "since": r.get( "since" ), "mark": r.get( "mark" ) } )
        except Exception as err:
            print( bad( f"  {name} on {r[ 'machine' ]}: could not stop it: {err}" ) )
            rc = 1
            continue
        if ans.get( "gone", True ):
            print( good( f"  {name} on {r[ 'machine' ]}: stopped" ) + dim( f"   ( {was} )" ) )
        else:
            print( warn( f"  {name} on {r[ 'machine' ]}: killed, and still there" ) + dim( f"   ( {was} )" ) )
            rc = 1
    for s in said:
        print( bad( f"  {s}" ) if not s.startswith( "nothing of" ) else dim( f"  {s}" ) )
    return rc
