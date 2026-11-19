"""Runs removed by hand ( ADR 0023, 0025 ): `d` removes the runs under a row of the runs' tree, `D` keeps only the
latest of each parameter set, environment and machine ( and its last PASS ). For good: each run's directory here ( the
record of the runs started from this machine ), and, for a run that ran on another machine, its directory there, through
that machine's agent ( `runs_remove` `rels`: found by its path under `runs/` among what it noted, never anything else ).
A run the check found there only ( `there` ) has no directory here: there only.

In two times, so that a window answers at once: `plan( rows, machines, how )` says what goes and where, asking nobody
( what is listed is what goes ); `measure( plan )` then the room freed ( a `du` here and on each machine ), filling the
window shown. `send( plan )` does it, its runs greyed meanwhile ( `runtree.GOING` ), and says what could not be ( a
machine that does not answer: here goes, there stays, and the check finds it ). Shared by `errand tui` and `errand web`.
"""
from __future__ import annotations

import shutil
import threading
from pathlib import Path

from . import runtree as T

HOW = ( "all", "latest" )


class Plan:
    def __init__( self, title, lines, here, there, how, going, name = "" ):
        self.title, self.lines, self.how, self.name = title, lines, how, name
        self.here  = list( here )          # the run directories here
        self.there = dict( there )         # machine name -> ( machine, [ paths under `runs/` ] )
        self.going = list( going )         # ( machine name, leaf ): the rows greyed

    @property
    def count( self ) -> int:
        return len( self.going )


def history( machines ) -> list:
    """every run the runs tab lists, `( machine, record, running )`: this machine's record ( ADR 0025 ), and what the
    check found elsewhere only"""
    from . import rows as R
    return R.record_runs( machines, running( machines ) )


def running( machines ) -> set:
    """the paths under `runs/` of what runs or waits"""
    from . import rows as R
    return { x for m in machines for p in ( m.table or { } ).get( "procs", [ ] ) if p.get( "leaf" )
             for x in ( R.rel_of( p[ "leaf" ] ), p[ "leaf" ] ) if x }


def _size( n: int ) -> str:
    for unit in ( "B", "kB", "MB", "GB" ):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000


def _runs_s( n: int ) -> str:
    return f"{n} run{'s' if n != 1 else ''}"


def _under( row, runs ) -> tuple:
    """-> ( the runs under one row, what to call it )"""
    what = row.data[ 1 ] if row is not None and isinstance( row.data, tuple ) else None
    if row is not None and row.kind == "run" and isinstance( what, dict ):
        return [ x for x in runs if x[ 1 ].get( "leaf" ) == what.get( "leaf" ) ], what.get( "what" ) or "this run"
    if row is not None and row.kind in ( "tnode", "tset", "thead" ) and isinstance( what, dict ):
        from . import rows as R
        node = T.find( R.tree_of( runs ), what[ "tree" ] )
        if node is None:
            raise ValueError( "not there any more" )
        return T.all_runs( node ), row.label.strip() if row.kind == "tnode" else "this parameter set" if row.kind == "tset" else "this table"
    raise ValueError( "d / D: on a run, or a row of the runs' tree" )


def plan( rows, machines, how: str ) -> Plan:
    """what `d` ( how = "all" ) or `D` ( "latest" ) removes under `rows` ( a row, or the rows chosen together );
    ValueError when there is nothing. Quick: nobody is asked."""
    if how not in HOW:
        raise ValueError( f"remove: {how!r}, not one of {HOW}" )
    from . import rows as R
    rows = [ rows ] if not isinstance( rows, ( list, tuple ) ) else [ r for r in rows if r is not None ]
    runs = history( machines )
    under, seen, names = [ ], set(), [ ]
    for row in rows:
        got, name = _under( row, runs )
        names.append( name )
        for x in got:
            k = ( x[ 0 ].name, x[ 1 ].get( "leaf" ) )
            if k not in seen:
                seen.add( k )
                under.append( x )
    name = names[ 0 ] if len( names ) == 1 else f"{len( names )} rows"
    going = T.keep_latest( under ) if how == "latest" else [ x for x in under if not x[ 2 ] ]
    if not going:
        raise ValueError( "nothing to remove here" + ( ": only the latest runs are left" if how == "latest" else "" ) )
    here, there, elsewhere = [ ], { }, set()
    for m, r, _ in going:
        if not r.get( "there" ):
            here.append( r[ "leaf" ] )
        if isinstance( m, R.Elsewhere ):
            elsewhere.add( m.name )
        elif not getattr( m, "here", False ) and r.get( "rel" ):
            there.setdefault( m.name, ( m, [ ] ) )[ 1 ].append( r[ "rel" ] )
    lines = ( [ f"here: {_runs_s( len( here ) )}, …" ] if here else [ ] ) + \
            [ f"{n}: {_runs_s( len( rels ) )} there too, …" for n, ( m, rels ) in there.items() ] + \
            ( [ f"ran on {', '.join( sorted( elsewhere ) )}: no agent errand knows of there, the copies here only" ] if elsewhere else [ ] ) + \
            [ "for good: nothing to undo ( the room freed: being measured )" ]
    count = len( going )
    title = ( f"keep only the latest of {name}: remove {count} older run{'s' if count != 1 else ''}?" if how == "latest"
              else f"remove {_runs_s( count )} of {name}?" )
    return Plan( title, lines, here, there, how, [ ( m.name, r[ "leaf" ] ) for m, r, _ in going ], name )


