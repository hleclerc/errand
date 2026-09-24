"""The code under test. Nothing in here knows about errand."""


def sieve( n ):
    """Primes below `n`, by Eratosthenes."""
    flags = bytearray( [ 1 ] ) * n
    flags[ 0 : 2 ] = b"\0\0"
    for i in range( 2, int( n ** 0.5 ) + 1 ):
        if flags[ i ]:
            flags[ i * i : : i ] = bytearray( len( flags[ i * i : : i ] ) )
    return [ i for i, f in enumerate( flags ) if f ]


def trial_division( n ):
    """The same thing, the slow way."""
    out = [ ]
    for i in range( 2, n ):
        if all( i % d for d in range( 2, int( i ** 0.5 ) + 1 ) ):
            out.append( i )
    return out
