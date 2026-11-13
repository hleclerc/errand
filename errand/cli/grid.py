"""Parameters with several values ( `--grid=, … --n 1,2,3` ): the matrix of runs they make, and how it is said.
"""
from __future__ import annotations

import itertools

from .parsing import ARGS


# ── matrices ─────────────────────────────────────────────────────────────────

def alternatives( text: str, sep = None ) -> list[ str ]:
    """Without a separator a value is one value, whatever it holds. With one
    ( `--grid=+` ), `a+b` is two values and `a++b` three -- the middle one
    empty. No escape: a value that holds the separator asks for another one."""
    if not sep:
        return [ text ]
    return text.split( sep )


def expand( raw_values: dict, params: dict, raw = ( ), sep = None ):
    """With `--grid=+`, `--n=1000+5000` is an axis of a declared parameter.
    Without `--grid`, every value is one value: a grid is asked for, never
    guessed from a comma. Anything else of the target's own is passed as it
    was written -- a command's words are never rewritten.
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
        parts = alternatives( given, sep ) if isinstance( given, str ) else [ given ]
        try:
            values = [ p.ptype( x ) for x in parts ]
        except ( TypeError, ValueError ):
            hint = ( "  ( a grid is asked for: --grid=, before the target )"
                     if not sep and isinstance( given, str ) and "," in given else "" )
            raise ValueError( f"--{name.replace( '_', '-' )}: cannot read {given!r} "
                              f"as {p.ptype.__name__}{hint}" )
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
    anything starts, so a grid that was not meant as one is seen in time."""
    axes = { }
    for varied, _ in combos:
        for k, v in varied.items():
            seen = axes.setdefault( k, [ ] )
            if v not in seen:
                seen.append( v )
    shown = ", ".join( f"{k.replace( '_', '-' )} = {' | '.join( str( v ) for v in vs )}"
                       for k, vs in axes.items() )
    return f"{len( combos )} runs: {shown}"


def split_values( raw, sep = None, what = "a tag" ):
    """The values of a tag or the names of `--env`: one, or several under
    `--grid=SEP`. A comma cannot be in a tag value or an environment name, so a
    comma without `--grid` is a grid that was not asked for, and said so."""
    if raw is None:
        return [ None ]
    words = raw if isinstance( raw, ( list, tuple ) ) else [ raw ]
    out = [ v.strip() for w in words for v in alternatives( str( w ), sep ) if v.strip() ]
    if not sep:
        for v in out:
            if "," in v:
                raise ValueError( f"{what}: {v!r} holds a comma; several values are asked for "
                                  f"with --grid=, ( before the target )" )
    return out


def separator_for( values ) -> str:
    """The `--grid` separator a command built from these values can use: the
    first of a few that none of them holds."""
    for sep in ( ",", "+", "|", ";", "@@" ):
        if not any( sep in str( v ) for v in values ):
            return sep
    raise ValueError( "no grid separator fits these values" )
