"""A stand-in for whatever your real work is. It knows nothing about errand."""
import math
import os

FTYPE = os.environ.get( "DEMO_FTYPE", "FP64" )
TOL   = 1e-6 if FTYPE == "FP32" else 1e-12


def solve( n, method = "cg", record = False ):
    """Pretend to solve something of size `n`, returning the iterate (or its history)."""
    x, r, history = 0.0, 1.0, [ ]
    steps = int( math.log( TOL ) / math.log( 0.7 ) ) * ( 1 if method == "cg" else 3 )
    for _ in range( steps ):
        r *= 0.7
        x += r
        sum( i * i for i in range( n // 10 ) )   # something for the clock to measure
        history.append( r )
    return history if record else x


def residual( x ):
    return abs( x - ( 1 / 0.3 ) ) * 1e-9
