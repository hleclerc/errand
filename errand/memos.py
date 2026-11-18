"""`@errand.memo` ( ADR 0015 ): a result kept by its inputs, in the project's cache zone.

    <root>/errand-cache/memo/<module.qualname>/<key>/value.npz | value.pkl | ( save's own )
                                                    /meta.json
    <root>/errand-cache/memo/.errand-work/                     parts and locks: never part of a sync

The key hashes the function's name, its `version`, and its arguments bound to its signature
( `key_of` ). Arguments are hashed by what they hold, never by `repr`.

Imported only when a function is decorated: standard library, plus whatever the values need
( numpy, for an array ).
"""
from __future__ import annotations

import dataclasses
import enum
import functools
import hashlib
import inspect
import json
import os
import pickle
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

SUB      = "memo"
WORK     = ".errand-work"
ENV      = "ERRAND_MEMO"             # off | refresh
BEAT     = 30.0                      # seconds between two touches of a held lock
STALE    = 300.0                     # a lock untouched this long was left by a run that died
FORMAT   = 1                         # how keys are made: raised if that changes


class MemoError( TypeError ):
    pass


# -- the key ----------------------------------------------------------------------

_file_hashes: dict = { }             # ( path, size, mtime ) -> its hash, in this process


def _file_digest( p: Path ) -> str:
    st = p.stat()
    k = ( str( p ), st.st_size, st.st_mtime_ns )
    if k not in _file_hashes:
        h = hashlib.sha256()
        with open( p, "rb" ) as f:
            for chunk in iter( lambda: f.read( 1 << 20 ), b"" ):
                h.update( chunk )
        _file_hashes[ k ] = h.hexdigest()
    return _file_hashes[ k ]


def _array_parts( x ):
    """( dtype, shape, bytes ) of an array of numpy, jax or torch; None for anything else."""
    mod = type( x ).__module__.split( "." )[ 0 ]
    if mod == "torch":
        t = x.detach().cpu().contiguous()
        try:
            a = t.numpy()
        except TypeError:                            # bfloat16 and the like: their bits
            import torch
            return str( t.dtype ), tuple( t.shape ), t.view( torch.int16 if t.element_size() == 2 else torch.uint8 ).numpy().tobytes()
        return str( t.dtype ), tuple( a.shape ), a.tobytes()
    if mod in ( "numpy", "jax", "jaxlib" ) and hasattr( x, "shape" ) and hasattr( x, "dtype" ):
        import numpy as np
        a = np.ascontiguousarray( np.asarray( x ) )
        if a.dtype == object:
            return None
        return a.dtype.str, a.shape, a.tobytes()
    return None


