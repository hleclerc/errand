"""`errand caches [MACHINE...] [--dry-run] [--unused DAYS]`: the library caches a machine holds ( ADR 0022 ), and
what ADR 0020's rules remove from them -- with `--unused`, also what has not served for DAYS days.

    errand caches               this machine
    errand caches lmo n22       machines of the ledger, by the names `errand machines` gives ( `here`: this one )
    errand caches hold MACHINE [DIR...]     MACHINE holds the cache directories it reaches ( or those named, by path or
                                id ): its host agent purges them once a day -- a cluster's login node, rather than the
                                compute node whose run made the directory

Removing on every machine at once is done in `errand tui` / `errand web`, where what goes is seen first.
"""
from __future__ import annotations

from pathlib import Path

from .. import caches as C, config
from .style import bad, dim, head, warn


def main( root: Path, words: list, dry_run = False, unused = None ) -> int:
    # The current project's directory is known to this machine's registry, even before a run used it.
    try:
        C.register( config.caches( root ).resolve(), "", root )
    except Exception:
        pass
    if words[ : 1 ] == [ "hold" ]:
        return hold( words[ 1 : ] )
    req = { "op": "caches", "purge": { "dry_run": bool( dry_run ), "unused_days": unused } }
    rc = 0
    for name, got, err in ask_all( words or [ "here" ], req ):
        print( head( name ) )
        if err:
            print( bad( f"  {err}" ) )
            rc = 1
            continue
        for line in lines( got, dry_run = dry_run, with_purge = True ):
            print( line )
    return rc


def hold( words ) -> int:
    """`errand caches hold MACHINE [DIR...]`."""
    if not words:
        print( bad( "errand caches hold MACHINE [DIR...]: which machine holds them ( `errand machines` names them )" ) )
        return 2
    try:
        m = machines_named( words[ : 1 ] )[ 0 ]
    except ValueError as err:
        print( bad( str( err ) ) )
        return 1
    rc = 0
    for d in words[ 1 : ] or [ None ]:
        try:
            got = m.ask( { "op": "caches_hold", "id": d }, timeout = 120 )
        except Exception as err:
            print( bad( f"  {m.name}: {str( err ).strip().splitlines()[ -1 ] if str( err ).strip() else type( err ).__name__}" ) )
            rc = 1
            continue
        for path, was in got.get( "held", [ ] ):
            print( f"  {path}: held by {m.name}" + dim( f" ( {got.get( 'host' )}; was {was or 'nobody'} )" ) )
    return rc


def machines_named( words ) -> list:
    """The machines named, as `errand tui` watches them ( `tui.machines.Machine` ). ValueError for a name nobody
    knows."""
    from ..tui.machines import Machine, watched
    known = watched()
    out = [ ]
    for w in words:
        m = next( ( m for m in known if ( m.here and w in ( "here", m.name ) ) or w in m.names ), None )
        if m is None:
            raise ValueError( f"{w}: no such machine ( `errand machines` lists them; `here` is this one )" )
        out.append( m )
    return out


def ask_all( words, req: dict, timeout = 600.0 ) -> list:
    """( name, answer, error ) for each machine named, asked at once."""
    import threading
    try:
        ms = machines_named( words )
    except ValueError as err:
        return [ ( "?", None, str( err ) ) ]
    got = [ None ] * len( ms )

    def one( i, m ):
        try:
            got[ i ] = ( m.name, m.ask( req, timeout = timeout ), None )
        except Exception as err:
            got[ i ] = ( m.name, None, str( err ).strip().splitlines()[ -1 ] if str( err ).strip() else type( err ).__name__ )

    threads = [ threading.Thread( target = one, args = ( i, m ), daemon = True ) for i, m in enumerate( ms ) ]
    for t in threads:
        t.start()
    for t in threads:
        t.join( timeout + 10 )
    return [ g or ( m.name, None, "did not answer" ) for g, m in zip( got, ms ) ]


def cache_line( c: dict ) -> str:
    """One cache: its entries, size, what is dead, what has not served for a while."""
    if c.get( "error" ):
        return f"{c[ 'name' ]}: " + bad( c[ "error" ] )
    said = f"{c[ 'name' ]}: {c[ 'entries' ]} entries, {C.human( c[ 'size' ] )}"
    if c.get( "dead" ):
        said += warn( f" · {c[ 'dead' ]} dead ( {C.human( c[ 'dead_size' ] )} )" )
    if c.get( "unused" ):
        said += dim( f" · {c[ 'unused' ]} unused ( {C.human( c[ 'unused_size' ] )} )" )
    if c.get( "journals" ):
        said += dim( f" · {c[ 'journals' ]} journals not merged" )
    return said


def lines( got: dict, dry_run = False, with_purge = False, indent = "  " ) -> list:
    """What a machine's `caches` answer says, one line per directory and cache."""
    out = [ ]
    dirs = got.get( "dirs" ) or [ ]
    if not dirs and not got.get( "guests" ):
        out.append( dim( f"{indent}no library cache seen here ( a run under errand writes its $ERRAND_CACHES down )" ) )
    for d in dirs:
        project = Path( d[ "project" ] ).name if d.get( "project" ) else ""
        held = "" if C.held_here( { "host": d.get( "host" ) } ) or not d.get( "host" ) else f"  held by {d[ 'host' ]}"
        out.append( f"{indent}{d[ 'path' ]}" + dim( f"  {project}{held}" ) )
        if not d.get( "caches" ):
            out.append( dim( f"{indent}  no cache kept by errand's rules" ) )
        for c in d.get( "caches", [ ] ):
            line = cache_line( c )
            done = c.get( "purged_now" )
            if with_purge and done is not None:
                line += dim( " -- " ) + ( f"{len( done[ 'removed' ] )} entries, {C.human( done[ 'freed' ] )} "
                                          f"{'would go' if dry_run else 'removed'}" if done[ "removed" ] else dim( "nothing to remove" ) )
            out.append( f"{indent}  {line}" )
    for g in got.get( "guests" ) or [ ]:
        out.append( f"{indent}windows {g[ 'vm' ][ : 8 ]}" )
        if g.get( "error" ):
            out.append( warn( f"{indent}  cannot say ( {g[ 'error' ]} )" ) )
        else:
            out += lines( g, dry_run = dry_run, with_purge = with_purge, indent = indent + "  " )
    return out
