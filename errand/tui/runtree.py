"""The runs as a tree ( ADR 0023 ), for `errand tui` and `errand web` alike: the directories of the file's path, the
file, the entry, its parameter sets as a table ( one line a set, a column a parameter, then its results, the status,
date and duration of its last run, how many ), and their runs.

A node is folded until opened ( `opened` holds `t:<id>` ), but one that holds a run running or waiting is open until
folded ( `folded` holds `t:<id>` ). The sort of an entry's table is in `opened` too: `s:<entry id>=<column>`, `=-` the
other way. The list is monospaced in both views: the table is text, aligned.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from .panes import Row

_PARAM = re.compile( r"\s([A-Za-z_][\w.]*)=(\S*)" )
OUT = ( "/errand-outputs/runs/", "/runs/" )


def rel_file( r: dict ) -> str:
    """the file's path from the project's root, read from the run's directory: `<outputs>/runs/<file>/<entry>/<run>`, or
    `<outputs>/runs/<file>/<run>` for a file run as a whole ( `sh x.sh`, `python foo.py`: no entry level ), told apart
    by the file's name ( its record's `file`, else `what`'s `<file>::` )"""
    leaf = str( r.get( "leaf" ) or "" )
    what = r.get( "what" ) or ""
    base = str( r.get( "file" ) or "" ).replace( "\\", "/" ).rsplit( "/", 1 )[ -1 ] or ( what.split( "::", 1 )[ 0 ].rsplit( "/", 1 )[ -1 ] if "::" in what else "" )
    names = { base, _slug( base ) } - { "" }
    if r.get( "rel" ):                                     # a run of this machine's record ( ADR 0025 ): its path under `runs/`
        cut = _cut( r[ "rel" ].split( "/" )[ : -1 ], names ) or "?"
        f = str( r.get( "file" ) or "" )
        if "/" not in cut and f.startswith( "/" ) and f.rsplit( "/", 1 )[ 0 ] != str( r.get( "project" ) or "" ):
            # a file outside its project, which errand files under its name alone: shown where it is
            return _home( f ) if f.startswith( _HOME ) else f
        return cut
    for anchor in OUT:
        i = leaf.find( anchor )
        if i >= 0:
            got = _cut( leaf[ i + len( anchor ) : ].strip( "/" ).split( "/" )[ : -1 ], names )   # ( the run's own directory out )
            if got:
                return got
    return what.split( "::", 1 )[ 0 ] if "::" in what else "?"


import os as _os

_HOME = _os.path.expanduser( "~" ) + "/"


def _home( p: str ) -> str:
    return "~/" + p[ len( _HOME ) : ] if p.startswith( _HOME ) else p


def _cut( parts: list, names: set ) -> str:
    """the file's path among the directories above a run: `<dirs>/<file>/<entry>` or `<dirs>/<file>` ( a file run whole )"""
    if len( parts ) >= 2 and parts[ -2 ] in names:
        return "/".join( parts[ : -1 ] )
    if parts and parts[ -1 ] in names:
        return "/".join( parts )
    if len( parts ) >= 2:
        return "/".join( parts[ : -1 ] )
    return "/".join( parts )


def _slug( s: str ) -> str:
    """as `results.slug` names a directory"""
    return "".join( c if c.isalnum() or c in "-_." else "_" for c in str( s ) ).strip( "_" ) or "_"


def entry_of( r: dict ) -> tuple:
    """`( name, params )` of a run: from its `result.yaml` ( a recent agent says them ), else from `what`"""
    what = r.get( "what" ) or ""
    rest = what.split( "::", 1 )[ 1 ] if "::" in what else what
    params = r.get( "params" ) if isinstance( r.get( "params" ), dict ) else None
    first = re.search( r"\s[A-Za-z_][\w.]*=", " " + rest )
    if params is None:
        params = dict( _PARAM.findall( " " + rest[ first.start() : ] if first else "" ) )
    name = r.get( "name" ) if isinstance( r.get( "name" ), str ) else ( rest[ : first.start() ] if first else rest ).strip()
    return name or "?", params


def _show( v ) -> str:
    if isinstance( v, float ):
        return f"{v:.4g}"
    if isinstance( v, ( dict, list ) ):
        return json.dumps( v, separators = ( ",", ":" ) )
    return "" if v is None else str( v )


def _num( v ):
    try:
        return ( 0, float( v ) )
    except ( TypeError, ValueError ):
        return ( 1, str( v ) )


def _id( logical: str ) -> str:
    """a node's id: short, and without what a list of ids would split on ( commas: entry names, parameter sets have some )"""
    return hashlib.sha1( logical.encode() ).hexdigest()[ : 12 ]


