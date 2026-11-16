# Mpi

```python
Mpi( launcher = "mpiexec", np = "-n", flags = [ ] )
```

How the place starts several processes of one program, when it is not the usual way. Rarely needed.

```python
errand.Env( [ …, errand.Mpi( "mpirun", flags = [ "--oversubscribe" ] ) ] )
```

It wraps nothing: errand runs once in the place, and only what asks for ranks ( `--ranks 4`, an
entry's `ranks = 4` ) is started as `launcher np N *flags …`, one process per rank.

Without it, errand picks the launcher itself: inside a Slurm job, `srun`
( see [Slurm, several ranks](./slurm#several-ranks) ); elsewhere, the `mpiexec` beside the
interpreter of the place, else the one on its `PATH`. With it, its launcher wins, even under Slurm.

Its place in the stack says where the launcher runs: before a container, outside it ( each rank
enters the container ); after a container, inside it.
See [Several processes (MPI)](../mpi).
