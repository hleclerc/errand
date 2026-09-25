"""Three kinds of work on the same code, in one file.

Nothing else is needed: there is no errand.py in this example, no environment
to declare, no configuration at all. `errand` finds this file because it
mentions `errand`, and runs whichever entry you name.
"""
import time

from errand import test, bench, experiment, Param

from primes import sieve, trial_division


# --- it must pass -----------------------------------------------------------
#
# Bare `errand` runs this one, and every other `test` in the tree, and stops
# there: a benchmark is not something you want fired by accident.

if test( "small primes" ):
    assert sieve( 30 ) == [ 2, 3, 5, 7, 11, 13, 17, 19, 23, 29 ]


if test( "the two agree", tags = [ "slow" ] ):
    assert sieve( 20_000 ) == trial_division( 20_000 )


# --- it must be fast --------------------------------------------------------
#
# `bench` keeps its numbers, dated, and takes the machine to itself while it
# runs -- so nothing else that errand launched is competing for the cache.
#
#   errand -k bench
#   errand primes_bench --n=100000,1000000        <- two runs, two directories
#
# A comma is a matrix. Here it gives one row per size in the summary that sits
# at the entry's root.

if p := bench( "sieve", n = Param( 100_000, help = "upper bound" ) ):
    t = time.perf_counter( )
    found = sieve( p.n )
    p.results[ "seconds" ] = time.perf_counter( ) - t
    p.results[ "primes" ]  = len( found )


# An entry is free to do several things at once -- this one is a benchmark
# that also asserts. There is no rule against it.

if p := bench( "sieve beats trial division", n = Param( 20_000 ) ):
    t = time.perf_counter( ); sieve( p.n )
    p.results[ "sieve_s" ] = time.perf_counter( ) - t

    t = time.perf_counter( ); trial_division( p.n )
    p.results[ "trial_s" ] = time.perf_counter( ) - t

    assert p.results[ "sieve_s" ] < p.results[ "trial_s" ]


# --- it must be looked at ---------------------------------------------------
#
#   errand -k exp
#   errand "test_primes::gaps"
#
# `p.out_dir` is this run's own directory. An experiment gets a stable
# `latest/` symlink beside the stamped ones, so the tab you leave open on
# runs/test_primes/gaps/latest/gaps.svg keeps working.

if p := experiment( "gaps", n = Param( 100_000 ) ):
    ps   = sieve( p.n )
    gaps = [ b - a for a, b in zip( ps, ps[ 1 : ] ) ]

    width, height = 800, 200
    points = " ".join( f"{ i * width / len( gaps ) :.1f},{ height - g * 4 }"
                       for i, g in enumerate( gaps ) )
    ( p.out_dir / "gaps.svg" ).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<polyline fill="none" stroke="black" points="{points}"/></svg>'
    )

    print( f"{ len( ps ) } primes, largest gap { max( gaps ) }" )   # -> output.txt
    p.results[ "largest_gap" ] = max( gaps )
