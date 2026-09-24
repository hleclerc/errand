"""The same work, run in whichever environment you ask for.

Nothing below mentions a machine, a container or a precision. Where it runs is
a property of the invocation, not of the code -- which is what lets one command
line run it in four places at once.
"""
import os
import time

from errand import bench, experiment, test, has_tag, tag, Param

from solver import solve, residual


# `DEMO_FTYPE` is set by the `Vars` layer of whichever environment was picked.
# The code reads an environment variable like any other program would; it does
# not ask errand anything.

FTYPE = os.environ.get( "DEMO_FTYPE", "FP64" )


# A file that must not even be IMPORTED under the wrong environment says so
# here, at the top, before the import that would fail. Finding entries means
# importing every candidate file, so an import at module level runs whatever
# was selected -- and on a machine where the GPU stack is broken that takes
# down the session, not just this file.
#
#   if not has_tag( "cuda" ):
#       sys.exit( 0 )
#   import cupy


if test( "it converges" ):
    x = solve( n = 200 )
    assert residual( x ) < 1e-8


# --- the benchmark ----------------------------------------------------------
#
#   errand -k bench                                  the default environment
#   errand bench_solver --env gpu                    one, by name
#   errand bench_solver --fp 32,64                   a matrix over a tag
#   errand bench_solver --env local,gpu --n=1e4,1e5  two axes, four runs
#   errand bench_solver -t 'cuda=True'               every cuda environment
#
# `bench` takes the machine to itself while it runs. Other errands on this host
# wait, whichever terminal or project they came from.

if p := bench( "solve", n = Param( 10_000, help = "number of unknowns" ),
                        method = Param( "cg", choices = [ "cg", "direct" ] ) ):
    t = time.perf_counter( )
    x = solve( n = p.n, method = p.method )
    p.results[ "seconds" ]  = time.perf_counter( ) - t
    p.results[ "residual" ] = residual( x )
    p.results[ "ftype" ]    = FTYPE          # recorded, so the rows say which is which


# An entry can ask for something short of the whole machine.

if p := bench( "warm cache probe", exclusive = False, cpus = 2, ram = "1G" ):
    t = time.perf_counter( )
    solve( n = 500 )
    p.results[ "seconds" ] = time.perf_counter( ) - t


# --- something to look at ---------------------------------------------------
#
#   errand -k exp --env local,gpu
#
# Two environments, two directories, two pictures to put side by side -- and a
# `latest/` symlink in each, so the tabs stay valid.

if p := experiment( "convergence", n = Param( 10_000 ) ):
    history = solve( n = p.n, record = True )
    svg = "".join( f'<circle cx="{ i * 8 }" cy="{ 200 + 20 * __import__( "math" ).log10( r ) }" r="2"/>'
                   for i, r in enumerate( history ) )
    ( p.out_dir / "convergence.svg" ).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="220">{svg}</svg>' )
    print( f"{ len( history ) } iterations in { FTYPE }, on { tag( 'driver' ) }" )
