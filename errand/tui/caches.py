"""The caches tab ( `3` ), shared by `errand tui` and `errand web` ( ADR 0022 ).

    ▾ loom                                        3 places · 2412 entries · 21.3 GB
        lmo = n22     1234 entries, 19.0 GB · 12 dead ( 1.0 GB ) · 300 unused ( 5.0 GB )
        mac           1178 entries, 2.3 GB
      ▸ entries: 312 dead or unused for 30 days somewhere

Each machine is asked for its caches ( the agent's `caches` op ) by a thread of its own, at most every
`EVERY` seconds while the tab is shown, with the entries of the caches whose entries are unfolded. A
directory two machines reach ( NFS ) is shown once, under the first. Removal goes through the machine that
holds the directory ( `caches_remove` ), under its compactor's lock; each asks first what it would do.
"""
from __future__ import annotations

import threading
import time

from .panes import Row

EVERY = 30.0               # seconds between askings of one machine, while the tab is shown
SHOWN = 400                # entries listed at most under one cache


def human( n: float ) -> str:
    from ..caches import human
    return human( n )


# ── asking ───────────────────────────────────────────────────────────────────

def want( machines, entries = (), days = 30, force = False ):
    """Each machine watched asked for its caches, in a thread, when what it said is older than `EVERY`, or was
    asked with other entries or another number of days."""
    asked = ( tuple( sorted( entries ) ), float( days ) )
    for m in machines:
        if getattr( m, "dormant", False ) or getattr( m, "caches_busy", False ):
            continue
        fresh = time.time() - getattr( m, "caches_at", 0.0 ) < EVERY
        if fresh and getattr( m, "caches_asked", None ) == asked and not force:
            continue
        m.caches_busy = True
        threading.Thread( target = _ask, args = ( m, asked ), daemon = True ).start()


def _ask( m, asked ):
    try:
        got = m.ask( { "op": "caches", "entries": list( asked[ 0 ] ), "days": asked[ 1 ] }, timeout = 180 )
        m.caches, m.caches_error = got, None
    except Exception as err:
        m.caches_error = str( err ).strip().splitlines()[ -1 ] if str( err ).strip() else type( err ).__name__
    finally:
        m.caches_at, m.caches_asked, m.caches_busy = time.time(), asked, False


def places( machines ) -> list:
    """Every cache directory the machines said, once each: { place, machine, guest, dir, also }. A directory said
    by two machines ( one id ) is the first one's, the others in `also`."""
    out, by_id = [ ], { }
    for m in machines:
        got = getattr( m, "caches", None )
        if not got:
            continue
        found = [ ( m.name, None, d ) for d in got.get( "dirs", [ ] ) ]
        found += [ ( f"{m.name} > windows {g[ 'vm' ][ : 8 ]}", g[ "vm" ], d )
                   for g in got.get( "guests", [ ] ) for d in g.get( "dirs", [ ] ) ]
        for place, guest, d in found:
            key = d.get( "id" ) or f"{place}:{d[ 'path' ]}"
            if key in by_id:
                by_id[ key ][ "also" ].append( place )
                continue
            by_id[ key ] = { "place": place, "machine": m, "guest": guest, "dir": d, "also": [ ] }
            out.append( by_id[ key ] )
    return out


def label( p: dict ) -> str:
    return " = ".join( [ p[ "place" ], *p[ "also" ] ] )


def _line( c: dict ) -> str:
    if c.get( "error" ):
        return f"cannot read: {c[ 'error' ]}"
    said = f"{c[ 'entries' ]} entries, {human( c[ 'size' ] )}"
    if c.get( "dead" ):
        said += f" · {c[ 'dead' ]} dead ( {human( c[ 'dead_size' ] )} )"
    if c.get( "unused" ):
        said += f" · {c[ 'unused' ]} unused ( {human( c[ 'unused_size' ] )} )"
    return said


# ── the rows ─────────────────────────────────────────────────────────────────

