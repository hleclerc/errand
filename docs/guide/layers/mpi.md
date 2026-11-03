# Mpi

```python
Mpi( launcher = "mpiexec", np = "-n", flags = [ ] )
```

How the place starts several processes of one program, for a place where it is not the usual one —
rarely needed. It wraps nothing: `errand` runs once, and only what asks for ranks ( `--ranks 4`,
`ranks = 4` ) is started under `launcher np N *flags`, one process per rank.

```python
errand.Env( [ …, errand.Mpi( "mpirun", flags = [ "--oversubscribe" ] ) ] )
```

Without it: inside a Slurm job, `srun` ( see [Slurm, several ranks](./slurm#several-ranks) );
elsewhere, the `mpiexec` beside the interpreter of the place, else the one on its PATH. See
[Several processes (MPI)](../mpi).
