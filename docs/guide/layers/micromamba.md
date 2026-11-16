# Micromamba, Conda

## Micromamba

```python
Micromamba( name, python = None, channels = [ "conda-forge" ], packages = [ ],
            requirements = None, pip = [ ], root_prefix = None, executable = None )
```

Runs the command as `micromamba -n <name> run …`, or as it is when that environment is already
active.

```python
errand.Env( [ errand.Micromamba( "myenv", python = "3.13", packages = [ "numpy", "mpi4py" ],
                                 requirements = "requirements.txt" ) ] )
```

| | |
|---|---|
| `name` | the environment. An existing one is [adopted as it is](../upkeep#what-is-already-there-is-adopted-not-rebuilt) |
| `python`, `channels`, `packages` | what it is created with |
| `requirements` | a file relative to the project root, installed with pip |
| `pip` | more pip packages, on top |
| `executable` | the micromamba binary, on a machine where it is not on `PATH` ( a compute node ) |
| `root_prefix` | the directory `-n <name>` resolves against |

Over [`Ssh`](./ssh) only what is declared is used: nothing is guessed from this machine's home.
Behind a [`Slurm`](./slurm) layer the command runs on a compute node that reads no rc file at all, so
state `executable` and `root_prefix` there.

::: info Why the root prefix is pinned
The shell hook exports `MAMBA_ROOT_PREFIX` from an rc file, which only interactive shells read.
Started from a Makefile, from cron or from any plain subprocess, micromamba falls back to the envs
directory beside its own binary, so `-n x` can name a different environment than the same command
typed by hand. The layer pins it: `root_prefix`; else, on this machine, `MAMBA_ROOT_PREFIX`, else
`~/.mamba` or `~/micromamba` when it holds an `envs/`.
:::

## Conda

```python
Conda( … )      # the same arguments, through `conda`
```
