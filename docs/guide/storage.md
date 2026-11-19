# Where errand writes

errand writes in three kinds of places, on every machine it works on:

| place | what | size |
|---|---|---|
| **the project**: `errand-outputs/` at its root ( over there, in the project's copy ) | every run's record, what was built, errand's bookkeeping | grows with use |
| **per user**: `~/.cache/errand/`, or `$ERRAND_CACHE_DIR` | errand's own sources and, if needed, a Python for itself; the agents, the hub, warm allocations and virtual machines; the list of machines work was sent to | a few MB, plus a Python if errand made one |
| **per machine**: `errand-queue-<uid>-<host>/` in `$XDG_RUNTIME_DIR`, else the temporary directory | the claims of [machine sharing](./machine) | a few files |

Then come the environments your layers build: a micromamba environment, a venv, a container
image. They go where the declaration says, and each layer has a parameter to choose that.

Everything that grows belongs to a project, so you choose where it goes. The per-user directory holds
only what is live, and cleans itself up ( see [What is running](./status) ).

## The project: `errand-outputs/`

```text
errand-outputs/
  runs/       the record of every run
  builds/     what errand built: the Windows images, the records of what was set up
  state/      errand's bookkeeping: plans, history, the output kept for `errand attach`
  caches/     the caches of the libraries the runs use, one directory each ( $ERRAND_CACHES )
```

What each holds is in [Results and records](./output).

Three settings move it, from the broadest to the most specific:

| setting | scope | example |
|---|---|---|
| `errand.configure( outputs_directory = … )` | the project, on every machine | `"errand-outputs"` ( the default ), or `"/data/me/proj-out"` |
| `ERRAND_OUTPUTS_DIR` | one machine: an environment variable | `export ERRAND_OUTPUTS_DIR=/scratch/me/proj-out` |
| `Ssh( errand_outputs_directory = … )` | the project's copy on that host | `"/scratch/me/proj-out"` |

A relative path is from the project root. With `errand_outputs_directory`, the project's copy over
there holds a symlink `errand-outputs` to the directory, so nothing else changes. What the copy's
own `errand-outputs/` already held is moved there at the next push. The two other settings move
nothing: a run writes to the new place, and the old one stays as it was.

`builds/` can go somewhere else on its own, with `errand.configure( builds_directory = … )`: another
disk, or a directory several projects share, so that they share one Windows image. It is the same
path on every machine, so an absolute path must exist on each of them.

## Over Ssh: the project's copy

`Ssh( root = … )` is where the project is copied over there. **Without it, the copy goes to the same
path as here**: `/home/me/proj` here means `/home/me/proj` over there. On a cluster, that is usually
the home directory, so you will want `root` to point at a work or scratch disk:

```python
errand.Ssh( host = "cluster", root = "/scratch/me/proj" )
```

The copy holds everything that follows from it: `errand-outputs/` ( unless
`errand_outputs_directory` says otherwise ), a [`Uv`](./layers/venv) venv, and a container image
declared with a relative path.

## Environments

Each layer that builds something says where it goes:

| layer | parameter | default |
|---|---|---|
| [`Micromamba`](./layers/micromamba) | `root_prefix`: environments and package cache | `$MAMBA_ROOT_PREFIX`, else `~/.mamba` or `~/micromamba` |
| [`Uv`](./layers/venv) | `path` | `.venv`, in the project |
| [`Venv`](./layers/venv) | `python`: the venv is the directory above its `bin/` | — |
| [`Apptainer`](./layers/containers) | `image`: relative to the project, or absolute | — |
| [`Apptainer`](./layers/containers) | `scratch`: where the build unpacks and downloads | apptainer's own: `/tmp` and `~/.apptainer/cache` |
| [`Windows`](./layers/windows) | `builds_directory`, see above | `errand-outputs/builds/windows/` |

## The per-user directory: `~/.cache/errand/`

```text
~/.cache/errand/
  src/<key>/         errand's sources, on a machine reached by Ssh: about 1 MB per checkout that sent them
  python/            a Python for errand alone, when the machine had no usable one
  uv/  uv-python/    the uv errand fetched to make it, and the Python uv downloaded
  agents/<name>/     one directory per agent: its socket, its lock, what it started
  hub-<key>/         the hub that keeps the connections of this machine's commands
  alloc/<name>/      a Slurm allocation kept warm, on the cluster
  vm/  vm-agent/     the virtual machines booted from here: state, locks, the keeper
  ledger/            the machines this one sent work to: where `errand status` looks
  seen/              one link per run made on this machine, to the run's directory
```

The sources are small. The Python errand may make for itself is tens of MB, once. The rest is live
and goes away by itself: an agent with nothing to do stops, a warm allocation is released, a
machine nobody used for a day leaves nothing here, and a machine not reached for two weeks is no
longer asked. Setting up a [`WindowsBox`](./layers/windows-box) also leaves an `msys2-rsync/`: the rsync
it installs on the Windows machine, downloaded once.

By default it is in the home directory, on purpose: on a cluster, the home is what the login node
and the compute nodes share, so what errand finds or makes on the login node is what a job uses on
a node. `ERRAND_CACHE_DIR` puts it elsewhere on a machine. Set it in your shell profile on that
machine ( `~/.bashrc`, `~/.zshrc` ):

```bash
export ERRAND_CACHE_DIR=/work/me/errand-cache
```

It is a setting of the machine, not of a project: the agents on a machine serve every project that
reaches it. errand reads it over there through the same interactive shell it runs every remote
command in, so the profile is enough, even if it stops early for non-interactive shells. On a
cluster, pick a directory that the compute nodes also see. Sockets in a deep directory are fine:
when their path is too long for the system, errand reaches them through a short link in
`/tmp/errand-<uid>/`.

Removing this directory is always safe when nothing is running: it undoes everything errand made
for itself. Moving it is the same: errand remakes what it needs at the new place.

## The tools' own caches

Some tools that errand runs keep caches of their own in the home directory: `pip` in `~/.cache/pip`,
`uv` in `~/.cache/uv`, apptainer in `~/.apptainer/cache`. errand leaves them alone. To move them,
set their variables in your account's environment over there ( `~/.bashrc`, say ):

```bash
export PIP_CACHE_DIR=/scratch/me/cache/pip
export UV_CACHE_DIR=/scratch/me/cache/uv
export APPTAINER_CACHEDIR=/scratch/me/cache/apptainer
```

For apptainer builds, [`Apptainer( scratch = … )`](./layers/containers) does that for you.

## A library's caches: `$ERRAND_CACHES`

Every run gets `ERRAND_CACHES`, the absolute path of `errand-outputs/caches/` on the machine it runs
on. A library that keeps a cache ( compiled kernels, say ) puts it in a directory named after itself,
`$ERRAND_CACHES/<name>`, and uses its own default when the variable is not set -- a run by hand.
An explicit setting of the library wins over both: loom reads `LOOM_CACHE_DIR`, then
`$ERRAND_CACHES/loom`, then `~/.cache/loom`. Each machine keeps its own; nothing there is synced.

A cache that keeps the format `errand-cache/1` at its root ( `errand-cache.json`, and a journal per process ) is
tidied by errand: the first run of a command, at most once a day, removes the entries a dependency of which changed or
went, then the shared ones nothing left needs ( ADR 0020 ). `errand caches` does it at once and says what each cache
holds; `--dry-run` only says it. A cache without the format is never touched.

## A directory tagged as a cache

A directory that holds a [`CACHEDIR.TAG`](https://bford.info/cachedir/) ( first line
`Signature: 8a477f597d28d172789f06886806bc55` ) is a zone wherever it is, on either side: never sent,
never removed, never reported as a change, as a `build` zone. pytest, cargo and ruff write that tag;
loom writes it in a package's catalogue and in its caches. A library that writes a directory inside
the project, at run time, tags it, and errand leaves it alone without being told.

A directory that a run made, that the project does not have, and that is not tagged nor in a zone, is
not errand's to remove: a push says it once, with what it holds, and then leaves it ( ADR 0019 ).

## A small home, in short

```python
errand.Ssh( host = "cluster",
            root = "/scratch/me/proj",                         # the project's copy
            errand_outputs_directory = "/scratch/me/proj-out" ) # runs, builds, state
errand.Micromamba( "proj", root_prefix = "/scratch/me/mamba" )  # environments
errand.Apptainer( "proj.sif", recipe = "proj.def", scratch = "/scratch/me/tmp" )
```

And in your shell profile over there, `ERRAND_CACHE_DIR` and the tools' cache variables:

```bash
export ERRAND_CACHE_DIR=/scratch/me/errand-cache
export PIP_CACHE_DIR=/scratch/me/cache/pip UV_CACHE_DIR=/scratch/me/cache/uv
```
