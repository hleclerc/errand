"""A case's traceback without errand in it ( ADR 0016 ).

A body runs inside errand ( `here.run_case`, `discovery.import_file` ) and the import machinery: four
frames out of five of what Python prints are those, before the user's line. They are left out; the
user's frames, and anything else's ( a library's ), stay, in their order. When the failure is errand's
own -- no frame of anyone else -- nothing is left out: an error of errand's is never hidden. `-v`
( `ERRAND_VERBOSE` ) prints them whole.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

_ERRAND = str( Path( __file__ ).resolve().parents[ 1 ] )        # the package's directory


def errand_frame( filename: str ) -> bool:
    """A frame of errand's, or of the import machinery's."""
    if filename.startswith( "<frozen importlib" ):
        return True
    try:
        return str( Path( filename ).resolve() ).startswith( _ERRAND + "/" ) or \
               str( Path( filename ).resolve() ).startswith( _ERRAND + "\\" )
    except ( OSError, ValueError ):
        return False


def _trim( te: traceback.TracebackException, seen: set ):
    if id( te ) in seen:
        return
    seen.add( id( te ) )
    frames = list( te.stack )
    kept = [ f for f in frames if not errand_frame( f.filename ) ]
    if kept:                                   # none but errand's: errand failed, and says where
        te.stack = traceback.StackSummary.from_list( kept )
    for other in ( te.__cause__, te.__context__, *( getattr( te, "exceptions", None ) or [ ] ) ):
        if other is not None:
            _trim( other, seen )


def text( exc: BaseException, whole: bool = False, colorize: bool = False ) -> str:
    """`exc` as Python prints it, errand's frames left out unless `whole`."""
    te = traceback.TracebackException.from_exception( exc, capture_locals = False )
    if not whole:
        _trim( te, set() )
    try:
        return "".join( te.format( colorize = colorize ) )
    except TypeError:                          # a Python that does not color its tracebacks
        return "".join( te.format() )


def print_failure( exc: BaseException, file = None ):
    """In place of `traceback.print_exc()` for a case's failure."""
    from .. import trace
    file = file or sys.stderr
    colorize = False
    try:
        import _colorize                       # Python 3.13+: as `print_exc` would decide
        colorize = _colorize.can_colorize( file = file )
    except Exception:
        pass
    file.write( text( exc, whole = trace.enabled(), colorize = colorize ) )
    file.flush()
