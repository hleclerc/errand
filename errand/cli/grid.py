"""Parameters with several values ( `--n 1,2,3` ): the matrix of runs they make, and how it is said.
"""
from __future__ import annotations

import itertools

from .parsing import ARGS


# ── matrices ─────────────────────────────────────────────────────────────────

def alternatives( text: str ) -> list[ str ]:
    """A comma makes a grid, wherever it is: `a,b` is two values, `a,,b` three
    -- the middle one empty -- and `a\\,b` is one, with a comma in it. No other
    backslash means anything."""
    out, cur, i = [ ], [ ], 0
    while i < len( text ):
        if text.startswith( "\\,", i ):
            cur.append( "," )
            i += 2
            continue
        if text[ i ] == ",":
            out.append( "".join( cur ) )
            cur = [ ]
        else:
            cur.append( text[ i ] )
        i += 1
    return out + [ "".join( cur ) ]


def expand( raw_values: dict, params: dict, raw = ( ) ):
    """`--n=1000,5000` is an axis of a declared parameter: the runner that
    declared it reads the comma. Anything else of the target's own is passed as
    it was written -- a command's words are never rewritten.
    -> [ ( varied, { name: value, ARGS: [ ... ] } ), ... ].

    Values arrive as strings precisely so a comma can be seen before the type
    is applied; `varied` holds only what actually had several values, so the
    non-matrix case stays silent.
    """
    axes = { }
    for name, given in raw_values.items():
        if given is None:
            continue
        p = params[ name ]
        parts = alternatives( given ) if isinstance( given, str ) else [ given ]
        try:
            values = [ p.ptype( x ) for x in parts ]
        except ( TypeError, ValueError ):
            raise ValueError( f"--{name.replace( '_', '-' )}: cannot read {given!r} "
                              f"as {p.ptype.__name__}" )
        if p.choices:
            wrong = [ v for v in values if v not in p.choices ]
            if wrong:
                raise ValueError( f"--{name.replace( '_', '-' )}: {wrong} not in {p.choices}" )
        axes[ name ] = values

    names = list( axes )
    out = [ ]
    for combo in itertools.product( *( axes[ n ] for n in names ) ):
        chosen = dict( zip( names, combo ) )
        varied = { n: v for n, v in chosen.items() if len( axes[ n ] ) > 1 }
        chosen[ ARGS ] = list( raw )
        out.append( ( varied, chosen ) )
    return out


def describe_grid( combos ) -> str:
    """`4 runs: n = 2 | 3, args = --size 1 | --size 2` -- said once, before
    anything starts, so a comma that was not meant as a grid is seen in time."""
    axes = { }
    for varied, _ in combos:
        for k, v in varied.items():
            seen = axes.setdefault( k, [ ] )
            if v not in seen:
                seen.append( v )
    shown = ", ".join( f"{k.replace( '_', '-' )} = {' | '.join( str( v ) for v in vs )}"
                       for k, vs in axes.items() )
    return f"{len( combos )} runs: {shown}"


def split_values( raw ):
    """A comma means a matrix, on a tag exactly as on a parameter."""
    if raw is None:
        return [ None ]
    return [ v.strip() for v in alternatives( str( raw ) ) if v.strip() ]
