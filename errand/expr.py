"""The tag expression language: one grammar, three readers.

    -t over environments,  -e over entries,  has_tag inside a file

Literals, `&`, `|`, `!`, and `=` for a valued tag. No parentheses: an
expression that needs them is a sign the dimensions are wrong.

Precedence is the usual one -- `!` binds tighter than `&`, which binds tighter
than `|` -- so `a & !b | c` reads as `(a & !b) | c`.
"""
from __future__ import annotations


def matches( expression: str, tags ) -> bool:
    """Does `tags` satisfy `expression`? `tags` is a dict or an iterable of names."""
    table = _as_table( tags )
    expression = ( expression or "" ).strip()
    if not expression:
        return True
    return any( all( _literal( lit, table ) for lit in conj.split( "&" ) if lit.strip() )
                for conj in expression.split( "|" ) )


def names( expression: str ) -> set:
    """The tag names an expression mentions, negations included."""
    out = set()
    for conj in ( expression or "" ).split( "|" ):
        for lit in conj.split( "&" ):
            lit = lit.strip().lstrip( "!" ).strip()
            if lit:
                out.add( lit.partition( "=" )[ 0 ].strip() )
    return out


def _literal( lit, table ):
    lit = lit.strip()
    if lit.startswith( "!" ):
        return not _literal( lit[ 1 : ], table )
    name, sep, value = ( s.strip() for s in lit.partition( "=" ) )
    if not name:
        raise ValueError( f"empty tag in expression: {lit!r}" )
    if name not in table:
        return False
    return _same( table[ name ], value ) if sep else True


def _same( have, wanted ):
    """`cuda=True` should match `cuda`, and `fp=64` match the string or the int."""
    if have is True:
        return wanted.lower() in ( "true", "yes", "1" )
    if have is False:
        return wanted.lower() in ( "false", "no", "0" )
    return str( have ) == wanted


def _as_table( tags ) -> dict:
    if isinstance( tags, dict ):
        return tags
    return { t: True for t in ( tags or [ ] ) }


def format_tags( tags ) -> str:
    """`driver=jax,cuda` -- what crosses an ssh hop and what `--envs` prints."""
    table = _as_table( tags )
    return ",".join( k if v is True else f"{k}={v}" for k, v in sorted( table.items() ) )