# The runs being removed ( ADR 0023 ): `( machine name, leaf )`. Shown greyed from the yes on, until their agents
# removed them ( then they leave the history ) or said they could not ( then they are shown again as they were ).
GOING: set = set()


def going( m, r ) -> bool:
    return bool( GOING ) and ( getattr( m, "name", m ), r.get( "leaf" ) ) in GOING


class Node:
    __slots__ = ( "name", "kind", "id", "children", "runs", "latest", "busy", "count" )

    def __init__( self, name, kind, id ):
        self.name, self.kind, self.id = name, kind, id
        self.children: dict = { }
        self.runs: list = [ ]          # ( machine, record, running )
        self.latest, self.busy, self.count = 0.0, False, 0

    def add( self, m, r, running ):
        self.runs.append( ( m, r, running ) )


def build( runs: list, roots = None ) -> Node:
    """`runs`: `( machine, record, running )`. -> the root of the tree, the dirs merged when they have one child."""
    root = Node( "", "root", "" )
    heads = _projects( runs, roots )
    for m, r, running in runs:
        path = rel_file( r )
        name, params = entry_of( r )
        node, sofar = root, ""
        head = heads.get( r.get( "project" ), "" )                 # its root, from the roots' common directory ( ADR 0025 )
        if head and not path.startswith( ( "/", "~" ) ):            # ( a file outside its project: where it is )
            path = f"{head}/{path}"
        parts = path.split( "/" )
        if parts[ 0 ] == "" and len( parts ) > 1:
            parts = [ "/" + parts[ 1 ] ] + parts[ 2 : ]
        for i, part in enumerate( parts ):
            sofar = f"{sofar}/{part}" if sofar else part
            kind = "file" if i == len( parts ) - 1 else "dir"
            node = node.children.setdefault( ( kind, part ), Node( part, kind, _id( sofar ) ) )
        entry = node.children.setdefault( ( "entry", name ), Node( name, "entry", _id( f"{path}::{name}" ) ) )
        key = json.dumps( { k: _show( v ) for k, v in sorted( params.items() ) } ) if params else ""
        target = entry.children.setdefault( ( "set", key ), Node( key, "set", _id( f"{path}::{name}::{key}" ) ) ) if params else entry
        target.add( m, r, running )
    _settle( root )
    return _merged( root )


def _projects( runs, all_roots = None ) -> dict:
    """where a run of this machine's record is: its root's path from the roots' common directory, put before its path
    under `runs/` -- so that a file is at one place whichever root its runs were started from ( `~/Projects` running
    `otrec/x.py`, `~/Projects/otrec` running `x.py`: `otrec/x.py` both ). The common directory itself is no row. Runs of
    the agents' histories ( no `rel` ): nothing. `all_roots`: every root of the record, filtered out or not -- the paths,
    and so the ids of the nodes, stay the same whatever is shown."""
    import os
    every = { r.get( "project" ) for _, r, _ in runs if r.get( "rel" ) and r.get( "project" ) } | set( all_roots or ( ) )
    odd = { r: r for r in every if not r.startswith( "/" ) }          # there only, no place here: under its own name
    roots = sorted( every - set( odd ) )
    if not roots:
        return odd
    top = os.path.commonpath( roots ) if len( roots ) > 1 else roots[ 0 ]
    return { **{ r: ( os.path.relpath( r, top ) if r != top else "" ).replace( os.sep, "/" ) for r in roots }, **odd }


def _settle( node: Node ):
    for c in node.children.values():
        _settle( c )
    node.count = len( node.runs ) + sum( c.count for c in node.children.values() )
    starts = [ r.get( "started" ) or 0 for _, r, _ in node.runs ] + [ c.latest for c in node.children.values() ]
    node.latest = max( starts ) if starts else 0.0
    node.busy = any( running for _, _, running in node.runs ) or any( c.busy for c in node.children.values() )


def _merged( node: Node ) -> Node:
    """a directory with one child and no runs of its own is one row with it: `experiments/exp_2d_real.py`"""
    kids = { }
    for k, c in node.children.items():
        c = _merged( c )
        while c.kind == "dir" and len( c.children ) == 1 and not c.runs:
            ( kind, _ ), only = next( iter( c.children.items() ) )
            merged = Node( f"{c.name}/{only.name}", only.kind, only.id )
            merged.children, merged.runs, merged.latest, merged.busy, merged.count = only.children, only.runs, only.latest, only.busy, only.count
            c = merged
        kids[ k ] = c
    node.children = kids
    return node