def _feed( h, x, where: str, seen: set ):
    """`x` into the hash `h`, by what it holds. `where` names it in an error."""
    t = type( x )
    if x is None or isinstance( x, ( bool, int, float, complex, str ) ):
        h.update( f"{t.__name__}:{x!r};".encode() )
        return
    if isinstance( x, ( bytes, bytearray, memoryview ) ):
        b = bytes( x )
        h.update( f"bytes:{len( b )}:".encode() + b )
        return
    if id( x ) in seen:
        raise MemoError( f"{where} holds itself: no key for it" )
    if hasattr( x, "__errand_key__" ):
        h.update( f"key:{t.__module__}.{t.__qualname__}:".encode() )
        _feed( h, x.__errand_key__(), where, seen )
        return
    if isinstance( x, enum.Enum ):
        h.update( f"enum:{t.__module__}.{t.__qualname__}.{x.name};".encode() )
        return
    if isinstance( x, Path ):
        if x.is_file():
            h.update( f"file:{x.name}:{_file_digest( x )};".encode() )
        elif x.exists():
            raise MemoError( f"{where} is a directory ( {x} ): give a key ( `key = …` ) or what in it matters" )
        else:
            h.update( f"path:{x.as_posix()};".encode() )
        return
    parts = _array_parts( x )
    if parts is not None:
        dtype, shape, data = parts
        h.update( f"array:{dtype}:{shape}:{len( data )}:".encode() + data )
        return
    seen = seen | { id( x ) }
    if isinstance( x, ( tuple, list ) ):
        h.update( f"{t.__name__}:{len( x )}[".encode() )
        for i, v in enumerate( x ):
            _feed( h, v, f"{where}[{i}]", seen )
        h.update( b"]" )
        return
    if isinstance( x, dict ):
        items = [ ]
        for k, v in x.items():
            kh = hashlib.sha256()
            _feed( kh, k, f"a key of {where}", seen )
            items.append( ( kh.hexdigest(), k, v ) )
        h.update( f"dict:{len( items )}{{".encode() )
        for kd, k, v in sorted( items, key = lambda i: i[ 0 ] ):
            h.update( kd.encode() )
            _feed( h, v, f"{where}[{k!r}]", seen )
        h.update( b"}" )
        return
    if isinstance( x, ( set, frozenset ) ):
        subs = [ ]
        for v in x:
            sh = hashlib.sha256()
            _feed( sh, v, f"an item of {where}", seen )
            subs.append( sh.hexdigest() )
        h.update( f"set:{len( subs )}:{''.join( sorted( subs ) )};".encode() )
        return
    if dataclasses.is_dataclass( x ) and not isinstance( x, type ):
        h.update( f"dataclass:{t.__module__}.{t.__qualname__}(".encode() )
        for f in dataclasses.fields( x ):
            h.update( f"{f.name}=".encode() )
            _feed( h, getattr( x, f.name ), f"{where}.{f.name}", seen )
        h.update( b")" )
        return
    if mod_scalar( x ):
        import numpy as np
        a = np.asarray( x )
        h.update( f"scalar:{a.dtype.str}:".encode() + a.tobytes() )
        return
    raise MemoError( f"{where} is a {t.__module__}.{t.__qualname__}, which errand.memo cannot hash by its contents: "
                     f"give it `__errand_key__()`, pass `key = …` to memo, or `ignore = [ … ]` it" )


def mod_scalar( x ) -> bool:
    return type( x ).__module__ == "numpy" and hasattr( x, "dtype" ) and getattr( x, "shape", None ) == ( )


def name_of( fn, root = None ) -> str:
    """What names a function on every machine and however it was imported: its file from the project root
    ( `exp/recon.reconstruct` ) when the file is in the project -- errand imports a file under a name of its
    own, a script run by hand is `__main__` --, else its module ( a library installed elsewhere )."""
    qual = fn.__qualname__.replace( "<", "_" ).replace( ">", "_" )
    try:
        src = Path( inspect.getsourcefile( fn ) or "" ).resolve()
        top = Path( root ).resolve() if root else None
        if top is None:
            from .downloads import project_root
            top = project_root( src.parent )
        return f"{src.relative_to( top ).with_suffix( '' ).as_posix()}.{qual}"
    except ( TypeError, ValueError, OSError ):
        return f"{fn.__module__}.{qual}"


def key_of( fn, version, args, kwargs, *, ignore = ( ), key = None, source = False, name = None ) -> str:
    """The key of a call: the function, its version, its arguments by what they hold."""
    h = hashlib.sha256()
    h.update( f"errand-memo:{FORMAT}:{name or name_of( fn )}:{version!r};".encode() )
    if source:
        try:
            h.update( inspect.getsource( fn ).encode() )
        except ( OSError, TypeError ):
            raise MemoError( f"{fn.__qualname__}: source = True, but its source cannot be read" ) from None
    if key is not None:
        _feed( h, key( *args, **kwargs ), f"the key of {fn.__qualname__}", set() )
        return h.hexdigest()[ : 40 ]
    bound = inspect.signature( fn ).bind( *args, **kwargs )
    bound.apply_defaults()
    for name, value in bound.arguments.items():
        if name in ignore:
            continue
        h.update( f"{name}=".encode() )
        _feed( h, value, f"argument {name!r} of {fn.__qualname__}", set() )
    return h.hexdigest()[ : 40 ]


# -- keeping a value --------------------------------------------------------------

