# Environments

An environment is a name for a place to run: a stack of **layers**, read outside in, that takes a
command from "run this" to the process that actually runs it.

```python
# errand-envs.py
import errand

errand.envs[ "local" ] = errand.Env( [ errand.Micromamba( "myenv", python = "3.13", requirements = "requirements.txt" ) ] )

errand.envs[ "gpu" ] = errand.Env( [ errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
                                                       pip = [ "jax[cuda13]" ] ) ] )

errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "login.hpc", root = "/scratch/me/proj" ),
                                         errand.Slurm( partition = "gpu", gpus = 1, time = "2:00:00" ),
                                         errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
                                                           pip = [ "jax[cuda13]" ] ) ] )
```

```bash
errand run --env cluster python train.py
```

<Term scene="stack" caption="The cluster environment above, crossed by one run." />

`cluster` reads as *that machine*, then *an allocation on it*, then *the container*, then your
command. There is no separate remote mode, no host file, no second configuration: `Ssh` and `Slurm`
are layers like the others.

Nothing here is hidden from you. The stack is the list of things you would have typed: an ssh, an
`sbatch`, an `apptainer exec`. `errand -v` prints each command as it starts
( [When something breaks](./upkeep#when-something-breaks) ), and `errand shell --env cluster` drops
you into the same place to look around.

## Where they are declared

Environments go in the project's `errand-*.py` files, at its root, conventionally
**`errand-envs.py`**. That file can be committed as long as it names no machine. What only this
machine knows — a host name, a scratch path — goes in an untracked **`errand-vars.py`**, read first,
and the other files ask for it with `errand.value`:

```python
# errand-vars.py -- not tracked
cluster_host = "login.hpc"
```

```python
# errand-envs.py -- tracked
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = errand.value( "cluster_host", "login.hpc" ) ), … ] )
```

See [What only this machine can supply](./configuration#what-only-this-machine-can-supply).

## The layers

Each layer has its page under [Layers](./layers/):

- reaching a machine: [`Ssh`](./layers/ssh), [`Slurm`](./layers/slurm), [`Windows`](./layers/windows),
  [`WindowsBox`](./layers/windows-box);
- what runs there: [`Apptainer`, `Docker`, `Podman`](./layers/containers),
  [`Micromamba`, `Conda`](./layers/micromamba), [`Venv`, `Uv`](./layers/venv),
  [`Nix`, `Guix`](./layers/nix-guix), [`Module`](./layers/module);
- around the command: [`Vars`](./layers/vars), [`Mpi`](./layers/mpi), [`Preload`](./layers/preload);
- and [`Missing`](./layers/missing), for a place this machine cannot reach.

## Looking at them

```bash
errand envs
```

```text
  local                                  micromamba:myenv  <- default
  gpu                                    apptainer:containers/cuda.sif  stale
  boxed                                  docker:errand-demo:1  not built
  cluster                                ssh:login.hpc -> slurm:gpu -> apptainer:containers/cuda.sif  unknown
```

The blank column holds the [tags](./tags), when an environment has some.

`stale` and `not built` need no action from you: the next command that uses the environment builds
it first. `unknown` means only the other machine can say what it has. See
[Keeping environments current](./upkeep).

## Choosing one

```bash
errand run --env gpu python train.py             # by name
errand run --grid=, --env local,gpu python train.py   # several: one run in each
errand run python train.py                       # the default
```

With no `--env`, `errand.default_env = "name"` decides; without it, the first environment the
project declared ( never one a [package provides](#environments-a-package-provides) ); with no
environment at all, the interpreter errand was started with. [Several runs: grids](./matrices) covers
`--grid`. Environments can also carry tags and be chosen by them: see
[Choosing among environments (tags)](./tags).

## Share pieces with plain Python

Project files are ordinary Python, and a stack is an ordinary list:

```python
# errand-envs.py
import errand

CUDA = [ errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
                           flags = [ "--nvccli" ], pip = [ "jax[cuda13]" ] ) ]

errand.envs[ "gpu" ]     = errand.Env( CUDA )
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "/home/me/proj" ) ] + CUDA )
```

`cluster` is `gpu` with a machine in front of it. The file says so, and the two cannot drift apart.

## What goes where

**Requirements belong to the layer that installs them**: a `requirements.txt` for the conda
environment, a `pip` list for the container. That layer is what gets rebuilt when they change.

**Tags are keyword arguments of `Env`**, because they describe the environment as a whole, not one
layer of it.

## Preparing, then running

What a target means is for the place to say: a binary built over there exists only over there, and a
file that imports torch can only be read where torch is. So the machine you type on only chooses the
environments and hands the command over as typed. **Resolving the target, building, and expanding
the grid happen in the environment**, and a typo is reported from there.

That is a **preparation phase**, which writes a *plan* — what will run, what it asks of the machine,
the directories it will write — before a **run phase** runs it. The plan is what the results are
fetched back by, what [`errand status`](./status) reads, and what an allocation is sized from.

The preparation goes through the environment's layers, unless `prepare =` gives it its own. To
prepare in one allocation ( CPUs to compile ) and run in another ( a GPU ), write both lists, and
copy what they share:

```python
# errand-envs.py
login = errand.Ssh( host = "login.hpc", root = "/scratch/me/proj" )
image = errand.Apptainer( image = "containers/cuda.sif" )   # both phases: same compiler, same libraries

errand.envs[ "cluster" ] = errand.Env(
    [ login, errand.Slurm( partition = "gpu", gpus = 1, time = "2:00:00" ), image ],
    prepare = [ login, errand.Slurm( cpus = 16, time = "0:30:00" ), image ],
)
```

Both lists start from the same place: the same `Ssh`, or none. At most one scheduler per list, and
errand checks it. With a single `Slurm`, the
allocation is [held warm](./layers/slurm#held-warm-keep-alive) and the preparation and the run go
into the same job. With `keep_alive = 0`, the preparation is one task and the run a job of its own,
sized from the plan. When no layer is a scheduler, preparing and running are one pass, one process.

## Environments a package provides

A library can declare environments for the projects that use it, so they have nothing to write. A
provider is a function taking the project root, which fills `errand.envs` as a project file does:

```python
# mylib/errand_envs.py
import errand

def provide( root ):
    errand.envs[ "mylib-linux" ] = errand.Env( [ errand.Apptainer( image = "mylib.sif", recipe = "…" ) ] )
```

An installed package declares it under the entry point group `errand.envs`:

```toml
[project.entry-points."errand.envs"]
mylib = "mylib.errand_envs:provide"
```

A program that drives errand itself appends it to `errand.providers` before calling `errand.main`.

- A provider that finds no way to an environment from this machine declares it anyway, as a
  [`Missing`](./layers/missing) that says what to write where.
- A layer the user is expected to complete ( an `Apptainer` without its `image`, a `Micromamba`
  without its `name` ) may be declared incomplete; used as it is, it is refused.
- Providers run after `errand-vars.py`, so they can read `errand.value`, and before the project's
  other files, which have the last word: they can redefine an environment, or change it in place
  ( `errand.envs[ "mylib-linux" ].stack.append( … )` ).
- They run even in a project with no `errand-*.py`. A provider that fails is reported and skipped.

## Next

[Keeping environments current](./upkeep): how an environment gets built, and what errand will not
touch.