def rows( machines, *, folded = (), opened = (), query = "", days = 30, every = False ) -> list:
    """The caches tab: per cache name, a row per place, then its entries merged across places ( unfolded:
    `entries:<name>` in `opened` ), only those dead or unused somewhere unless `every`."""
    from .rows import ago
    ps = places( machines )
    names = { }
    for p in ps:
        for c in p[ "dir" ].get( "caches", [ ] ):
            names.setdefault( c[ "name" ], [ ] ).append( ( p, c ) )
    out = [ ]
    q = query.lower()
    for name in sorted( names ):
        held = [ ( p, c ) for p, c in names[ name ]
                 if not q or q in name.lower() or q in label( p ).lower() or q in str( p[ "dir" ].get( "project" ) or "" ).lower() ]
        if not held:
            continue
        is_open = ( "cache", name ) not in folded
        total = sum( c.get( "size", 0 ) for _, c in held )
        count = sum( c.get( "entries", 0 ) for _, c in held )
        out.append( Row( name, f"{len( held )} place{'s' if len( held ) > 1 else ''} · {count} entries · {human( total )}",
                         kind = "cache", data = ( None, { "ident": f"cache:{name}", "cache": name } ), open = is_open ) )
        if not is_open:
            continue
        for p, c in held:
            project = p[ "dir" ].get( "project" )
            shown = label( p ) + ( f"  {project.rsplit( '/', 1 )[ -1 ]}" if project else "" )
            out.append( Row( shown, _line( c ), kind = "cachefs", depth = 1,
                             mark = "dead" if c.get( "dead" ) else None,
                             data = ( p[ "machine" ].name, { "ident": f"{name}:{p[ 'dir' ].get( 'id' ) or p[ 'dir' ][ 'path' ]}",
                                                             "cache": name, "id": p[ "dir" ].get( "id" ) or p[ "dir" ][ "path" ],
                                                             "guest": p[ "guest" ], "place": label( p ), "dir": p[ "dir" ],
                                                             "summary": c } ) ) )
        merged = merge( held )
        flagged = [ k for k, at in merged.items() if any( e[ "dead" ] or e[ "unused" ] for _, e in at ) ]
        listed = every or ( f"entries:{name}" in opened )
        what = f"all {len( merged )}" if every else f"{len( flagged )} dead or unused for {days:g} days somewhere"
        entries_open = f"entries:{name}" in opened
        if not any( "list" in c for _, c in held ):
            what = "unfold to read them" if not entries_open else "reading…"
        out.append( Row( "entries", what, kind = "centries", depth = 1, open = entries_open,
                         data = ( None, { "ident": f"entries:{name}", "cache": name } ) ) )
        if not entries_open or not listed:
            continue
        keys = sorted( merged if every else flagged, key = lambda k: -max( e[ "size" ] for _, e in merged[ k ] ) )
        if q:
            keys = [ k for k in keys if q in k.lower() ] or keys
        now = time.time()
        for k in keys[ : SHOWN ]:
            at = merged[ k ]
            size = max( e[ "size" ] for _, e in at )
            from ..caches import seconds
            used = max( seconds( e.get( "used" ) ) for _, e in at )
            dead = [ label( p ) for p, e in at if e[ "dead" ] ]
            said = [ human( size ), f"used {ago( now - used )} ago" if used else "never used" ]
            if dead:
                said.append( "dead on " + ", ".join( dead ) )
            said.append( "on " + ", ".join( label( p ) for p, _ in at ) )
            out.append( Row( k, " · ".join( said ), kind = "centry", depth = 2, mark = "dead" if dead else None,
                             data = ( None, { "ident": f"{name}:{k}", "cache": name, "key": k,
                                              "at": [ { "machine": p[ "machine" ].name, "place": label( p ), "guest": p[ "guest" ],
                                                        "id": p[ "dir" ].get( "id" ) or p[ "dir" ][ "path" ], **e } for p, e in at ] } ) ) )
        if len( keys ) > SHOWN:
            out.append( Row( f"… {len( keys ) - SHOWN} more ( / filters them by name )", kind = "note", depth = 2 ) )
    if not out:
        asking = any( getattr( m, "caches", None ) is None and not getattr( m, "dormant", False ) and not getattr( m, "caches_error", None )
                      for m in machines )
        out.append( Row( "asking the machines for their caches…" if asking else
                         "no library cache seen: a run under errand writes its $ERRAND_CACHES down", kind = "note" ) )
    for m in machines:
        if getattr( m, "caches_error", None ):
            out.append( Row( f"{m.name}: cannot say", m.caches_error, kind = "broken", data = ( m.name, None ) ) )
    return out


def merge( held ) -> dict:
    """key -> [ ( place, entry ) ]: the entries of one cache over its places, from those that sent them."""
    out = { }
    for p, c in held:
        for k, e in ( c.get( "list" ) or { } ).items():
            out.setdefault( k, [ ] ).append( ( p, e ) )
    return out


