"""The heat solver as errand entries: each body is the program of ONE rank.

    errand run 'test_heat.py::*'                 # here, with the mpiexec of the environment
    errand run --env cluster 'test_heat.py::*'   # in the container, ranks over the allocation's nodes

`ranks = 4` is what the entry needs; `--ranks 8` on the command line overrides it.
"""
from errand import bench, Param, test


if test( "the parallel solution is the exact one", ranks = 4 ):
    import numpy as np
    from mpi4py import MPI
    from heat import exact, solve

    comm = MPI.COMM_WORLD
    assert comm.Get_size() > 1, "one rank: nothing was exchanged"
    n, steps = 1000, 200
    u, lo, energy = solve( n, steps, comm )
    assert np.max( np.abs( u - exact( n, steps, lo, lo + len( u ) ) ) ) < 1e-12
    # every rank has the same total: the allreduce reached all of them
    assert comm.allgather( energy ) == [ energy ] * comm.Get_size()


if p := bench( "heat", ranks = 4, n = Param( 1_000_000, help = "grid points" ),
               steps = Param( 500, help = "time steps" ) ):
    import time
    from mpi4py import MPI
    from heat import solve

    comm = MPI.COMM_WORLD
    comm.Barrier()
    t = time.perf_counter()
    u, lo, energy = solve( p.n, p.steps, comm )
    seconds = comm.allreduce( time.perf_counter() - t, op = MPI.MAX )
    # the results kept are rank 0's
    p.results[ "seconds" ] = seconds
    p.results[ "ranks" ]   = comm.Get_size()
    p.results[ "energy" ]  = energy
