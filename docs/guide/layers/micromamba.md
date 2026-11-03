# Micromamba, Conda

## Micromamba

```python
Micromamba( name, python = None, channels = [ "conda-forge" ],
            packages = [ ], requirements = None, pip = [ ],
            root_prefix = None, executable = None )
```

Wraps with `micromamba -n <name> run`; a no-op if that environment is already active. The
environment is [built and kept current](../upkeep) from what is declared: `python`, `channels`,
`packages`, a `requirements` file relative to the project root, and `pip` on top.

`executable` is the micromamba binary to call, for a machine where it is not on `PATH`, and
`root_prefix` the directory `-n <name>` resolves against. Over [`Ssh`](./ssh) only what is declared is
passed — nothing is guessed from this machine's home — and behind a [`Slurm`](./slurm) layer the
command runs on a compute node that reads no rc file at all: state both there.

::: info Why `micromamba` is pinned to a root prefix
The shell hook exports `MAMBA_ROOT_PREFIX` from an rc file, which only *interactive* shells read.
Started from a Makefile, from cron or from any plain subprocess, micromamba instead falls back to
the envs directory beside its own binary — so `-n x` would silently name a different environment
than the same command typed by hand. The layer pins it.
:::

## Conda

```python
Conda( … )      # the same arguments as Micromamba
```
