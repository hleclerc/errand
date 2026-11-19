"""The runs started from this machine ( ADR 0025 ): every run directory under the `runs/` of every project root seen
here, wherever the run ran -- a run sent to another machine has its directory here too, its `result.yaml` brought back.
The runs' tab is built from it, with exact counts.

Kept as an index in memory and on disk ( `runs-index.json` in errand's cache ): one compact record per run, with the date
of its `result.yaml`, so that a run is read once, again only when its record changes. `refresh()` walks the directories'
dates ( 0.25 s for 63,000 runs ) and reads what changed; it runs when the bell rings ( a run ends, is brought back ) and
every `SWEEP` seconds. The host agent holds one, which serves the page; the TUI another, from the same file.

The roots: the projects runs were started from ( `note_root`, when a run starts ), the projects this machine's `seen`
links name, and, beside them, any directory holding an `errand-outputs/`.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

SWEEP = 60.0
STAMP = re.compile( r"^(\d{4})-(\d\d)-(\d\d)_(\d\d)h(\d\d)m(\d\d)" )
KEPT = ( "name", "file", "env", "place", "host", "status", "duration_s", "params", "results", "stamp" )
_KEYS = re.compile( r"^(" + "|".join( KEPT ) + r"):" )


class Run:
    """one run of the record: where ( `root`, `rel` its path under the root's `runs/` ), what its `result.yaml` said"""
    __slots__ = ( "root", "rel", "at", "name", "file", "env", "place", "host", "status", "started", "duration",
                  "params", "results" )

    def __init__( self, root, rel, at = 0.0, **said ):
        self.root, self.rel, self.at = root, rel, at
        for k in self.__slots__[ 3 : ]:
            setattr( self, k, said.get( k ) )

    @property
    def leaf( self ) -> str:
        return f"{self.root}/{_RUNS}/{self.rel}"

    def record( self ) -> dict:
        """as the runs' tree reads a run ( `runtree` ): the shape of the agents' history"""
        out = { "leaf": self.leaf, "project": self.root, "started": self.started, "status": self.status,
                "duration": self.duration, "env": self.env, "host": self.host, "place": self.place, "rel": self.rel }
        if self.name:
            out[ "name" ] = self.name
        if self.file:
            out[ "file" ] = self.file
        if isinstance( self.params, dict ):
            out[ "params" ] = self.params
        if isinstance( self.results, dict ):
            out[ "results" ] = self.results
        out[ "what" ] = f"{( self.file or '' ).rsplit( '/', 1 )[ -1 ]}::{self.name or '?'}"
        return out

    def dump( self ) -> list:
        return [ getattr( self, k ) for k in self.__slots__ ]


_RUNS = "errand-outputs/runs"           # a root's runs, by default ( `config.runs` )


def runs_dir( root: str ) -> Path:
    try:
        from .. import config
        return config.runs( Path( root ) )
    except Exception:
        return Path( root ) / _RUNS


def _cache() -> Path:
    from .. import bootstrap
    return bootstrap.local_cache()


def _started( name: str, fallback: float ) -> float:
    m = STAMP.match( name )
    if not m:
        return fallback
    try:
        return time.mktime( tuple( int( x ) for x in m.groups() ) + ( 0, 0, -1 ) )
    except ( OverflowError, ValueError ):
        return fallback


def _intern( v ):
    return sys_intern( v ) if isinstance( v, str ) and len( v ) < 80 else v


try:
    from sys import intern as sys_intern
except ImportError:                                         # pragma: no cover
    sys_intern = lambda s: s


def read_result( path: Path ) -> dict:
    """the fields kept of a `result.yaml`: its top-level lines that matter only, read by `yamlish`"""
    from .. import yamlish
    try:
        text = path.read_text( errors = "replace" )
    except OSError:
        return { }
    lines = [ l for l in text.splitlines() if _KEYS.match( l ) ]
    try:
        return yamlish.load( "\n".join( lines ) )
    except Exception:
        return { }


# ── the roots ────────────────────────────────────────────────────────────────

def _roots_file() -> Path:
    return _cache() / "roots.json"


def note_root( root ):
    """a project runs are started from: kept, its runs listed from now on"""
    root = str( Path( root ).resolve() )
    path = _roots_file()
    try:
        known = json.loads( path.read_text() )
    except ( OSError, ValueError ):
        known = [ ]
    if root in known:
        return
    try:
        path.parent.mkdir( parents = True, exist_ok = True )
        tmp = path.with_suffix( f".{os.getpid()}" )
        tmp.write_text( json.dumps( sorted( set( known ) | { root } ) ) )
        os.replace( tmp, path )
    except OSError:
        pass


def roots() -> list:
    """the project roots whose runs are listed: those runs were started from, those `seen` names, and beside them the
    directories that hold an `errand-outputs/` ( the projects of one place )"""
    found = set()
    try:
        found |= set( json.loads( _roots_file().read_text() ) )
    except ( OSError, ValueError ):
        pass
    try:
        from . import seen as S
        d = S._dir()
        found |= { rec.get( "project" ) for _, rec in ( S._records( d ) if d.is_dir() else [ ] ) if rec.get( "project" ) }
    except Exception:
        pass
    temp = ( "/tmp/", "/private/tmp/", "/private/var/folders/", "/var/folders/" )
    if str( _cache() ).startswith( temp ):
        temp = ( )                                   # ( errand itself in a scratch directory: a test's )
    found = { r for r in found if r and not r.startswith( temp ) and runs_dir( r ).is_dir() }
    around = set()
    for r in found:                                          # its neighbours and children that hold outputs too
        for base in ( Path( r ), Path( r ).parent ):
            try:
                for e in os.scandir( base ):
                    if e.is_dir( follow_symlinks = False ) and not e.name.startswith( "." ) and ( Path( e.path ) / _RUNS ).is_dir():
                        around.add( e.path )
            except OSError:
                pass
    return sorted( found | around )


# ── the index ────────────────────────────────────────────────────────────────

class Registry:
    def __init__( self, file: Path | None = None ):
        self.file = file or ( _cache() / "runs-index.json" )
        self.runs: dict = { }                # leaf -> Run
        self.roots: list = [ ]
        self.lock = threading.Lock()
        self.version = 0                     # bumped at every change: what was built from it is stale
        self.at = 0.0                        # time.time() of the last walk
        self._dirty = False
        self._dirs: dict = { }               # a directory -> ( its date, its runs, its other directories )
        self._load()

    def _load( self ):
        try:
            got = json.loads( self.file.read_text() )
        except ( OSError, ValueError ):
            return
        if not isinstance( got, dict ) or got.get( "v" ) != 1:
            return
        for row in got.get( "runs", [ ] ):
            try:
                r = Run( row[ 0 ], row[ 1 ], row[ 2 ], **dict( zip( Run.__slots__[ 3 : ], row[ 3 : ] ) ) )
            except Exception:
                continue
            self.runs[ r.leaf ] = r
        self.roots = got.get( "roots", [ ] )

    def save( self ):
        if not self._dirty:
            return
        try:
            self.file.parent.mkdir( parents = True, exist_ok = True )
            tmp = self.file.with_suffix( f".{os.getpid()}.{threading.get_ident()}" )
            with self.lock:
                data = { "v": 1, "roots": self.roots, "runs": [ r.dump() for r in self.runs.values() ] }
            tmp.write_text( json.dumps( data, separators = ( ",", ":" ) ) )
            os.replace( tmp, self.file )
            self._dirty = False
        except OSError:
            pass

    def refresh( self, force = False, every = 0.5 ) -> bool:
        """the directories walked, what changed read: -> whether anything did. A directory whose date did not change is
        not listed again ( `_dirs` ); a run with its `result.yaml` read is final, one without is looked at again."""
        if not force and time.time() - self.at < every:
            return False
        self.at = time.time()
        rs = roots()
        changed = rs != self.roots
        found: set = set()
        for root in rs:
            top = runs_dir( root )
            for leaf, name in self._walk( top ):
                found.add( leaf )
                had = self.runs.get( leaf )
                if had is not None and had.at:
                    continue                                       # read, and final
                res = Path( leaf ) / "result.yaml"
                try:
                    at = res.stat().st_mtime
                except OSError:
                    at = 0.0
                if had is not None and had.at == at:
                    continue
                self._read( root, top, leaf, name, at )
                changed = True
        gone = [ l for l in self.runs if l not in found ]
        if gone:
            with self.lock:
                for l in gone:
                    self.runs.pop( l, None )
            changed = True
        if changed:
            self.roots = rs
            self.version += 1
            self._dirty = True
            self.save()
        return changed

    def _read( self, root, top, leaf, name, at ):
        said = read_result( Path( leaf ) / "result.yaml" ) if at else { }
        rel = os.path.relpath( leaf, top ).replace( os.sep, "/" )
        started = _started( said.get( "stamp" ) or name, at or _mtime( leaf ) )
        run = Run( sys_intern( root ), rel, at, started = started,
                   duration = said.get( "duration_s" ) if isinstance( said.get( "duration_s" ), ( int, float ) ) else None,
                   **{ k: _intern( said.get( k ) ) for k in ( "name", "file", "env", "place", "host", "status" ) },
                   params = said.get( "params" ) if isinstance( said.get( "params" ), dict ) and said.get( "params" ) else None,
                   results = said.get( "results" ) if isinstance( said.get( "results" ), dict ) and said.get( "results" ) else None )
        with self.lock:
            self.runs[ leaf ] = run

    def _walk( self, top: Path, depth = 0 ):
        """the run directories under `top` ( named by their stamp, `2026-11-19_13h16m36-…`; their outputs not entered );
        a directory listed again only when its date changed"""
        if depth > 14:
            return
        key = str( top )
        try:
            mtime = os.stat( key ).st_mtime_ns
        except OSError:
            self._dirs.pop( key, None )
            return
        kept = self._dirs.get( key )
        if kept is None or kept[ 0 ] != mtime:
            runs, subs = [ ], [ ]
            try:
                with os.scandir( key ) as it:
                    for e in it:
                        if not e.is_dir( follow_symlinks = False ):
                            continue
                        if STAMP.match( e.name ):
                            runs.append( ( e.path, e.name ) )
                        elif not e.name.startswith( "." ):
                            subs.append( e.path )
            except OSError:
                return
            kept = self._dirs[ key ] = ( mtime, runs, subs )
        yield from kept[ 1 ]
        for sub in kept[ 2 ]:
            yield from self._walk( Path( sub ), depth + 1 )

    def forget( self, leaves ):
        """runs removed: out of the index at once"""
        with self.lock:
            n = sum( self.runs.pop( l, None ) is not None for l in leaves )
        if n:
            self.version += 1
            self._dirty = True

    def records( self ) -> list:
        with self.lock:
            return [ r.record() for r in self.runs.values() ]


def _mtime( p ) -> float:
    try:
        return os.stat( p ).st_mtime
    except OSError:
        return 0.0


_shared: dict = { }
_shared_lock = threading.Lock()


def shared() -> Registry:
    """this process's index ( one per cache: a test's own ), made and walked once; `refresh` again as things change"""
    key = str( _cache() )
    with _shared_lock:
        got = _shared.get( key )
        if got is None:
            got = _shared[ key ] = Registry()
            got.refresh( force = True )
        return got
