# Several processes (MPI)

```bash
errand run --ranks 4 parallel.py                  # mpiexec -n 4, here
errand run --env cluster --ranks 64 parallel.py   # srun, over the nodes of an allocation
errand run --ranks 8 --cpus 2 parallel.py         # 8 processes of 2 cores each
```

`--ranks N` starts the target as N processes of one program, with the launcher of the place, and
brings back one result. The script is the program of one rank: `from mpi4py import MPI` and
`MPI.COMM_WORLD` inside it, nothing to write around it.

## The launcher is the place's

The same command runs here, on another machine and on a cluster. Nothing about the launcher goes in
the environment:

- **here or over ssh**, the `mpiexec` beside the interpreter of the place ( the MPI of a conda or
  micromamba environment, the one mpi4py was built against ), else the one on its `PATH`;
- **under [Slurm](/guide/layers/slurm)**, the allocation is asked for one task per rank, errand runs
  in it once, and starts the ranks with `srun`, spread over the nodes as the environment says
  ( `Slurm( nodes = 2, ntasks_per_node = 4 )` );
- **anything else** is named with the [`Mpi`](/guide/layers/mpi) layer:
  `errand.Mpi( "mpirun", flags = [ "--oversubscribe" ] )`.

## In a container

errand runs inside the container, but `srun` is not in an image, and an `mpiexec` of the image would
start every rank on one node. So when a Slurm allocation, or an `Mpi` layer, comes **before** the
container in the stack, the ranks start outside it: the agent out there runs the launcher, and each
rank enters the container on its own node.

```text
srun --mpi=pmix --nodes 2 --ntasks 8 apptainer exec image.sif python parallel.py
```

The MPI of the image gets its rank from Slurm ( PMIx for Open MPI, PMI-2 for MPICH ). An `Mpi` layer
placed **after** the container is the image's own, and starts the ranks inside it, on one node.
Only errand's variables and `PYTHONPATH` are passed to the launcher out there; each rank gets the
container's environment by entering it again. → [Tutorial 4 · A parallel computation](/tutorials/parallel)

With no launcher to be found, the run is skipped and says what to install:
`micromamba install -c conda-forge mpich mpi4py`, or an `Mpi` layer.

## What one rank needs

With `--ranks`, `--cpus`, `--gpus` and `--ram` say what **one rank** needs ( one core when unsaid ).
In the [machine's queue](./machine), the run takes N times that; under Slurm, it is what each task
is asked for.

## An entry that needs ranks

An [entry](./declaring-work) that only makes sense on several processes says so, as a default
`--ranks` overrides:

```python
if test( "distributed", ranks = 4 ):
    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    assert comm.allreduce( 1 ) == comm.Get_size()
```

For an entry, each rank runs its body. The ranks' lines arrive prefixed by the rank ( `[2] …` ),
each rank writes `rank-<r>.json` beside `output.txt`, and the entry fails when one rank failed
( `rank 2: AssertionError: …` ), is skipped when all of them skipped. Its results are rank 0's. A
rank that fails calls `MPI.COMM_WORLD.Abort` once its record is written ( when mpi4py is loaded ),
so the others are not left waiting in a collective.

## Next

[Sharing a machine](./machine).