def facts( row: Row ) -> list:
    """What the detail says of a row of this tab: ( name, value )."""
    from .rows import ago
    from ..caches import seconds
    _, what = row.data if isinstance( row.data, tuple ) else ( None, None )
    out = [ ]

    def line( k, v ):
        if v not in ( None, "", [ ] ):
            out.append( ( k, str( v ) ) )

    now = time.time()
    if row.kind == "cache":
        line( "cache", what[ "cache" ] )
        line( "keys", "on a place: i its dead entries, u those unused for n days; here: on every place" )
    elif row.kind == "centries":
        line( "keys", "v: every entry, or those dead or unused only · n: the days · d: removed where dead or unused, "
                      "D: everywhere" )
    elif row.kind == "cachefs":
        d, c = what[ "dir" ], what[ "summary" ]
        line( "place", what[ "place" ] )
        line( "path", f"{d[ 'path' ]}/{what[ 'cache' ]}" )
        line( "project", d.get( "project" ) )
        line( "held by", f"{d.get( 'host' )} ( h: this machine instead )" if d.get( "host" ) else "nobody ( h: this machine )" )
        line( "views", ", ".join( v or "the machine as it is" for v in c.get( "views", [ ] ) ) )
        line( "entries", f"{c.get( 'entries' )}, {human( c.get( 'size', 0 ) )}" )
        line( "dead", f"{c[ 'dead' ]}, {human( c[ 'dead_size' ] )} ( i removes them )" if c.get( "dead" ) else None )
        line( "unused", f"{c[ 'unused' ]}, {human( c[ 'unused_size' ] )} ( u removes them )" if c.get( "unused" ) else None )
        line( "journals", f"{c[ 'journals' ]} not merged yet" if c.get( "journals" ) else None )
        line( "purged", f"{ago( now - seconds( c[ 'purged' ] ) )} ago" if c.get( "purged" ) else "never" )
        line( "error", c.get( "error" ) )
    elif row.kind == "centry":
        line( "entry", what[ "key" ] )
        line( "cache", what[ "cache" ] )
        for a in what[ "at" ]:
            state = "dead" if a[ "dead" ] else "unused" if a[ "unused" ] else "alive"
            used = f"used {ago( now - seconds( a.get( 'used' ) ) )} ago" if a.get( "used" ) else "never used"
            line( a[ "place" ], f"{human( a[ 'size' ] )} · {state} · {used}"
                  + ( f" · built in {a[ 'cost_s' ]:.0f} s" if a.get( "cost_s" ) else "" )
                  + ( f" · seen from {a[ 'view' ]}" if a.get( "view" ) else "" ) )
        first = what[ "at" ][ 0 ]
        line( "shared", "yes: the entries that need it go with it" if first.get( "shared" ) else None )
        line( "needs", ", ".join( first.get( "needs" ) or [ ] ) )
    return out


# ── removing ─────────────────────────────────────────────────────────────────

class Removal:
    """What a key would remove: `title`, the `lines` of the confirmation, and ( machine, request, place ) to send."""

    def __init__( self, title, lines, reqs ):
        self.title, self.lines, self.reqs = title, lines, reqs


