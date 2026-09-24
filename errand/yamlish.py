"""A YAML writer and reader for the small shape errand writes.

`errand` must work before any environment exists, so it cannot depend on
PyYAML. It does not need to: what it writes is a flat mapping whose values are
scalars, flow mappings and flow lists, which is a small enough language to emit
and parse here. What comes out is ordinary YAML -- any real parser reads it.

Reading is only ever applied to files errand itself wrote (result.yaml,
summary.yaml), so the parser is deliberately narrow: it understands the shape
above and raises on anything else rather than guessing.
"""
from __future__ import annotations

_NEEDS_QUOTES = set( "#:{}[],&*!|>'\"%@`" )


def _scalar( v ):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance( v, int ):
        return str( v )
    if isinstance( v, float ):
        # repr keeps round-tripping; inf/nan are not YAML numbers, so quote them
        return repr( v ) if v == v and abs( v ) != float( "inf" ) else f"'{v!r}'"
    s = str( v )
    if ( s == "" or s[ 0 ] in _NEEDS_QUOTES or s[ 0 ] == " " or s[ -1 ] == " "
         or s in ( "null", "true", "false", "yes", "no", "~" )
         or _looks_numeric( s ) or ": " in s or " #" in s ):
        return "'" + s.replace( "'", "''" ) + "'"
    return s


def _looks_numeric( s ):
    try:
        float( s )
        return True
    except ValueError:
        return False


def _flow( v ):
    """A dict or list on one line -- what params/results/tags look like."""
    if isinstance( v, dict ):
        return "{ " + ", ".join( f"{_scalar( k )}: {_flow( x )}" for k, x in v.items() ) + " }" if v else "{ }"
    if isinstance( v, ( list, tuple ) ):
        return "[ " + ", ".join( _flow( x ) for x in v ) + " ]" if v else "[ ]"
    return _scalar( v )


def dump( data: dict ) -> str:
    """A top-level mapping; nested containers go inline."""
    out = [ ]
    for k, v in data.items():
        if isinstance( v, dict ) and v and any( isinstance( x, ( dict, list ) ) for x in v.values() ):
            out.append( f"{_scalar( k )}:" )
            for k2, v2 in v.items():
                out.append( f"  {_scalar( k2 )}: {_flow( v2 )}" )
        else:
            out.append( f"{_scalar( k )}: {_flow( v )}" )
    return "\n".join( out ) + "\n"


# ── reading ──────────────────────────────────────────────────────────────────

def _parse_scalar( s ):
    s = s.strip()
    if s in ( "null", "~", "" ):
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    if len( s ) >= 2 and s[ 0 ] == s[ -1 ] and s[ 0 ] in "'\"":
        return s[ 1 : -1 ].replace( s[ 0 ] * 2, s[ 0 ] )
    try:
        return int( s )
    except ValueError:
        pass
    try:
        return float( s )
    except ValueError:
        pass
    return s


def _split_top( s, sep = "," ):
    """Split on `sep`, ignoring separators nested in {} [] or quotes."""
    out, depth, quote, cur = [ ], 0, None, [ ]
    for c in s:
        if quote:
            cur.append( c )
            if c == quote:
                quote = None
            continue
        if c in "'\"":
            quote = c
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        if c == sep and depth == 0:
            out.append( "".join( cur ) )
            cur = [ ]
        else:
            cur.append( c )
    if "".join( cur ).strip():
        out.append( "".join( cur ) )
    return out


def _parse_value( s ):
    s = s.strip()
    if s.startswith( "{" ) and s.endswith( "}" ):
        body = s[ 1 : -1 ].strip()
        if not body:
            return { }
        out = { }
        for item in _split_top( body ):
            k, _, v = item.partition( ":" )
            out[ _parse_scalar( k ) ] = _parse_value( v )
        return out
    if s.startswith( "[" ) and s.endswith( "]" ):
        body = s[ 1 : -1 ].strip()
        return [ _parse_value( x ) for x in _split_top( body ) ] if body else [ ]
    return _parse_scalar( s )


def load( text: str ) -> dict:
    out, current = { }, None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith( "#" ):
            continue
        indented = raw[ 0 ] in " \t"
        key, _, value = raw.strip().partition( ":" )
        key = _parse_scalar( key )
        if indented:
            if current is None:
                raise ValueError( f"unexpected indented line: {raw!r}" )
            out[ current ][ key ] = _parse_value( value )
        elif value.strip() == "":
            current = key
            out[ key ] = { }
        else:
            current = None
            out[ key ] = _parse_value( value )
    return out


def read( path ):
    """`load` of a file, or None when it isn't there."""
    try:
        return load( path.read_text() )
    except FileNotFoundError:
        return None


def write( path, data ):
    path.write_text( dump( data ) )