def _arrays( value ):
    """The arrays of a value that a `.npz` holds whole: an array, or a tuple, list or dict ( of str ) of them."""
    try:
        import numpy as np
    except ImportError:
        return None
    if isinstance( value, np.ndarray ) and value.dtype != object:
        return "array", { "a": value }
    if isinstance( value, ( tuple, list ) ) and value and all( isinstance( v, np.ndarray ) and v.dtype != object for v in value ):
        return type( value ).__name__, { f"a{i}": v for i, v in enumerate( value ) }
    if isinstance( value, dict ) and value and all( isinstance( k, str ) and isinstance( v, np.ndarray ) and v.dtype != object
                                                    for k, v in value.items() ):
        return "dict", { f"k_{k}": v for k, v in value.items() }
    return None


def write_value( d: Path, value, save = None ) -> str:
    if save is not None:
        save( value, d )
        return "save"
    got = _arrays( value )
    if got is not None:
        import numpy as np
        shape, arrays = got
        with open( d / "value.npz", "wb" ) as f:
            np.savez( f, **arrays )
        return f"npz:{shape}"
    with open( d / "value.pkl", "wb" ) as f:
        pickle.dump( value, f, protocol = pickle.HIGHEST_PROTOCOL )
    return "pickle"


def read_value( d: Path, how: str, load = None ):
    if how == "save" or load is not None:
        if load is None:
            raise MemoError( f"{d}: written by a `save`, and no `load` to read it" )
        return load( d )
    if how.startswith( "npz:" ):
        import numpy as np
        shape = how[ 4 : ]
        with np.load( d / "value.npz", allow_pickle = False ) as z:
            if shape == "array":
                return z[ "a" ]
            if shape == "dict":
                return { k[ 2 : ]: z[ k ] for k in z.files }
            got = [ z[ f"a{i}" ] for i in range( len( z.files ) ) ]
            return tuple( got ) if shape == "tuple" else got
    with open( d / "value.pkl", "rb" ) as f:
        return pickle.load( f )


class _Locked:
    """One computation of a key at a time, across processes and machines that share the disk. The lock is
    touched while it is held: a long computation is not taken for a dead one."""

    def __init__( self, path: Path ):
        self.path, self.stop = path, threading.Event()

    def __enter__( self ):
        self.path.parent.mkdir( parents = True, exist_ok = True )
        while True:
            try:
                os.mkdir( self.path )
                break
            except FileExistsError:
                pass
            try:
                if time.time() - self.path.stat().st_mtime > STALE:
                    os.rmdir( self.path )
                    continue
            except OSError:
                continue
            time.sleep( 0.2 )
        threading.Thread( target = self._beat, daemon = True ).start()
        return self

    def _beat( self ):
        while not self.stop.wait( BEAT ):
            try:
                os.utime( self.path, None )
            except OSError:
                return

    def __exit__( self, *_ ):
        self.stop.set()
        try:
            os.rmdir( self.path )
        except OSError:
            pass


# -- the decorator ----------------------------------------------------------------

_said_no_project = False


def _mode( ) -> str:
    from .entries import memo as public
    got = ( getattr( public, "mode", None ) or os.environ.get( ENV ) or "on" ).strip().lower()
    if got not in ( "on", "off", "refresh" ):
        raise MemoError( f"errand.memo mode {got!r}: on, off or refresh" )
    return got


def memo_root( root = None ) -> Path | None:
    from .downloads import ZONE, project_root
    try:
        return Path( root or project_root() ) / ZONE / SUB
    except FileNotFoundError:
        return None


