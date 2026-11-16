# 4 · A parallel computation

An MPI program whose ranks talk to each other: first on your laptop, then on two nodes of a Slurm
cluster, inside an Apptainer image. The code does not change between the two; only `--env` does.

::: info What was run
The local part was run as written, on a Mac with MPICH from conda-forge. The cluster part was run on
a Slurm cluster ( Apptainer 1.4, `srun --mpi=pmix` with PMIx 5 ), over two of its nodes; the host, the paths and the node names are changed, and the
`srun` line is shortened. The same image also ran on a second cluster ( Singularity 3.8, PMIx 3,
Omni-Path, jobs submitted and watched ): what that one needed is under
[What the image needs](#what-the-image-needs) and [Jobs that wait in the queue](#jobs-that-wait-in-the-queue).
:::

The files are in
[`examples/06-mpi`](https://github.com/hleclerc/errand/tree/main/examples/06-mpi).

## The program

`heat.py` solves the heat equation on [0, 1]. Each rank holds one block of the grid, and one
"ghost" value at each end for its neighbours' edges:

```python
def solve( n, steps, comm = MPI.COMM_WORLD ):
    rank, size = comm.Get_rank(), comm.Get_size()
    lo, hi = block( n, rank, size )
    u = np.zeros( hi - lo + 2 )              # u[ 0 ] and u[ -1 ]: the neighbours' edge values
    u[ 1 : -1 ] = np.sin( np.pi * np.arange( lo + 1, hi + 1 ) / ( n + 1 ) )
    left  = rank - 1 if rank > 0 else MPI.PROC_NULL
    right = rank + 1 if rank < size - 1 else MPI.PROC_NULL
    for _ in range( steps ):
        comm.Sendrecv( u[ 1 : 2 ],   dest = left,  recvbuf = u[ -1 : ], source = right )
        comm.Sendrecv( u[ -2 : -1 ], dest = right, recvbuf = u[ : 1 ],  source = left )
        u[ 1 : -1 ] += NU * ( u[ : -2 ] - 2 * u[ 1 : -1 ] + u[ 2 : ] )
    energy = comm.allreduce( float( np.sum( u[ 1 : -1 ] ** 2 ) ) / ( n + 1 ) )
    return u[ 1 : -1 ], lo, energy
```

Two kinds of communication: point to point between neighbours ( `Sendrecv`, every step ), and
collective ( `allreduce`, at the end ). The start is chosen so that the exact discrete answer is
known: whatever the number of ranks, the error must be at round-off level.

It is a plain MPI program. errand does not wrap it, and `mpiexec -n 4 python heat.py` runs it too.

## The places

```python
# errand-envs.py
errand.envs[ "here" ] = errand.Env( [
    errand.Micromamba( "errand-mpi-demo", python = "3.12", packages = [ "numpy", "mpi4py", "mpich" ] ),
] )

errand.envs[ "cluster" ] = errand.Env( [
    errand.Ssh( host = "login.hpc", root = "/scratch/me/mpi-demo" ),      # shared with the compute nodes
    errand.Slurm( nodes = 2, ntasks_per_node = 4, time = "0:30:00" ),
    errand.Apptainer( image = "containers/mpi.sif", recipe = "containers/mpi.def" ),
] )
```

Neither says how many processes to start. That is the work's to say, with `--ranks`, or with
`ranks =` on an entry. The environment says only where the processes go: 2 nodes, 4 tasks on each.

## Here

```bash
errand setup --env here
errand run --ranks 3 -o heat.py 300000 100
```

```text
  $ …/envs/errand-mpi-demo/bin/mpiexec -n 3 …
3 ranks on my-laptop, n = 300000, 100 steps: 0.016 s, energy 0.500000, error 6.7e-15
block 100000..200000 on my-laptop
block 200000..300000 on my-laptop
block 0..100000 on my-laptop
PASS heat.py (heat.py)
```

`--ranks 3` starts the script under the `mpiexec` that sits beside the environment's Python: the
MPI mpi4py was built against. The three ranks' output arrives in one stream, as the launcher
gathers it. `-o` gives rank 0 a directory to write `heat.txt` into ( `$ERRAND_OUT_DIR` ).

## Entries on several ranks

`test_heat.py` declares two entries. The body of each is the program of **one** rank:

```python
if test( "the parallel solution is the exact one", ranks = 4 ):
    from mpi4py import MPI
    from heat import exact, solve
    comm = MPI.COMM_WORLD
    u, lo, energy = solve( 1000, 200, comm )
    assert np.max( np.abs( u - exact( 1000, 200, lo, lo + len( u ) ) ) ) < 1e-12
    assert comm.allgather( energy ) == [ energy ] * comm.Get_size()

if p := bench( "heat", ranks = 4, n = Param( 1_000_000 ), steps = Param( 500 ) ):
    …
    p.results[ "seconds" ] = seconds          # the results kept are rank 0's
```

```bash
errand run 'test_heat.py::*'
errand run --ranks 2 'test_heat.py::heat' --n 2000000      # --ranks overrides the entry's 4
```

errand stays in one process and starts the ranks. Each rank imports the file and runs only the body
of that entry. What comes back is one result for the entry:

- each line is prefixed by its rank ( `[2] …` );
- the entry fails if one rank fails ( `rank 2: AssertionError: …` ), and that rank aborts the others
  so that none waits forever in a collective;
- the numbers recorded are rank 0's.

→ [Several processes (MPI)](/guide/mpi)

## On two nodes, in an image

```bash
errand setup --env cluster                                  # the image, built over there
errand run --env cluster --ranks 8 heat.py 10000000 200
```

```text
  $ srun --overlap --mpi=pmix --nodes 2 --ntasks-per-node 4 --ntasks 8 apptainer exec /scratch/me/mpi-demo/containers/mpi.sif python /scratch/me/mpi-demo/heat.py 10000000 200   ( outside the container )
8 ranks on node15, n = 10000000, 200 steps: 5.292 s, energy 0.500000, error 1.8e-14
block 0..1250000 on node15
block 1250000..2500000 on node15
block 2500000..3750000 on node15
block 3750000..5000000 on node15
block 5000000..6250000 on node16
block 6250000..7500000 on node16
block 7500000..8750000 on node16
block 8750000..10000000 on node16
PASS heat.py (heat.py)
```

What happened, from the outside in:

1. Slurm gave an allocation of 2 nodes, with an errand agent on the first one ( node15 ).
2. That agent entered the image once, and errand ran in it, on node15 only.
3. errand saw a container in the stack, with Slurm in front of it. `srun` is not in the image, and an
   `mpiexec` of the image would put all 8 ranks on node15. So errand asked the agent **outside** the
   image to start the ranks.
4. That agent ran `srun` over the whole allocation. Each of the 8 tasks entered the image on its own
   node, and started `heat.py` there.
5. Inside the image, Open MPI got its rank and its peers from Slurm, through PMIx, and the ranks on
   node15 and node16 talked over the cluster's network.

This is the usual way to run MPI in Apptainer on a cluster. Sites call it the "hybrid model".

The entries run the same way:

```bash
errand run --env cluster 'test_heat.py::*'
```

### What the image needs

- **An MPI that speaks the PMI that `srun` offers.** errand passes `srun --mpi=pmix` for Open MPI and
  `--mpi=pmi2` for MPICH; `Slurm( mpi = "…" )` says otherwise. `srun --mpi=list` on the cluster
  lists what it supports. The image in this example uses Open MPI from Ubuntu, which is built with
  PMIx.
- **The cluster's network, for speed.** An MPI built in the image works over TCP everywhere. On
  InfiniBand or Slingshot, use your site's base image, or an MPI built against the same fabric
  libraries. A fabric library from the distribution may not even start: on Omni-Path with GPU
  nodes, Ubuntu's `libpsm2` aborts with *CUDA version of hfi1 driver is loaded with non-CUDA version
  of psm2 library*. TCP then still works, with the variables given to the ranks by a `Vars` after
  the container:

  ```python
  errand.Vars( { "OMPI_MCA_pml": "ob1", "OMPI_MCA_mtl": "^psm2,ofi", "OMPI_MCA_btl": "self,vader,tcp" } )
  ```
- **Shared memory between the ranks of a node.** Each rank enters the image on its own, in a user
  namespace of its own, so they cannot map each other's memory ( CMA ). Open MPI then warns once per
  rank, unless the image says to copy instead: `OMPI_MCA_btl_vader_single_copy_mechanism=none` in its
  `%environment`, as `containers/mpi.def` does.
- **The project directory, mounted.** The project must sit on a filesystem that every node sees, and
  that Apptainer mounts. `$HOME` is mounted by default; for `/scratch`, add
  `flags = [ "--bind", "/scratch" ]` to the layer if your site does not already mount it. Without
  it, errand stops with *the project root … is not seen here*.

### Jobs that wait in the queue

With `Slurm( watch = … )` ( or `--batch` ), the job is submitted and asked about, and the work runs
in a single pass on its nodes. Its size is then fixed before errand reads the entries, so an entry's
own `ranks = 4` cannot size it: give `--ranks` on the command line.

```bash
errand run --env cluster --ranks 4 'test_heat.py::*'
```

A site whose login nodes must load a module to run images ( `module load singularity` ) puts the
`errand.Module` **before** `Slurm`: it is then loaded both where errand checks the image and in the
job. A site without internet on its nodes builds the image elsewhere and installs it where images
may run from: `build_on`, `install` and `run_from` on the container layer
( [Containers](/guide/layers/containers) ).

### When the launcher is inside the image

To start the ranks with the image's own `mpiexec`, all on the first node, put an `errand.Mpi`
**after** the container:

```python
[ errand.Ssh( … ), errand.Slurm( … ), errand.Apptainer( … ), errand.Mpi( "mpiexec" ) ]
```

Where `Mpi` stands in the stack says where the ranks start: before the container, outside it;
after it, inside it.

## Ctrl-C

Ctrl-C reaches the agent outside the image, which stops `srun` and, through it, every rank on every
node: nothing is left running on either node.

Closing the laptop, on the other hand, leaves the run going: `errand attach` follows it again, and
brings back what it wrote.

## A rebuilt image

`errand setup --env cluster` after a change to `mpi.def` rebuilds the image, even while the allocation
is kept warm. The agent that lived in the old image leaves by itself, and the next command starts one
in the new image.

## Next

[Several processes (MPI)](/guide/mpi) · [Slurm](/guide/layers/slurm) ·
[Containers](/guide/layers/containers) · [Mpi](/guide/layers/mpi)
