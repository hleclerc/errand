"""The heat equation on [0, 1], split over the ranks of an MPI program.

Each rank holds one block of the grid, plus one ghost value at each end. At every
step it swaps its edge values with its two neighbours ( `Sendrecv` ), updates its
block, and the energy is summed over all the ranks at the end ( `allreduce` ).

The start, sin( pi x ), is an eigenvector of the scheme: after k steps it is the same
sine times g^k, whatever the number of ranks. That is what `test_heat.py` checks.

    python heat.py 1000000 500             # one process
    mpiexec -n 4 python heat.py 1000000 500
    errand run --ranks 4 heat.py 1000000 500

It knows nothing about errand: it is an MPI program, run as one.
"""
import os
import sys
import time

import numpy as np
from mpi4py import MPI

NU = 0.4      # dt / h^2: below 1/2, the explicit scheme is stable


def block( n: int, rank: int, size: int ):
    """The points this rank holds, among the n inner points of the grid."""
    return rank * n // size, ( rank + 1 ) * n // size


def solve( n: int, steps: int, comm = MPI.COMM_WORLD ):
    """-> ( this rank's block of the solution, its first index, the energy over all the ranks )."""
    rank, size = comm.Get_rank(), comm.Get_size()
    lo, hi = block( n, rank, size )
    x = np.arange( lo + 1, hi + 1 ) / ( n + 1 )
    u = np.zeros( hi - lo + 2 )              # u[ 0 ] and u[ -1 ]: the neighbours' edge values
    u[ 1 : -1 ] = np.sin( np.pi * x )
    left  = rank - 1 if rank > 0 else MPI.PROC_NULL           # the ends of [0, 1] stay at 0
    right = rank + 1 if rank < size - 1 else MPI.PROC_NULL
    for _ in range( steps ):
        comm.Sendrecv( u[ 1 : 2 ],   dest = left,  recvbuf = u[ -1 : ], source = right )
        comm.Sendrecv( u[ -2 : -1 ], dest = right, recvbuf = u[ : 1 ],  source = left )
        u[ 1 : -1 ] += NU * ( u[ : -2 ] - 2 * u[ 1 : -1 ] + u[ 2 : ] )
    energy = comm.allreduce( float( np.sum( u[ 1 : -1 ] ** 2 ) ) / ( n + 1 ) )
    return u[ 1 : -1 ], lo, energy


def exact( n: int, steps: int, lo: int, hi: int ):
    """The same block, as the scheme makes it from sin( pi x ) in `steps` steps."""
    g = 1 - 4 * NU * np.sin( np.pi / ( 2 * ( n + 1 ) ) ) ** 2
    return g ** steps * np.sin( np.pi * np.arange( lo + 1, hi + 1 ) / ( n + 1 ) )


if __name__ == "__main__":
    n     = int( sys.argv[ 1 ] ) if len( sys.argv ) > 1 else 1_000_000
    steps = int( sys.argv[ 2 ] ) if len( sys.argv ) > 2 else 500
    comm  = MPI.COMM_WORLD
    comm.Barrier()
    t = time.perf_counter()
    u, lo, energy = solve( n, steps, comm )
    seconds = comm.allreduce( time.perf_counter() - t, op = MPI.MAX )
    error = comm.allreduce( float( np.max( np.abs( u - exact( n, steps, lo, lo + len( u ) ) ) ) ), op = MPI.MAX )
    if comm.Get_rank() == 0:
        line = f"{comm.Get_size()} ranks on {MPI.Get_processor_name()}, n = {n}, {steps} steps: " \
               f"{seconds:.3f} s, energy {energy:.6f}, error {error:.1e}"
        print( line, flush = True )
        out = os.environ.get( "ERRAND_OUT_DIR" )          # set by `errand run -o`
        if out:
            with open( os.path.join( out, "heat.txt" ), "w" ) as f:
                f.write( line + "\n" )
    # Where each rank ran: one line each
    print( f"block {lo}..{lo + len( u )} on {MPI.Get_processor_name()}", flush = True )