def memo( fn = None, *, version = 0, key = None, ignore = ( ), save = None, load = None, source = False, root = None ):
    """`@errand.memo` or `@errand.memo( version = 2, … )`: see ADR 0015 and the module's docstring."""
    if fn is None:
        return lambda f: memo( f, version = version, key = key, ignore = ignore, save = save, load = load,
                               source = source, root = root )
    if ( save is None ) != ( load is None ):
        raise MemoError( f"{fn.__qualname__}: `save` and `load` go together" )
    ignore = tuple( [ ignore ] if isinstance( ignore, str ) else ignore )
    named = [ ]                                       # found once, at the first call: the project is known then

    def where( *args, **kwargs ) -> Path | None:
        top = memo_root( root )
        if top is None:
            return None
        if not named:
            named.append( name_of( fn, top.parent.parent ) )
        return top / named[ 0 ].replace( "/", "." ) / key_of( fn, version, args, kwargs, ignore = ignore, key = key,
                                                               source = source, name = named[ 0 ] )

    @functools.wraps( fn )
    def wrapper( *args, **kwargs ):
        global _said_no_project
        from .steps import step
        mode = _mode()
        if mode == "off":
            return fn( *args, **kwargs )
        d = where( *args, **kwargs )
        if d is None:
            if not _said_no_project:
                _said_no_project = True
                print( f"errand.memo: no project ( errand-*.py ) above {Path.cwd()}: {fn.__qualname__} is computed, "
                       f"and nothing is kept", file = sys.stderr )
            return fn( *args, **kwargs )
        short = fn.__qualname__

        def loaded( ):
            meta = json.loads( ( d / "meta.json" ).read_text() )
            value = read_value( d, meta.get( "format", "pickle" ), load )
            step( f"{short}: from the cache ( {meta.get( 'host', '?' )}, {meta.get( 'date', '?' )}, "
                  f"{_duration( meta.get( 'seconds', 0 ) )} )" )
            return value

        if mode == "on" and ( d / "meta.json" ).is_file():
            try:
                return loaded()
            except Exception as err:
                print( f"errand.memo: {short}: {d} does not load ( {type( err ).__name__}: {err} ): computed again",
                       file = sys.stderr )
        with _Locked( d.parent.parent / WORK / "locks" / f"{d.parent.name}-{d.name}" ):
            if mode == "on" and ( d / "meta.json" ).is_file():           # computed by another run meanwhile
                try:
                    return loaded()
                except Exception:
                    pass
            step( f"{short}: computing" )
            t0 = time.time()
            value = fn( *args, **kwargs )
            seconds = time.time() - t0
            part = d.parent.parent / WORK / "parts" / f"{d.parent.name}-{d.name}-{os.getpid()}-{time.time_ns()}"
            part.mkdir( parents = True )
            try:
                how = write_value( part, value, save )
                ( part / "meta.json" ).write_text( json.dumps( {
                    "function": named[ 0 ], "version": version, "format": how,
                    "host": socket.gethostname(), "date": time.strftime( "%Y-%m-%d %H:%M" ), "seconds": round( seconds, 3 ),
                    "args": _summary( fn, args, kwargs ) }, indent = 1 ) )
                d.parent.mkdir( parents = True, exist_ok = True )
                if d.exists():                          # refreshed, or a value that did not load
                    shutil.rmtree( d, ignore_errors = True )
                try:
                    os.replace( part, d )
                except OSError:
                    pass                                # written meanwhile by a machine that shares the disk
            finally:
                shutil.rmtree( part, ignore_errors = True )
            return value

    wrapper.memo_dir = where
    return wrapper


def _duration( s: float ) -> str:
    s = float( s or 0 )
    if s < 60:
        return f"{s:.1f} s"
    if s < 3600:
        return f"{s / 60:.0f} min"
    return f"{s / 3600:.1f} h"


def _summary( fn, args, kwargs ) -> dict:
    """The arguments in short, for a person reading `meta.json`."""
    try:
        bound = inspect.signature( fn ).bind( *args, **kwargs )
        bound.apply_defaults()
        items = bound.arguments.items()
    except TypeError:
        items = enumerate( args )
    out = { }
    for k, v in items:
        if hasattr( v, "shape" ) and hasattr( v, "dtype" ):
            out[ str( k ) ] = f"{type( v ).__name__}( {tuple( v.shape )}, {v.dtype} )"
        else:
            r = repr( v )
            out[ str( k ) ] = r if len( r ) <= 80 else r[ : 77 ] + "..."
    return out