def plan( row: Row, how: str, machines, days = 30 ) -> Removal:
    """`how`: `dead`, `unused` ( on a place's row, or on every place on the cache's row ); `flagged` ( an entry,
    where it is dead or unused ), `everywhere` ( an entry, everywhere it is ). ValueError, said plainly, when it
    means nothing here."""
    if row is None or row.kind not in ( "cache", "cachefs", "centry" ):
        raise ValueError( "on a cache, a place of it, or one of its entries ( the caches tab, 3 )" )
    _, what = row.data
    by = { m.name: m for m in machines }
    if row.kind in ( "cache", "cachefs" ):
        if how not in ( "dead", "unused" ):
            raise ValueError( "i removes dead entries, u unused ones; d and D are for an entry" )
        held = [ ( p, c ) for p in places( machines ) for c in p[ "dir" ].get( "caches", [ ] ) if c[ "name" ] == what[ "cache" ] ]
        if row.kind == "cachefs":
            held = [ ( p, c ) for p, c in held if ( p[ "dir" ].get( "id" ) or p[ "dir" ][ "path" ] ) == what[ "id" ] ]
        n = sum( c.get( how, 0 ) for _, c in held )
        size = sum( c.get( f"{how}_size", 0 ) for _, c in held )
        if not n:
            raise ValueError( f"nothing {'dead' if how == 'dead' else f'unused for {days:g} days'} in {what[ 'cache' ]}"
                              + ( f" on {what[ 'place' ]}" if row.kind == "cachefs" else "" ) )
        reqs = [ ( p[ "machine" ], { "op": "caches_remove", "id": p[ "dir" ].get( "id" ) or p[ "dir" ][ "path" ],
                                     "cache": what[ "cache" ], "rule": how, "days": days, "guest": p[ "guest" ] }, label( p ) )
                 for p, c in held if c.get( how ) ]
        said = "dead" if how == "dead" else f"not used for {days:g} days"
        lines = [ f"{label( p )}: {c[ how ]} entries, {human( c[ f'{how}_size' ] )}" for p, c in held if c.get( how ) ]
        lines.append( "and the shared entries nothing needs any more" )
        return Removal( f"remove {n} {what[ 'cache' ]} entries {said} ( {human( size )} )?", lines, reqs )
    if how not in ( "flagged", "everywhere" ):
        raise ValueError( "on an entry: d removes it where it is dead or unused, D everywhere" )
    at = [ a for a in what[ "at" ] if how == "everywhere" or a[ "dead" ] or a[ "unused" ] ]
    if not at:
        raise ValueError( "alive everywhere: D removes it all the same" )
    reqs = [ ( by[ a[ "machine" ] ], { "op": "caches_remove", "id": a[ "id" ], "cache": what[ "cache" ],
                                       "keys": [ what[ "key" ] ], "guest": a[ "guest" ] }, a[ "place" ] )
             for a in at if a[ "machine" ] in by ]
    lines = [ f"{a[ 'place' ]}: {human( a[ 'size' ] )}" + ( " ( dead )" if a[ "dead" ] else " ( unused )" if a[ "unused" ] else "" )
              for a in at ]
    if at[ 0 ].get( "shared" ):
        lines.append( "shared: the entries that need it go with it" )
    return Removal( f"remove {what[ 'key' ]} from {len( at )} place{'s' if len( at ) > 1 else ''}?", lines, reqs )


def hold_plan( row: Row, machines ) -> Removal:
    """`h` on a place: the machine of the row holds that directory, its host agent purges it ( ADR 0022 )."""
    if row is None or row.kind != "cachefs":
        raise ValueError( "h: on a place of a cache, to say which machine purges it" )
    _, what = row.data
    m = next( ( m for m in machines if m.name == row.data[ 0 ] ), None )
    if m is None or what.get( "guest" ):
        raise ValueError( "a guest holds its own caches" )
    d = what[ "dir" ]
    lines = [ f"{d[ 'path' ]}: held by {d.get( 'host' ) or 'nobody'} now",
              f"its host agent on {m.name} purges it once a day ( ADR 0020's rules )" ]
    also = [ p for p in places( machines ) if ( p[ "dir" ].get( "id" ) or p[ "dir" ][ "path" ] ) == what[ "id" ] and p[ "also" ] ]
    if also:
        lines.append( f"also reached by {', '.join( also[ 0 ][ 'also' ] )}: `errand caches hold NAME` picks another" )
    return Removal( f"{m.name} holds {d[ 'path' ]}?", lines,
                    [ ( m, { "op": "caches_hold", "id": what[ "id" ] }, what[ "place" ] ) ] )


def send( r: Removal ) -> str:
    """The removal done, place by place -> what to say of it."""
    removed, freed, failed = 0, 0, [ ]
    for m, req, place in r.reqs:
        try:
            got = m.ask( { k: v for k, v in req.items() if v is not None }, timeout = 300 )
            if req[ "op" ] == "caches_hold":
                m.caches_at = 0.0
                return f"{place}: held by {m.name} ( {got.get( 'host' )} ), its host agent purges it"
            removed += len( got.get( "removed", [ ] ) )
            freed += got.get( "freed", 0 )
        except Exception as err:
            failed.append( f"{place}: {str( err ).strip().splitlines()[ -1 ] if str( err ).strip() else type( err ).__name__}" )
        m.caches_at = 0.0                       # read again at once
    return f"{removed} entries removed, {human( freed )} freed" + ( f" · could not: {failed[ 0 ]}" if failed else "" )
