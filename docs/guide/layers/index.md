# Layers

A layer wraps the command that is about to run. An [environment](../environments) is a stack of
them, read **outside in**:

```python
# errand-envs.py
import errand

errand.envs[ "cluster" ] = errand.Env( [
    errand.Ssh( host = "login.hpc", root = "/scratch/me/proj" ),   # that machine
    errand.Slurm( time = "2:00:00" ),                              # an allocation on it
    errand.Apptainer( image = "containers/cuda.sif" ),             # the container in it
    errand.Vars( { "OMP_NUM_THREADS": "8" } ),                     # the child's variables
] )
```

## The list

| layer | what it does |
|---|---|
| [`Ssh`](./ssh) | another machine. First in the stack; the project is pushed there and the results brought back |
| [`Slurm`](./slurm) | an allocation, with an agent on its first node; `sbatch` under [`--batch`](../detached) |
| [`Windows`](./windows) | a Windows virtual machine errand installs, boots and stops; first, or right after its `Ssh` |
| [`WindowsBox`](./windows-box) | a Windows machine that is already there, right after the `Ssh` that reaches it |
| [`Apptainer`, `Docker`, `Podman`](./containers) | a container, with its own interpreter, built from its recipe |
| [`Micromamba`, `Conda`](./micromamba) | `micromamba -n <name> run`; nothing when that environment is already active |
| [`Venv`, `Uv`](./venv) | a given interpreter, or a uv-managed venv of the project |
| [`Nix`, `Guix`](./nix-guix) | `nix develop -c …`, `guix shell -- …` |
| [`Module`](./module) | Lmod or environment modules, the way a cluster picks a toolchain |
| [`Vars`](./vars) | environment variables for the child process |
| [`Mpi`](./mpi) | the launcher of [several processes](../mpi), when it is not the usual one. Rarely needed |
| [`Preload`](./preload) | at the end: sessions forked from a process that has already imported torch, jax… |
| [`Missing`](./missing) | a place this machine cannot reach: says what is lacking, and stops before anything runs |

That is every layer there is. A batch system other than Slurm has no layer.

## The interpreter

There is always a current interpreter, and most layers change it. A layer that selects an
interpreter replaces a **first word that names one** — `python`, `python3`, the interpreter errand
runs under — and leaves any other first word alone. So `errand run --env gpu nvidia-smi` runs
nvidia-smi, and `errand run --env gpu python -c …` runs the container's python.

## Built, and kept current

What a layer needs in order to exist — an image, a conda environment, a venv — it also knows how to
build, and errand rebuilds it when its declaration changes. What was already there is adopted, not
rebuilt. See [Keeping environments current](../upkeep).

## `when`

Every layer takes **`when =`**: an [expression](/reference/expressions) over the selected tags and
the pseudo-tag `phase` ( `prepare` or `run` ). A layer without one is active in both phases; at most
one scheduler may be active in each. See [Preparing, then running](../environments#preparing-then-running).

```python
errand.Slurm( partition = "gpu", gpus = 1, when = "phase=run" )
errand.Vars( { "XLA_FLAGS": "--xla_gpu_deterministic_ops" }, when = "cuda" )
```
