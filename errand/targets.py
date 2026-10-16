"""What a target on the command line designates.

    errand run tests/test_ot.py::basic
    errand run '**/test_*.py::grad_*'
    errand run 'tests/{ot,shapes}/test_*.py::{basic,quick}'
    errand run 'tests/**::*',bench/fft.py

A target is a PATH, relative to the directory errand is started from, extension
included -- what the shell completes and what pytest prints -- then optionally
`::` and an entry name. Both sides are globs, the same globs on both sides:
`*` and `?` within a name, `[…]` a class, `{a,b}` alternatives, and `**` any
depth of directories on the path side. With `::`, a path that names a directory
means everything under it. This module resolves the targets with `::`; the
others are files and commands, see `discovery`.

A comma outside braces separates targets, as it separates the values of every
other axis; `\\,` is a comma that is only a comma.

What a target cannot designate is an error rather than an empty run: a path
without a glob must exist, and a glob must match something. Running nothing
because of a typo, and saying "all good", is the worst answer there is.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

GLOB_CHARS = "*?["

# `\,` `\{` `\}` stand for themselves. They are swapped for characters nobody
# types while the text is split and expanded, and swapped back afterwards.
_ESCAPES = { "\\,": "\x01", "\\{": "\x02", "\\}": "\x03" }
_BACK    = { v: k[ 1 ] for k, v in _ESCAPES.items() }


def _protect( text: str ) -> str:
    for k, v in _ESCAPES.items():
        text = text.replace( k, v )
    return text


def _unprotect( text: str ) -> str:
    for k, v in _BACK.items():
        text = text.replace( k, v )
    return text


def _split_top( text: str, sep = "," ) -> list[ str ]:
    """`text` cut at every `sep` that is not inside braces."""
    out, depth, start = [ ], 0, 0
    for i, c in enumerate( text ):
        if c == "{":
            depth += 1
        elif c == "}" and depth:
            depth -= 1
        elif c == sep and depth == 0:
            out.append( text[ start : i ] )
            start = i + 1
    out.append( text[ start : ] )
    return out


def split( pattern: str ) -> list[ str ]:
    """The targets of a comma-separated pattern, escapes still in place."""
    return [ _unprotect_commas( s ).strip() for s in _split_top( _protect( pattern ) ) if s.strip() ]


def _unprotect_commas( text: str ) -> str:
    # Back to the escaped spelling: the braces of a target are expanded later,
    # and must still know which commas were only commas.
    return text.replace( "\x01", "\\," ).replace( "\x02", "\\{" ).replace( "\x03", "\\}" )


def expand( text: str ) -> list[ str ]:
    """`a{b,c}d` -> [ `abd`, `acd` ], nested braces included, as a shell does it.

    A brace with no comma in it is not an alternative and stays as it is.
    """
    def go( s ):
        depth, start = 0, None
        for i, c in enumerate( s ):
            if c == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif c == "}" and depth:
                depth -= 1
                if depth == 0:
                    inner = s[ start + 1 : i ]
                    parts = _split_top( inner )
                    if len( parts ) > 1:
                        head, tail = s[ : start ], s[ i + 1 : ]
                        return [ r for p in parts for r in go( head + p + tail ) ]
        return [ s ]

    return [ _unprotect( s ) for s in dict.fromkeys( go( _protect( text ) ) ) ]


def is_glob( text: str ) -> bool:
    return any( c in text for c in GLOB_CHARS )


def _class( text: str, i: int ):
    """The `[…]` starting at `i` as a regex class, and where it ends -- or
    ( None, i ) when it does not close, and `[` is then only a bracket."""
    j = i + 1
    if j < len( text ) and text[ j ] in "!^":
        j += 1
    if j < len( text ) and text[ j ] == "]":
        j += 1
    while j < len( text ) and text[ j ] != "]":
        j += 1
    if j >= len( text ):
        return None, i
    body = text[ i + 1 : j ]
    if body[ : 1 ] in ( "!", "^" ):
        body = "^" + body[ 1 : ]
    return "[" + body.replace( "\\", "\\\\" ).replace( "[", "\\[" ) + "]", j


def path_regex( glob: str ) -> re.Pattern:
    """A path glob as a regex over `/`-separated absolute paths.

    `*` and `?` stay inside one directory; `**` as a whole component is any
    number of them, none included.
    """
    out, i, n = [ ], 0, len( glob )
    while i < n:
        c = glob[ i ]
        if glob.startswith( "**", i ) and ( i == 0 or glob[ i - 1 ] == "/" ):
            if glob.startswith( "**/", i ):
                out.append( "(?:[^/]*/)*" )
                i += 3
                continue
            if i + 2 == n:
                out.append( ".*" )
                i += 2
                continue
        if c == "*":
            out.append( "[^/]*" )
        elif c == "?":
            out.append( "[^/]" )
        elif c == "[":
            cls, end = _class( glob, i )
            if cls is not None:
                out.append( cls )
                i = end + 1
                continue
            out.append( re.escape( c ) )
        else:
            out.append( re.escape( c ) )
        i += 1
    return re.compile( "".join( out ) + r"\Z" )


def name_regex( glob: str ) -> re.Pattern:
    """An entry-name glob: the same glob, with no directories to stay inside."""
    out, i = [ ], 0
    while i < len( glob ):
        c = glob[ i ]
        if c == "*":
            out.append( ".*" )
        elif c == "?":
            out.append( "." )
        elif c == "[":
            cls, end = _class( glob, i )
            if cls is not None:
                out.append( cls )
                i = end + 1
                continue
            out.append( re.escape( c ) )
        else:
            out.append( re.escape( c ) )
        i += 1
    return re.compile( "".join( out ) + r"\Z", re.DOTALL )


def name_matches( glob: str, name: str ) -> bool:
    return name_regex( glob ).match( name ) is not None


def escape( text: str ) -> str:
    """`text` as a target that designates exactly it: what the screen writes
    when it turns a ticked case back into a command."""
    out = [ ]
    for c in text:
        if c in "*?[":
            out.append( f"[{c}]" )
        elif c in ",{}":
            out.append( "\\" + c )
        else:
            out.append( c )
    return "".join( out )


def real( path ) -> str:
    return os.path.realpath( str( path ) )


class Spec( tuple ):
    """( the files a target designates, the entry-name glob or None ).

    A pair, because that is what runners read; the target it came from rides
    along, for the errors that have to quote it.
    """
    def __new__( cls, files, name, text ):
        made = super().__new__( cls, ( files, name ) )
        made.text = text
        return made


def under( files, base: str ) -> list:
    base = base.rstrip( os.sep ) + os.sep
    return [ f for f in files if real( f ).startswith( base ) ]


def resolve( pattern: str | None, files: list[ Path ], *, cwd: Path, root: Path,
             explicit = None, suggest = None ) -> list[ Spec ]:
    """The specs a pattern means, over `files` -- the ones that declare work.

    A file named in full that is not among them is offered to `explicit( path )`,
    which says whether something can run it anyway: a script is never found by
    looking, but it can be asked for.

    Raises ValueError, with something to do about it, when a target designates
    nothing.
    """
    here = real( cwd )
    base = here if ( here + os.sep ).startswith( real( root ).rstrip( os.sep ) + os.sep ) else real( root )

    if not pattern:
        return [ Spec( under( files, base ), None, "" ) ]

    by_real = { real( f ): f for f in files }
    specs = [ ]
    for text in split( pattern ):
        path_part, sep, name_part = text.partition( "::" )
        path_part = path_part.strip()
        names = expand( name_part.strip() ) if sep and name_part.strip() else [ None ]

        matched, missing, idle = [ ], [ ], [ ]
        for alt in ( expand( path_part ) if path_part else [ "" ] ):
            absolute = os.path.normpath( os.path.join( here, alt ) ) if alt else here
            if not is_glob( alt ):
                if os.path.isdir( absolute ):
                    matched += under( files, real( absolute ) )
                elif os.path.isfile( absolute ):
                    hit = by_real.get( real( absolute ) )
                    if hit is None and explicit is not None and explicit( Path( absolute ) ):
                        hit = Path( absolute )
                    ( matched.append( hit ) if hit is not None else idle.append( alt ) )
                else:
                    missing.append( alt )
                continue
            rx = path_regex( absolute )
            for f in files:
                # A glob may name a directory too: `'**/ot'` is everything in it.
                p = real( f )
                while p and p != os.sep:
                    if rx.match( p ):
                        matched.append( f )
                        break
                    p = os.path.dirname( p )
                    if not p.startswith( real( root ) ):
                        break

        matched = list( dict.fromkeys( matched ) )
        if not matched:
            raise ValueError( _nothing( text, missing, idle, suggest ) )
        specs += [ Spec( matched, n, text ) for n in names ]
    return specs


def _nothing( text, missing, idle, suggest ) -> str:
    if missing and not idle:
        why = f"{missing[ 0 ]}: no such file or directory"
    elif idle:
        why = f"{idle[ 0 ]}: no entry runner takes it ( see errand.runners, or -r NAME )"
    else:
        why = f"'{text}' matches no file an entry runner takes"
    near = suggest( text.partition( "::" )[ 0 ] ) if suggest else [ ]
    if near:
        why += "\n  did you mean:  " + "  ".join( near )
    return why