def all_runs( node: Node ) -> list:
    out = list( node.runs )
    for c in node.children.values():
        out += all_runs( c )
    return out


def find( node: Node, id: str ) -> Node | None:
    if node.id == id:
        return node
    for c in node.children.values():
        got = find( c, id )
        if got is not None:
            return got
    return None


def path_to( root: Node, key ) -> list:
    """the ids of the nodes to open for the row `key` ( `rows.key` ) to be shown: those above it, and the one that lists
    it ( a run's set or entry; a table's entry ) -> [ ] when it is not in the tree"""
    kind, _, what = key if isinstance( key, ( list, tuple ) ) and len( key ) == 3 else ( None, None, None )

    def hit( n: Node ) -> bool:
        if kind in ( "tnode", "tset", "thead" ):
            return n.id == what
        return kind == "work" and any( r.get( "leaf" ) == what for _, r, _ in n.runs )

    def walk( n: Node, above: list ):
        if hit( n ):
            return above + ( [ n.id ] if kind in ( "work", "thead" ) else [ ] )
        for c in n.children.values():
            got = walk( c, above + ( [ n.id ] if n.id else [ ] ) )
            if got is not None:
                return got
        return None
    return walk( root, [ ] ) or [ ]


def keep_latest( runs: list ) -> list:
    """what goes when only the latest is kept: for each parameter set, environment and machine, all but the most recent run and
    the most recent PASS ( when it is another ); never what runs"""
    groups: dict = { }
    for m, r, running in runs:
        name, params = entry_of( r )
        key = ( getattr( m, "name", m ), rel_file( r ), name, json.dumps( { k: _show( v ) for k, v in sorted( params.items() ) } ), r.get( "env" ) )
        groups.setdefault( key, [ ] ).append( ( m, r, running ) )
    gone = [ ]
    for runs_ in groups.values():
        runs_.sort( key = lambda x: -( x[ 1 ].get( "started" ) or 0 ) )
        kept = { id( runs_[ 0 ][ 1 ] ) }
        good = next( ( x for x in runs_ if x[ 1 ].get( "status" ) == "PASS" ), None )
        if good is not None:
            kept.add( id( good[ 1 ] ) )
        gone += [ x for x in runs_ if id( x[ 1 ] ) not in kept and not x[ 2 ] ]
    return gone


# ── rows ─────────────────────────────────────────────────────────────────────

