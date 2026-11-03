# Layers

A layer wraps the command that is about to run, and an [environment](../environments) is a stack of
them, read **outside in**:

```python
# errand-envs.py
import errand

errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "login.hpc", root = "/scratch/me/proj" ),   # that machine
                                         errand.Slurm( time = "2:00:00" ),                              # an allocation on it
                                         errand.Apptainer( image = "containers/cuda.sif" ),             # the container in it
                                         errand.Vars( { "OMP_NUM_THREADS": "8" } ) ] )                  # …and the child's env
```

| layer | what it does |
|---|---|
| [`Ssh`](./ssh) | must be first; everything after it runs on that machine, with the project pushed there and the results brought back |
| [`Slurm`](./slurm) | an allocation: `srun`, or `sbatch` in [batch mode](../detached), sized from what the work asks for |
| [`Windows`](./windows) | a Windows virtual machine errand boots and runs in; first, or right after its `Ssh` |
| [`Apptainer`, `Docker`, `Podman`](./containers) | a container, using its own interpreter, built from its recipe |
| [`Micromamba`, `Conda`](./micromamba) | `micromamba -n <name> run`; a no-op if that environment is already active |
| [`Venv`, `Uv`](./venv) | a specific interpreter, or a uv-managed venv of the project |
| [`Nix`, `Guix`](./nix-guix) | `nix develop -c …`, `guix shell -- …` |
| [`Module`](./module) | Lmod / environment modules, the way a cluster picks a toolchain |
| [`Mpi`](./mpi) | a launcher of its own for [several processes](../mpi), where neither `mpiexec` nor Slurm's `srun` is the one — rarely needed |
| [`Vars`](./vars) | environment variables for the child process |

## The interpreter

There is always a current interpreter; most layers are a way to override it. A layer that selects an
interpreter replaces a **first word that names one** — `python`, `python3`, the interpreter errand
itself is running under — and leaves any other first word alone, which is why
`errand run --env gpu nvidia-smi` runs nvidia-smi and `errand run --env gpu python -c …` runs the
container's python.

## Built, and kept current

Anything a layer needs in order to *exist* it also knows how to **build** — see
[Keeping them current](../upkeep).

## `when`

Every layer takes **`when =`**: an [expression](/reference/expressions) over the selected tags and
the pseudo-tag `phase` ( `prepare` or `run` ). A layer without one is active in both phases; at most
one scheduler may be active in each. See [Preparing, then running](../environments#preparing-then-running).
