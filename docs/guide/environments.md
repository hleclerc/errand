# Environments

An environment is a stack of **layers** describing how to get from "run this program" to the actual
subprocess, plus **[tags](./tags)** saying what it is. There is always a current interpreter; most
layers are a way to override it.

Environments are declared in [`errand-envs.py`](./configuration), at the root of the project — they
depend on who runs, and on what machine, so that file is not versioned:

```python
# errand-envs.py
import errand

errand.envs[ "local" ] = errand.Env( [ errand.Micromamba( "myenv", python = "3.13", requirements = "requirements.txt" ) ],
                                     driver = "jax" )

errand.envs[ "gpu" ] = errand.Env( [ errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
                                                       pip = [ "jax[cuda13]" ] ) ],
                                   driver = "jax", cuda = True )

errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "/home/me/proj" ),
                                         errand.Slurm( partition = "gpu", gpus = 1, time = "2:00:00" ),
                                         errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
                                                           pip = [ "jax[cuda13]" ] ) ],
                                       driver = "jax", cuda = True )
```

<Term scene="stack" caption="The cluster environment above, crossed by one run." />

Read a stack outside in: `cluster` is *that machine*, then *an allocation on it*, then *the
container*, then your command. There is no separate remote mode, no host file, no second config —
`Ssh` and `Slurm` are layers like the others.

## The layers

| layer | what it does |
|---|---|
| `Micromamba( name, python =, channels =, packages =, requirements =, pip = )` | wraps with `micromamba -n <name> run`; a no-op if that environment is already active |
| `Conda( … )`, `Venv( python =, requirements =, pip = )`, `Uv( path =, python =, … )` | the same idea, other tools |
| `Nix( flake =, shell = )`, `Guix( manifest =, packages = )` | `nix develop -c …`, `guix shell -- …` |
| `Module( "gcc/13", "cuda/12" )` | Lmod / environment modules, the way a cluster picks a toolchain |
| `Apptainer( image, recipe =, flags =, mounts =, pip =, fakeroot =, scratch =, build_flags = )` | wraps with `apptainer exec`, using the container's own interpreter. The last three are about *building* it rather than entering it |
| `Docker( image, recipe =, flags =, mounts =, pip =, user = )`, `Podman( … )` | likewise |
| `Ssh( host, root =, python =, options = )` | must be first; everything after it runs on that machine. `options` go to ssh *and* rsync — a port, an identity, a jump host |
| `Slurm( partition =, nodes =, cpus =, gpus =, time =, account =, extra = )` | goes through `srun`, or `sbatch` in [batch mode](./detached) |
| `Vars( { … } )` | environment variables for the child process |

Slurm is the only batch system with a layer of its own so far. errand does however *recognize*
being inside a PBS, OAR, LSF, SGE or Flux allocation, and [stands down from
queuing](./machine#when-somebody-else-owns-the-machine) when it is.

Every argument is spelled out in the [layer reference](/reference/layers).

## Two rules about what goes where

**Requirements belong to the layer that installs them** — a `requirements.txt` for the conda
environment, a `pip` list for the container — because that is the thing that has to be rebuilt when
they change.

**Tags are keyword arguments**, because they belong to the environment as a whole rather than to any
one layer of it.

## Share pieces with plain Python

Project files are ordinary Python. A layer stack is an ordinary list:

```python
# errand-envs.py
import errand

CUDA = [ errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
                           flags = [ "--nvccli" ], pip = [ "jax[cuda13]" ] ) ]

errand.envs[ "gpu" ]     = errand.Env( CUDA,                                                    driver = "jax", cuda = True )
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "…" ) ] + CUDA, driver = "jax", cuda = True )
```

That `cluster` is `gpu` *plus a machine in front of it* is visible in the file, and the two cannot
drift apart — which is the point.

The same trick covers the case where one platform has apptainer and another does not: two
environments, the same tags, the same fingerprint, the same output paths, only the container engine
differs. Choosing where to run has nothing to say about which engine holds the image.

## Looking at them

```bash
errand --envs
```

```text
  local    driver=cpu                    micromamba:demo -> vars                     <- default
  gpu      cuda  driver=cuda             apptainer:cuda.sif -> vars                  stale
  boxed    boxed  driver=cpu             docker:errand-demo:1 -> vars                not built
  box      cuda  driver=cuda  remote     ssh:gpu-box -> apptainer:cuda.sif -> vars   unknown
  cluster  cuda  driver=cuda  fp=64  remote  ssh:login.hpc -> slurm:gpu -> …         unknown
```

`unknown` is honest rather than optimistic: only the other machine can say what it has.

You do not have to act on `stale` or `not built` — see [Keeping them
current](./upkeep).

## Choosing one

```bash
errand -k bench --env gpu            # by name
errand -k bench --driver cuda        # by tag; every tag name becomes a flag
errand -k bench --fp 32
errand -k bench -t 'cuda & !remote'  # by expression
errand -k bench --env gpu,cluster    # both: a comma is a matrix here too
```

Use `--env NAME` when you want exactly one and mean it. Everything else is in [Tags](./tags).

With nothing asked for, `errand.default_env = "name"` decides; with none, the first one declared is used;
with no environment declared at all, errand runs in the interpreter you started it with.

## Next

[Keeping them current](./upkeep) — how an environment gets built, and what errand refuses to touch.