def rows( root: Node, *, folded = (), opened = (), query = "", now = None, unfold = False ) -> list:
    """`unfold`: every node open ( what looks a row up by its key: a run's page, `/r/<id>` )"""
    now = now or time.time()
    out = [ ]

    def is_open( n: Node ) -> bool:
        k = f"t:{n.id}"
        return unfold or bool( query ) or k in opened or ( n.busy and k not in folded )

    def walk( n: Node, depth: int ):
        for c in sorted( n.children.values(), key = lambda c: ( c.kind != "dir", -c.latest ) ):    # folders first
            count = c.count
            label = c.name + ( "/" if c.kind in ( "dir", "project" ) and not c.name.endswith( "/" ) else "" )
            o = is_open( c )
            gone = bool( GOING ) and all( going( m, r ) for m, r, _ in all_runs( c ) )
            out.append( Row( label, "removing…" if gone else f"{count} run{'' if count == 1 else 's'}  {_ago( now - c.latest )}",
                             kind = "tnode", data = ( None, { "tree": c.id, "level": c.kind } ), depth = depth, open = o,
                             mark = "going" if gone else "run" if c.busy else "" ) )
            if not o:
                continue
            if c.kind == "entry" and c.children:
                table( c, depth + 1 )
            elif c.kind == "entry":
                out.extend( _run( m, r, running, depth + 1, now ) for m, r, running in _newest( c.runs ) )
            else:
                walk( c, depth + 1 )

    def table( entry: Node, depth: int ):
        sets = list( entry.children.values() )
        pnames, rnames = [ ], [ ]
        info = [ ]
        for s in sets:
            runs = _newest( s.runs )
            m, last, running = runs[ 0 ]
            params = entry_of( last )[ 1 ]
            res = next( ( r.get( "results" ) for _, r, _ in runs if isinstance( r.get( "results" ), dict ) and r.get( "results" ) ), { } ) or { }
            for k in params:
                if k not in pnames:
                    pnames.append( k )
            for k in res:
                if k not in rnames:
                    rnames.append( k )
            info.append( ( s, params, res, m, last, running, len( runs ) ) )
        cols = pnames + [ f"→{k}" for k in rnames ] + [ "status", "last", "took", "env", "runs" ]

        def cells( params, res, m, last, running, n ):
            status = "running" if running else ( last.get( "status" ) or "lost" )
            took = f"{last[ 'duration' ]:.1f} s" if isinstance( last.get( "duration" ), ( int, float ) ) else ""
            return ( [ _show( params.get( k ) ) for k in pnames ] + [ _show( res.get( k ) ) for k in rnames ] +
                     [ status, _at( last.get( "started" ) or 0, now ), took, f"{last.get( 'env' ) or ''}@{m.name}", str( n ) ] )

        values = [ cells( *x[ 1 : ] ) for x in info ]
        spec = next( ( o[ len( f"s:{entry.id}=" ) : ] for o in opened if isinstance( o, str ) and o.startswith( f"s:{entry.id}=" ) ), None )
        order = list( range( len( info ) ) )
        if spec and spec.lstrip( "-" ) in cols:
            c = cols.index( spec.lstrip( "-" ) )
            order.sort( key = lambda i: _num( values[ i ][ c ] ) if values[ i ][ c ] != "" else ( 2, "" ), reverse = spec.startswith( "-" ) )
        else:
            order.sort( key = lambda i: -info[ i ][ 0 ].latest )
        shown = [ n + ( " ▼" if spec == f"-{n}" else " ▲" if spec == n else "" ) for n in cols ]
        widths = [ max( [ len( shown[ c ] ) ] + [ len( v[ c ] ) for v in values ] ) for c in range( len( cols ) ) ]
        line = lambda vs: "  ".join( v.ljust( widths[ c ] ) for c, v in enumerate( vs ) ).rstrip()
        spans, at = [ ], 0
        for c, n in enumerate( cols ):
            spans.append( [ n, at, at + widths[ c ] ] )
            at += widths[ c ] + 2
        out.append( Row( line( shown ), "", kind = "thead", data = ( None, { "tree": entry.id, "cols": spans } ), depth = depth ) )
        for i in order:
            s, *_ = info[ i ]
            if len( s.runs ) == 1:                     # its only run: the line is the run, nothing to unfold
                m, r, running = s.runs[ 0 ]
                row = _run( m, r, running, depth, now )
                row.label, row.tabled = line( values[ i ] ), True
                out.append( row )
                continue
            o = is_open( s )
            running = info[ i ][ 5 ]
            gone = bool( GOING ) and all( going( m, r ) for m, r, _ in s.runs )
            out.append( Row( line( values[ i ] ), "", kind = "tset", data = ( None, { "tree": s.id } ), depth = depth, open = o,
                             mark = "going" if gone else "run" if running else { "PASS": "ok", "FAIL": "FAIL", "SKIP": "skip" }.get( info[ i ][ 4 ].get( "status" ), "lost" ) ) )
            if o:
                out.extend( _run( m, r, running, depth + 1, now ) for m, r, running in _newest( s.runs ) )

    walk( root, 0 )
    return out


def _newest( runs ):
    return sorted( runs, key = lambda x: -( x[ 1 ].get( "started" ) or 0 ) )


def _run( m, r, running, depth, now ) -> Row:
    status = "running" if running else ( r.get( "status" ) or "lost" )
    took = f"{r[ 'duration' ]:.1f} s" if isinstance( r.get( "duration" ), ( int, float ) ) else ""
    if going( m, r ):
        status, mark = "removing", "going"
    elif r.get( "there" ):                                 # the check found it on its machine only ( ADR 0025 )
        status, mark = f"on {m.name} only", "there"
    else:
        mark = "run" if running else { "PASS": "ok", "FAIL": "FAIL", "SKIP": "skip" }.get( status, "lost" )
    name = m.name if len( m.name ) <= 12 else m.name[ : 11 ] + "…"
    return Row( f"{_at( r.get( 'started' ) or 0, now )}  {name:<12} {r.get( 'env' ) or '':<12} {status:<7} {took}".rstrip(), "",
                kind = "run", data = ( m.name, r ), depth = depth, mark = mark )


def _at( t: float, now: float ) -> str:
    if time.localtime( t )[ : 3 ] == time.localtime( now )[ : 3 ]:
        return time.strftime( "%H:%M", time.localtime( t ) )
    return time.strftime( "%d %b %H:%M", time.localtime( t ) )


def _ago( s: float ) -> str:
    s = max( 0, int( s ) )
    return f"{s} s" if s < 90 else f"{s // 60} min" if s < 5400 else f"{s // 3600} h" if s < 172800 else f"{s // 86400} d"
