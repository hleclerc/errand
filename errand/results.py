"""The output tree: where a run writes, and the summaries above it.

    runs/{file}__{name}/[params]/{place}/{date}/
    runs/{file}__{name}/[params]/{place}/latest -> {date}

Every component is computed from the run rather than declared by it, which is
what lets the same path be worked out on another machine -- before the run
happens -- and rsynced back afterwards.

Summaries are recomputed by re-reading the tree, never from a ledger kept in
memory: they are then correct however many separate invocations contributed to
them, and they repair themselves.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path

from . import yamlish

RESULT   = "result.yaml"
SUMMARY  = "summary.yaml"
OUTPUT   = "output.txt"
LATEST   = "latest"


def today( ) -> str:
    return datetime.datetime.now( datetime.timezone.utc ).date().isoformat()


def slug( s ) -> str:
    return "".join( c if c.isalnum() or c in "-_." else "_" for c in str( s ) ).strip( "_" ) or "_"


def param_hash( resolved: dict ) -> str | None:
    if not resolved:
        return None
    return hashlib.sha256( repr( sorted( resolved.items() ) ).encode() ).hexdigest()[ : 10 ]


def place( env: str | None = None ) -> str:
    """Where this ran: the environment, and the machine.

    Both matter and neither is enough. The same machine with two environments
    is two different sets of numbers -- a different compiler, a different
    image, single precision instead of double -- and the same environment on
    two machines is two more. So both name the directory, and a run can never
    land on top of a run that was not the same run.

    The environment stands for its container rather than the other way round:
    an image is one of the things an environment IS, and the name is the one
    the project chose.
    """
    host = socket.gethostname().split( "." )[ 0 ] or platform.node() or "localhost"
    return f"{slug( env )}@{slug( host )}" if env else slug( host )


def label( entry ) -> str:
    return f"{slug( entry.file.stem )}__{slug( entry.name )}"


def dirs_for( out_root: Path, entry, resolved, where ):
    """-> ( leaf, entry_root ). The leaf is this run's directory; the entry root
    is the top of what the summaries cover.

    Every run is dated, without exception -- a stable path costs nothing, since
    `latest` is a symlink beside the dated directories.
    """
    entry_root = out_root / label( entry )
    base = entry_root
    h = param_hash( resolved )
    if h:
        base = base / h
    return base / where / today(), entry_root


def clear( path: Path ):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree( path )
    path.mkdir( parents = True, exist_ok = True )


def point_latest_at( leaf: Path ):
    """`latest` beside the dated directories, so a stable path costs no history."""
    link = leaf.parent / LATEST
    try:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to( leaf.name, target_is_directory = True )
    except OSError:
        pass          # a filesystem without symlinks is a loss, not a failure


# ── provenance ───────────────────────────────────────────────────────────────

def git_commit( root: Path ):
    try:
        rev = subprocess.run( [ "git", "-C", str( root ), "rev-parse", "--short", "HEAD" ],
                              capture_output = True, text = True, timeout = 5 )
        if rev.returncode:
            return None, False
        status = subprocess.run( [ "git", "-C", str( root ), "status", "--porcelain" ],
                                 capture_output = True, text = True, timeout = 5 )
        return rev.stdout.strip(), bool( status.stdout.strip() )
    except ( OSError, subprocess.SubprocessError ):
        return None, False


def ram_mb( ) -> float:
    import resource
    import sys
    peak = resource.getrusage( resource.RUSAGE_SELF ).ru_maxrss
    return peak / ( 1024 * 1024 ) if sys.platform == "darwin" else peak / 1024


# ── writing ──────────────────────────────────────────────────────────────────

def write_result( leaf: Path, *, entry, root, env_name, where, tags, status, error,
                  duration_s, ram, params, results, output_text, version ):
    # The output file is normally written live, as the run talks; all that is
    # left here is to say whether it holds anything. Writing it again would
    # only risk replacing a complete file with a truncated buffer.
    output_file = None
    live = leaf / OUTPUT
    if live.exists():
        if live.stat().st_size:
            output_file = OUTPUT
        else:
            live.unlink()
    elif output_text.strip():
        output_file = OUTPUT
        live.write_text( output_text )

    commit, dirty = git_commit( root )
    data = {
        "name"       : entry.name,
        "file"       : _under( entry.file, root ),
        "line"       : entry.line,
        "kind"       : entry.kind,
        "env"        : env_name,
        "place"      : where,
        "host"       : socket.gethostname().split( "." )[ 0 ],
        "commit"     : commit,
        "dirty"      : dirty,
        "errand"     : version,
        "status"     : status,
        "error"      : error,
        "duration_s" : round( duration_s, 3 ),
        "ram_mb"     : round( ram, 1 ),
        "params"     : _plain( params ),
        "tags"       : _plain( tags ),
        "results"    : _plain( results ),
        "output_file": output_file,
    }
    yamlish.write( leaf / RESULT, data )
    return data


def _under( path: Path, root: Path ) -> str:
    """Relative to the root when it is under it, absolute when it is not.

    A file reached through a symlink, or provided from outside the tree, must
    not cost an otherwise good run its result file.
    """
    try:
        return str( path.relative_to( root ) )
    except ValueError:
        return str( path )


def _plain( v ):
    """A value that did not mean to be serialized degrades to its repr rather
    than taking an otherwise good run's result file down with it."""
    if isinstance( v, dict ):
        return { str( k ): _plain( x ) for k, x in v.items() }
    if isinstance( v, ( list, tuple ) ):
        return [ _plain( x ) for x in v ]
    if v is None or isinstance( v, ( str, int, float, bool ) ):
        return v
    return repr( v )


