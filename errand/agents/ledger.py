"""The ledger: the machines this one has sent work to, so `errand status` knows where to look ( ADR 0008 ).

    ~/.cache/errand/ledger/<id>.json      { "target", "name", "last" }

One entry per machine reached through its agent ( `agents.open` ), whatever the project: what runs
there is then asked of that machine itself ( `table` ), which knows it better than any record kept
here could -- work started from elsewhere, or by a command that was killed, included.

A machine is forgotten after two weeks unused, or when asked ( `forget`: `errand machines forget`,
`d` in `errand tui` ): it is not asked any more, until work is sent there again. Nothing over there is
stopped by it.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .. import bootstrap

LEDGER   = "ledger"
FORGET   = 14 * 86400.0       # a machine not reached for this long is not asked any more
DORMANT  = 86400.0            # no work sent there for this long: not contacted unless asked ( a shared login node )
REFRESH  = 60.0               # an entry is rewritten at most this often


def _dir() -> Path:
    return bootstrap.local_cache() / LEDGER


def note( target: dict ):
    """`target` was reached: a machine to ask. Only ssh hosts: the other agents ( environments,
    guests, allocations ) live on a host, and are found there."""
    if target.get( "kind" ) != "ssh":
        return
    from .upstream import identity, name
    key = identity( target )
    path = _dir() / f"{hashlib.sha1( key.encode() ).hexdigest()[ : 12 ]}.json"
    try:
        if time.time() - path.stat().st_mtime < REFRESH:
            return
    except OSError:
        pass
    try:
        path.parent.mkdir( parents = True, exist_ok = True )
        tmp = path.with_suffix( ".tmp" )
        old = { }
        try:
            old = json.loads( path.read_text() )
        except ( OSError, ValueError ):
            pass
        rec = { **old, "target": target, "name": name( target ), "last": time.time() }
        if rec.get( "watch" ) is False:
            rec[ "watch" ] = None                            # work sent there again: watched as any other
        rec.setdefault( "first", rec[ "last" ] )             # the name a machine shows is its oldest one
        tmp.write_text( json.dumps( rec ) )
        tmp.replace( path )
    except OSError:
        pass              # a ledger that cannot be written must not stop the work


def machines() -> list:
    """The machines reached lately, most recent first: [ { target, name, last } ]."""
    out = [ ]
    for p in _dir().glob( "*.json" ) if _dir().is_dir() else [ ]:
        try:
            rec = json.loads( p.read_text() )
        except ( OSError, ValueError ):
            continue
        if time.time() - rec.get( "last", 0 ) > FORGET:
            p.unlink( missing_ok = True )
            continue
        out.append( rec )
    return sorted( out, key = lambda r: -r.get( "last", 0 ) )


def _files( ):
    for p in sorted( _dir().glob( "*.json" ) ) if _dir().is_dir() else [ ]:
        try:
            yield p, json.loads( p.read_text() )
        except ( OSError, ValueError ):
            continue


def forget( name: str ) -> list:
    """The machine `name` forgotten -- a name it is reached by, or its label, and every other name of the
    same machine ( `groups` ). -> the names removed. Nothing over there is touched."""
    names = next( ( g[ "names" ] for g in groups() if name in g[ "names" ] or name == g[ "label" ] ), [ ] )
    gone = [ ]
    for p, rec in _files():
        if rec.get( "name" ) in names:
            p.unlink( missing_ok = True )
            gone.append( rec[ "name" ] )
    return gone


def rename( name: str, label: str ) -> list:
    """The machine `name` ( any of its names, or its label ) shown as `label` from now on, every name of it
    alike. -> its names; empty when there is no such machine."""
    names = next( ( g[ "names" ] for g in groups() if name in g[ "names" ] or name == g[ "label" ] ), [ ] )
    for p, rec in _files():
        if rec.get( "name" ) in names:
            rec[ "label" ] = label.strip() or None
            tmp = p.with_suffix( ".tmp" )
            tmp.write_text( json.dumps( rec ) )
            tmp.replace( p )
    return names


def learn( name: str, host: str ):
    """`name` answered as the machine `host` ( its hostname ): two names that answer alike are one machine."""
    for p, rec in _files():
        if rec.get( "name" ) == name and rec.get( "host" ) != host:
            rec[ "host" ] = host
            tmp = p.with_suffix( ".tmp" )
            tmp.write_text( json.dumps( rec ) )
            tmp.replace( p )


def _alias( rec: dict ) -> str:
    """The ssh name without its user: `hugo.leclerc@cinaps` and `cinaps` are reached the same way."""
    host = ( rec.get( "target" ) or { } ).get( "host" ) or rec.get( "name", "" )
    return host.rsplit( "@", 1 )[ -1 ]


def groups( ) -> list:
    """The machines, each once whatever the names it is reached by: same ssh name but for the user, same
    label, or the same hostname answered. [ { label, name ( shown ), names, target ( of the latest work ),
    last, host } ], latest work first."""
    recs = machines()
    parent = list( range( len( recs ) ) )

    def top( i ):
        while parent[ i ] != i:
            parent[ i ] = parent[ parent[ i ] ]
            i = parent[ i ]
        return i

    for key in ( _alias, lambda r: r.get( "label" ), lambda r: r.get( "host" ) ):
        seen = { }
        for i, r in enumerate( recs ):
            k = key( r )
            if k:
                if k in seen:
                    parent[ top( i ) ] = top( seen[ k ] )
                else:
                    seen[ k ] = i
    out = { }
    for i, r in enumerate( recs ):
        out.setdefault( top( i ), [ ] ).append( r )
    groups = [ ]
    for rs in out.values():
        latest = max( rs, key = lambda r: r.get( "last", 0 ) )
        label = next( ( r[ "label" ] for r in rs if r.get( "label" ) ), None )
        # its oldest name; among entries that do not say when they began ( older ledgers ), the shortest
        oldest = min( rs, key = lambda r: ( r.get( "first", float( "inf" ) ), len( r[ "name" ] ) ) )
        groups.append( { "label": label, "name": label or oldest[ "name" ], "names": sorted( r[ "name" ] for r in rs ),
                         "watch": next( ( r[ "watch" ] for r in rs if r.get( "watch" ) is not None ), None ),
                         "target": latest[ "target" ], "last": latest.get( "last", 0 ),
                         "host": next( ( r[ "host" ] for r in rs if r.get( "host" ) ), None ) } )
    return sorted( groups, key = lambda g: -g[ "last" ] )


HERE = "here.label"           # this machine's own name, when it was given one ( not a .json: not a machine to ask )


def here_name( ) -> str:
    """What this machine is shown as: the name given to it ( `rename_here` ), its hostname otherwise."""
    import socket
    try:
        label = ( _dir() / HERE ).read_text().strip()
    except OSError:
        label = ""
    return label or socket.gethostname().split( "." )[ 0 ] or "localhost"


def rename_here( label: str ):
    """This machine shown as `label` from now on ( its hostname again when empty )."""
    path = _dir() / HERE
    if not label.strip():
        path.unlink( missing_ok = True )
        return
    path.parent.mkdir( parents = True, exist_ok = True )
    tmp = path.with_suffix( ".tmp" )
    tmp.write_text( label.strip() + "\n" )
    tmp.replace( path )


def set_watch( name: str, on ) -> list:
    """Whether the machine `name` ( any of its names, or its label ) is contacted: True always, False never,
    None as its work says ( `dormant` ). Saved: `errand tui` and `errand status` follow it. -> its names."""
    names = next( ( g[ "names" ] for g in groups() if name in g[ "names" ] or name == g[ "label" ] ), [ ] )
    for p, rec in _files():
        if rec.get( "name" ) in names:
            rec[ "watch" ] = on
            tmp = p.with_suffix( ".tmp" )
            tmp.write_text( json.dumps( rec ) )
            tmp.replace( p )
    return names


def watched( rec: dict, now = None ) -> bool:
    """Whether errand contacts it: as set ( `set_watch` ), else while work was sent there lately."""
    if rec.get( "watch" ) is not None:
        return bool( rec[ "watch" ] )
    return not dormant( rec, now )


def dormant( rec: dict, now = None ) -> bool:
    """No work sent there for a day: `errand status` and `errand tui` do not contact it, so that no agent
    of errand's is started on a machine others share ( a cluster's login node ) for nothing."""
    return ( now or time.time() ) - rec.get( "last", 0 ) > DORMANT
