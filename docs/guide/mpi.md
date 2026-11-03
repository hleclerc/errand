# Several processes (MPI)

A distributed program is N processes of one program, started together by an MPI launcher. errand
starts them for you, here or over the nodes of a cluster, and brings back one result.

## The command line

```bash
errand run --ranks 4 parallel.py                       # a script, under `mpiexec -n 4`
errand run --ranks 8 --cpus 2 'tests/test_dist.py::*'  # entries: 8 processes of 2 cores each
errand run --env cluster --ranks 64 'tests/test_dist.py::*'   # the same, over the nodes of an allocation
```

`--ranks N` runs the target as N processes, each running the whole of it: a script is started
N times by the MPI launcher of the place, and so is the body of each entry. That body is the program
of one rank — `from mpi4py import MPI` and `MPI.COMM_WORLD` inside it, nothing to write around it.
With ranks, `--cpus`, `--gpus` and `--ram` say what **one rank** needs ( one core when unsaid ).

The same command runs here, on another machine and on a cluster: nothing about the launcher goes in
the environment. Here, it is the `mpiexec` beside the interpreter of the place ( the MPI of a conda /
micromamba environment, the one mpi4py was built against ), else the one on its PATH. Under
[Slurm](/guide/layers/slurm), the allocation is asked for one task per rank, errand runs in it
**once**, and starts the ranks with `srun` — on every node of the allocation, spread as the
environment says ( `Slurm( nodes = 2, ntasks_per_node = 4 )` ).

## An entry that says it

An entry that is only meaningful on several processes can say so itself, as a default
`--ranks` overrides:

```python
if test( "distributed", ranks = 4 ):
    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    assert comm.allreduce( 1 ) == comm.Get_size()
```

## What comes back

One entry: the ranks' lines arrive prefixed by the rank ( `[2] …` ), each rank
writes `rank-<r>.json` beside `output.txt`, and the entry fails when one rank failed
( `rank 2: AssertionError: …` ), is skipped when they all skipped. Its results are rank 0's. A rank
that fails calls `MPI.COMM_WORLD.Abort` once its record is written ( when mpi4py is loaded ), so
the others are not left waiting in a collective.

## Resources and launchers

For the [queue](./machine), an entry of N ranks takes N times what one rank asks. A place whose launcher is not
one of these names it with the [`Mpi`](/guide/layers/mpi) layer: `errand.Mpi( "mpirun", flags =
[ "--oversubscribe" ] )`.
