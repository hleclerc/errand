"""Finding something by typing a little of it.

**Not an edit distance.** Typing `tsq` must find `tests/test_shapes.py::quick`,
and the Levenshtein distance between those two is enormous -- edit distance
answers "how different are these two strings", which is a question nobody is
asking here. What an editor's *go to file* does, and what this does, is match
the letters IN ORDER but not necessarily together -- a subsequence -- and then
SCORE how well they sit: together beats scattered, the start of a word beats
the middle of one, early beats late, and a short candidate beats a long one
that merely contains the same letters.

Several words mean several searches, all of which must find something:
`shap gpu` is "the letters of shap, somewhere, AND the letters of gpu,
somewhere". That is what makes a search cheap to refine -- you add a word
rather than rewriting what you had.

The positions of the letters that matched come back with the score, because a
list that shows you WHY a row is in it is a list you can trust after one look.
"""
from __future__ import annotations

# What the letters are worth where they land. The numbers only matter against
# each other; these are the ones that put the obvious answer first.
ADJACENT  = 12      # right after the previous letter that matched
SEPARATOR = 24      # right after `_ - / . : space`, i.e. the start of a word
CAMEL     = 20      # right at a lowercase -> uppercase step
FIRST     = 24      # the very first character
SKIPPED   = -1      # per character stepped over inside the match
LEADING   = -2      # per character stepped over before it starts, and capped
LEADING_MAX = -12
LENGTH    = -0.05   # per character of the candidate: shorter is better

SEPARATORS = "_-/.: "
LIMIT = 400         # a candidate longer than this is cut: nobody reads that far


def score( needle: str, hay: str ):
    """-> ( score, [ positions ] ), or None when the letters are not all there.

    `needle` is matched case-insensitively; a candidate that is not matched at
    all returns None rather than a very bad score, so that callers can tell
    "no" from "barely".
    """
    if not needle:
        return 0.0, [ ]
    hay = hay[ : LIMIT ]
    low_needle, low_hay = needle.lower(), hay.lower()
    if len( low_needle ) > len( low_hay ):
        return None

    memo: dict = { }
    got = _best( low_needle, low_hay, hay, 0, 0, False, memo )
    if got is None:
        return None
    total, positions = got
    return total + LENGTH * len( hay ), positions


def _best( needle, hay, raw, ni, hi, after_match, memo ):
    """The best way of placing `needle[ni:]` into `hay[hi:]`. Memoised on
    ( where in the needle, where in the hay, does the previous letter sit right
    before this one ) -- which is all a placement depends on."""
    if ni == len( needle ):
        return 0.0, [ ]
    key = ( ni, hi, after_match )
    if key in memo:
        return memo[ key ]

    best = None
    letter = needle[ ni ]
    for i in range( hi, len( hay ) ):
        if hay[ i ] != letter:
            continue
        rest = _best( needle, hay, raw, ni + 1, i + 1, True, memo )
        if rest is None:
            continue
        gap = i - hi
        here = _bonus( hay, raw, i, after_match and gap == 0 )
        here += ( max( LEADING_MAX, LEADING * gap ) if ni == 0 else SKIPPED * gap )
        total = here + rest[ 0 ]
        if best is None or total > best[ 0 ]:
            best = ( total, [ i ] + rest[ 1 ] )
        # The first placement of the first letter is not necessarily the best
        # one -- `s` in `tests/shapes` should reach `shapes` -- so every
        # placement is tried, and the memo is what keeps that affordable.
    memo[ key ] = best
    return best


def _bonus( hay, raw, i, adjacent ):
    if i == 0:
        return FIRST
    if adjacent:
        return ADJACENT
    if hay[ i - 1 ] in SEPARATORS:
        return SEPARATOR
    if raw[ i - 1 ].islower() and raw[ i ].isupper():
        return CAMEL
    return 0.0


def terms( query: str ):
    """A query is a list of words, and every one of them must be found."""
    return [ word for word in query.split() if word ]


def score_all( query: str, hay: str ):
    """-> ( score, positions ) with every word of `query` placed, or None."""
    total, marks = 0.0, [ ]
    for word in terms( query ):
        got = score( word, hay )
        if got is None:
            return None
        total += got[ 0 ]
        marks += got[ 1 ]
    return total, sorted( set( marks ) )


def rank( query: str, items, fields ):
    """Order `items` by how well they answer `query`.

    `fields` is a callable giving, for one item, `{ name: ( text, weight ) }`.
    Each word is looked for in every field and kept where it scores best, so
    `shapes gpu` finds a case whose NAME says shapes and whose TAGS say gpu --
    which is the whole point of searching over several things at once.

    -> [ ( item, score, { field: positions } ) ], best first, and only the ones
    that matched.
    """
    if not terms( query ):
        return [ ( item, 0.0, { } ) for item in items ]

    out = [ ]
    for item in items:
        parts = fields( item )
        total, marks, missing = 0.0, { }, False
        for word in terms( query ):
            best = None
            for name, ( text, weight ) in parts.items():
                got = score( word, text )
                if got is None:
                    continue
                if best is None or got[ 0 ] * weight > best[ 0 ]:
                    best = ( got[ 0 ] * weight, name, got[ 1 ] )
            if best is None:
                missing = True
                break
            total += best[ 0 ]
            marks.setdefault( best[ 1 ], [ ] )
            marks[ best[ 1 ] ] = sorted( set( marks[ best[ 1 ] ] + best[ 2 ] ) )
        if not missing:
            out.append( ( item, total, marks ) )
    out.sort( key = lambda row: -row[ 1 ] )
    return out
