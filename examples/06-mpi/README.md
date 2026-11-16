# 06 — a parallel computation: MPI, Slurm, Apptainer

An MPI program that exchanges data between its ranks, run here and on a cluster in an image.

```
heat.py               the heat equation on [0, 1], split over the ranks: halo swaps, an allreduce
test_heat.py          two entries whose bodies are the program of one rank: a test, a benchmark
errand-envs.py        `here` ( micromamba, MPICH ) and `cluster` ( ssh, Slurm, Apptainer )
containers/mpi.def    the image: Ubuntu, Open MPI with PMIx, mpi4py
```

`heat.py` knows nothing about errand: `mpiexec -n 4 python heat.py` runs it too.

## Here

```bash
cd examples/06-mpi
errand setup --env here                 # the micromamba environment, once
errand run --ranks 4 heat.py            # mpiexec -n 4, from that environment
errand run 'test_heat.py::*'            # each entry on the 4 ranks it asks for
errand run --ranks 2 'test_heat.py::heat' --n 2000000
```

## On a cluster

Change the host, the root and, if needed, the partition in `errand-envs.py`, then:

```bash
errand setup --env cluster              # the image, built over there
errand run --env cluster --ranks 8 heat.py 100000000 200
errand run --env cluster 'test_heat.py::*'
```

errand runs once, in the image, on the first node of a 2-node allocation. The ranks are started
outside the image by the allocation's `srun`, over both nodes, and each enters the image on its
node. Every `block … on <node>` line says where a rank ran.

The walkthrough: [Tutorial 4 · A parallel computation](https://hleclerc.github.io/errand/tutorials/parallel).