# ── summaries ────────────────────────────────────────────────────────────────

def refresh( entry_root: Path ):
    """Rewrite every summary under `entry_root`, deepest first.

    A directory holding a result file is a run; a directory holding
    directories is summarized from what they hold. The levels are whatever the
    tree actually has, so an entry with no parameters simply has one fewer.
    """
    if not entry_root.is_dir():
        return
    for directory in _dirs_deepest_first( entry_root ):
        rows = { }
        for child in sorted( p for p in directory.iterdir() if p.is_dir() and not p.is_symlink() ):
            row = _row_of( child )
            if row:
                rows[ child.name ] = row
        if rows:
            yamlish.write( directory / SUMMARY, _summarize( rows ) )


def _dirs_deepest_first( top: Path ):
    out = [ ]
    for directory, subdirs, _ in os.walk( top ):
        d = Path( directory )
        if ( d / RESULT ).exists():
            subdirs[ : ] = [ ]
            continue
        out.append( d )
    return sorted( out, key = lambda p: -len( p.parts ) )


def _row_of( directory: Path ):
    """One row for a child: its own result, or the digest of its summary.

    A row's numbers are kept PER KEY. Folding `seconds` and `iterations` into
    one min/max would put a stopwatch and a counter in the same interval and
    say nothing about either; what a history is for is watching one quantity
    move.
    """
    result = yamlish.read( directory / RESULT )
    if result is not None:
        extents = { "duration_s": _pair( result.get( "duration_s" ) ) }
        for key, value in ( result.get( "results" ) or { } ).items():
            if isinstance( value, ( int, float ) ) and not isinstance( value, bool ):
                extents[ key ] = _pair( value )
        return { "status": result.get( "status" ), "runs": 1, **_readable( extents ) }

    summary = yamlish.read( directory / SUMMARY )
    if summary is None:
        return None
    row = { "status": "FAIL" if summary.get( "failed" ) else "PASS",
            "runs"  : summary.get( "runs", 0 ) }
    row.update( _readable( _extents_of( summary ) ) )
    return row


def _pair( v ):
    return None if v is None else [ v, v ]


def _readable( extents: dict ):
    """`seconds: 12.4` when there is one value, `seconds: [ 11.9, 12.4 ]` when
    there is a spread -- a row that has not moved should not look like it has."""
    out = { }
    for key, pair in extents.items():
        if pair is None:
            continue
        lo, hi = pair
        out[ key ] = lo if lo == hi else [ lo, hi ]
    return out


def _extents_of( row: dict ):
    """Read `seconds: 12.4` or `seconds: [ 11.9, 12.4 ]` back as a pair."""
    out = { }
    for key, value in row.items():
        if key in ( "status", "runs", "entries", "passed", "failed" ):
            continue
        if isinstance( value, list ) and len( value ) == 2:
            out[ key ] = [ value[ 0 ], value[ 1 ] ]
        elif isinstance( value, ( int, float ) ) and not isinstance( value, bool ):
            out[ key ] = [ value, value ]
    return out


def _summarize( rows: dict ):
    merged = { }
    for row in rows.values():
        for key, pair in _extents_of( row ).items():
            if key in merged:
                merged[ key ] = [ min( merged[ key ][ 0 ], pair[ 0 ] ),
                                  max( merged[ key ][ 1 ], pair[ 1 ] ) ]
            else:
                merged[ key ] = list( pair )
    return {
        "passed" : sum( 1 for r in rows.values() if r[ "status" ] == "PASS" ),
        "failed" : sum( 1 for r in rows.values() if r[ "status" ] != "PASS" ),
        "runs"   : sum( r.get( "runs", 1 ) for r in rows.values() ),
        **_readable( merged ),
        "entries": rows,
    }