def measure( p: Plan ) -> list:
    """the lines of `p` with the room freed: here ( `du` ), and on each machine ( its agent, `dry` ); a machine that does
    not answer said so. Slow: asked once the window is shown."""
    from ..agents import look
    lines, total, asked = [ ], 0, { }
    asking = threading.Thread( target = lambda: asked.update(
        _each( p.there, lambda m, rels: m.ask( { "op": "runs_remove", "rels": rels, "dry": True }, timeout = 300 ) ) ), daemon = True )
    asking.start()
    if p.here:
        room = sum( look._sizes( [ l for l in p.here if Path( l ).is_dir() ], _walk_size ).values() )
        total += room
        lines.append( f"here: {_runs_s( len( p.here ) )}, {_size( room )}" )
    asking.join()
    for mname, ( m, rels ) in p.there.items():
        got = asked.get( mname )
        if isinstance( got, Exception ) or got is None:
            lines.append( f"{mname}: cannot be reached now ( {got} ): its {_runs_s( len( rels ) )} stay there, the check will find them" )
            continue
        sizes = got.get( "sizes" ) or { }
        room = sum( sizes.values() )
        total += room
        lines.append( f"{mname}: {_runs_s( len( sizes ) )} there too, {_size( room )}"
                      + ( f" ( {len( rels ) - len( sizes )} already gone there )" if len( sizes ) < len( rels ) else "" ) )
    lines.append( f"for good: {_size( total )} freed, nothing to undo" )
    p.lines[ : ] = lines                               # ( the same list: a window that shows it shows the sizes )
    return lines


def _walk_size( path: Path ) -> int:
    total = 0
    for f in path.rglob( "*" ):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def mark( p: Plan ):
    """the runs of `p` shown greyed, from now until `send` is done"""
    T.GOING.update( p.going )


def _each( by_machine: dict, ask ) -> dict:
    """`ask( machine, what )` for every machine at once ( threads ): -> { name: its answer, or the exception }"""
    out = { }

    def one( name, m, what ):
        try:
            got = ask( m, what )
            if isinstance( got, dict ) and got.get( "error" ):
                raise RuntimeError( got[ "error" ] )
            out[ name ] = got
        except Exception as err:
            out[ name ] = err
    ts = [ threading.Thread( target = one, args = ( n, m, w ), daemon = True ) for n, ( m, w ) in by_machine.items() ]
    for t in ts:
        t.start()
    for t in ts:
        t.join( 900 )
    return out


def _remove_here( leaf: str ) -> bool:
    path = Path( leaf )
    latest = path.parent / "latest"
    try:
        if latest.is_symlink() and latest.resolve() == path.resolve():
            latest.unlink()
    except OSError:
        pass
    shutil.rmtree( path, ignore_errors = True )
    return not path.exists()


def send( p: Plan ) -> str:
    """the plan done: what was removed, what was not and why. Its runs greyed meanwhile; those removed leave the record
    at once; the others are shown again as they were"""
    from ..agents import registry as G
    from . import rows as R
    said, gone_here, there_n = [ ], [ ], 0
    mark( p )
    try:
        done: dict = { }
        asking = threading.Thread( target = lambda: done.update(
            _each( p.there, lambda m, rels: m.ask( { "op": "runs_remove", "rels": rels }, timeout = 900 ) ) ), daemon = True )
        asking.start()
        for leaf in p.here:
            if _remove_here( leaf ):
                gone_here.append( leaf )
            else:
                said.append( f"{Path( leaf ).name}: could not be removed here" )
        asking.join()
        G.shared().forget( gone_here )
        for mname, ( m, rels ) in p.there.items():
            got = done.get( mname, RuntimeError( "no answer" ) )
            if isinstance( got, Exception ):
                said.append( f"{mname}: not reached, its runs stay there ( {got} ); the check will find them" )
                continue
            removed = got.get( "removed" ) or [ ]
            there_n += len( removed )
            for leaf, why in got.get( "kept" ) or [ ]:
                said.append( f"{mname}: {Path( leaf ).name} kept there ( {why} )" )
            R.forget_there( m, removed )
    finally:
        T.GOING.difference_update( p.going )
    head = f"{_runs_s( len( gone_here ) )} removed here" + ( f", {there_n} on other machines" if p.there else "" )
    return head + ( "; " + "; ".join( said[ : 3 ] ) + ( f" ( +{len( said ) - 3} more )" if len( said ) > 3 else "" ) if said else "" )
