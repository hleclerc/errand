# Layers

A layer wraps the command that is about to run. A stack is read **outside in**:

```python
# errand-envs.py
import errand

errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "login.hpc", root = "/scratch/me/proj" ),   # that machine
                                         errand.Slurm( time = "2:00:00" ),                              # an allocation on it
                                         errand.Apptainer( image = "containers/cuda.sif" ),             # the container in it
                                         errand.Vars( { "OMP_NUM_THREADS": "8" } ) ] )                  # …and the child's env
```

There is always a current interpreter; most layers are a way to override it. A layer that selects an
interpreter replaces a **first word that names one** — `python`, `python3`, the interpreter errand
itself is running under — and leaves any other first word alone, which is why
`errand --env gpu -- nvidia-smi` runs nvidia-smi and `-- python -c …` runs the container's python.

Anything a layer needs in order to *exist* it also knows how to **build** — see
[Keeping environments current](/guide/upkeep).

## Vars

```python
Vars( values: dict | callable )
```

Environment variables for the child.

`values` may be a **callable taking the selected tags**, which is how a single environment covers a
whole dimension instead of being split into one environment per value:

```python
Vars( lambda t: { "MYPROJ_FTYPE": f"FP{ t.get( 'fp', '64' ) }" } )
```

See [Tags only select](/guide/tags#tags-only-select).

## Interpreter-selecting layers

### Venv

```python
Venv( python = "python", requirements = None, pip = [ ], create = False )
```

A specific interpreter: a venv's python, or any installed one. `create = True` makes the venv if
`python` points inside one that is missing. `requirements` is a path relative to the project root.

### Micromamba

```python
Micromamba( name, python = None, channels = [ "conda-forge" ],
            packages = [ ], requirements = None, pip = [ ],
            root_prefix = None, executable = None )
```

Wraps with `micromamba -n <name> run`; a no-op if that environment is already active.

`executable` is the micromamba binary to call, for a machine where it is not on `PATH`, and
`root_prefix` the directory `-n <name>` resolves against. Over `Ssh` only what is declared is
passed -- nothing is guessed from this machine's home -- and behind a `Slurm` layer the command
runs on a compute node that reads no rc file at all: state both there.

::: info Why `micromamba` is pinned to a root prefix
The shell hook exports `MAMBA_ROOT_PREFIX` from an rc file, which only *interactive* shells read.
Started from a Makefile, from cron or from any plain subprocess, micromamba instead falls back to
the envs directory beside its own binary — so `-n x` would silently name a different environment
than the same command typed by hand. The layer pins it.
:::

### Conda

```python
Conda( … )      # the same arguments as Micromamba
```

### Uv

```python
Uv( path = ".venv", python = None, requirements = None, pip = [ ] )
```

A uv-managed venv in the project. `path` is relative to the project root.

### Nix

```python
Nix( flake = ".", shell = None )     # nix develop <flake>[#<shell>] -c …
```

### Guix

```python
Guix( manifest = None, packages = [ ] )    # guix shell -m <manifest> -- …
```

With no manifest, `packages` is passed instead.

### Module

```python
Module( "gcc/13", "cuda/12" )
```

Lmod / environment modules — how a cluster picks a toolchain. `module` is a shell *function*, not a
program, so this goes through a login shell to exist at all. That is the whole layer.

## Container layers

### Apptainer

```python
Apptainer( image, recipe = None, flags = [ ], mounts = { }, pip = [ ],
           fakeroot = False, scratch = None, build_flags = [ ] )
```

Wraps with `apptainer exec`, using the container's own interpreter.

| | |
|---|---|
| `image` | the `.sif` |
| `recipe` | the `.def` it is built from. A change to it is a reason to rebuild |
| `flags` | passed to `apptainer exec` — `--nv`, `--nvccli` |
| `mounts` | `{ host: container }` |
| `pip` | installed **into** the container |

The last three are about *building* the image rather than entering it:

- `fakeroot` — build without root on a host that allows it.
- `scratch` — a directory with room. Apptainer unpacks whole layers, and the default `/tmp` is where
  a build dies halfway, out of space, on a shared machine.
- `build_flags` — passed to `apptainer build`.

An image is built **where it is used**: an `Ssh` layer in front means the recipe is rsynced over and
the build happens there.

### Docker / Podman

```python
Docker( image, recipe = None, flags = [ ], mounts = { }, pip = [ ], user = "caller" )
Podman( … )     # the same, rootless
```

`user` defaults to the caller's own, and this matters: a run writes its results into the project, and
a daemon-backed container writes them as root unless told otherwise — so the output tree of a
containerized run would come out owned by somebody who is not you, and the next run *outside* the
container could not clear it. Podman, being rootless, already maps the caller.

## Going elsewhere

### Ssh

```python
Ssh( host, root = None, python = "python3", options = [ ] )
```

**Must be the first layer.** Everything after it runs on `host`, resolved against `root` (the
project root over there; defaults to this one's path).

`options` are passed to **both ssh and rsync** — a port, an identity file, a jump host, a
`StrictHostKeyChecking` you have decided about. rsync has to get the same ones or it reaches a
different machine than ssh does.

```python
Ssh( host = "gpu-box", root = "/home/me/proj",
     options = [ "-p", "2222", "-i", "~/.ssh/bench" ] )
```

See [Running elsewhere](/guide/remote) for what the push and the pull actually move.

### Slurm

```python
Slurm( partition = None, nodes = None, cpus = None, gpus = None,
       time = None, account = None, nodelist = None, extra = [ ] )
```

`srun` while you wait, `sbatch` under [`--batch`](/guide/detached) — which *is* the detachment: it
returns as soon as the job is queued.

Not an interpreter-selecting layer: it puts the command inside an allocation and leaves it otherwise
alone, so it stacks in front of a container or an environment exactly as `Ssh` does in front of it.

**Everything is optional, `partition` included.** What is not stated is not passed, and Slurm then
applies its own default — which is the right answer far more often than a partition name copied out
of somebody else's script: the cluster already knows which one is the default, and it is the one
that stays correct when the cluster is rearranged.

What the entries ask for fills in the rest:

| declared | from the work | flag |
|---|---|---|
| `cpus` | `cpus = 4` | `--cpus-per-task` |
| `gpus` | `gpus = 1` | `--gpus` |
| — | `ram = "8G"` | `--mem` |
| — | `exclusive = True` | `--exclusive` |

**What the environment states explicitly wins**: whoever wrote `Slurm( cpus = 16 )` knew something
about that partition an entry cannot. A dispatched command carries several entries, so the
allocation is the largest of them, and exclusive if any one of them is.

`nodelist` pins the allocation to named nodes ( `--nodelist` ): a string as Slurm reads it
( `"node15"`, `"node[1-4]"` ) or a list of names.

`extra` is appended verbatim, for whatever your site needs that nothing above covers.

::: danger root must be on a shared filesystem
A batch job runs on a compute node, and `/tmp` there is not the `/tmp` you pushed to. errand checks
for this before submitting and tells you plainly.
:::

### Windows

```python
Windows( iso = None, key = None, index = 1, cpus = 4, ram = "8G", disk = "64G",
         msvc = True, python = None, provision = [ ], fetch = [ ], keep = "15m", root = None )
```

**Must be the first layer.** A Windows virtual machine under QEMU, which errand installs, boots,
reaches over ssh and stops. Everything is optional:

```python
errand.envs[ "win" ] = errand.Env( [ errand.Windows( fetch = [ "build" ] ) ] )
```

```bash
errand --env win --setup                         # the install: once, 20 to 60 minutes
errand --env win -- cmake -B build -G Ninja      # then: commands, through cmd.exe
errand --env win -- cmake --build build
errand --vm-stop                                 # let go of it now rather than in 15 minutes
```

With no `iso` and no `key` it is **Windows Server 2025, evaluation edition**: downloaded from
Microsoft, no licence needed for 180 days, and reinstalled by errand before it runs out. Server Core
by default — no desktop, which nothing run over ssh needs. `msvc` puts the Visual Studio build tools
in it (cl, link, msbuild, cmake, ninja) and calls `vcvars64` before every command.

| | |
|---|---|
| `iso`, `key`, `index` | another Windows: a path or a URL, its product key, which image of the ISO |
| `cpus`, `ram` | the size of the machine — how it is *booted*, so changing it reinstalls nothing |
| `python` | a python.org release, `"3.13.1"`, installed and on `PATH` |
| `provision` | more to install: a `.ps1` of the project, or a line of PowerShell |
| `fetch` | paths of the project brought back after each command — `build`, `dist` |
| `keep` | how long a booted machine waits for the next command |
| `root` | where the project goes over there; `C:/errand/<project name>` |

What it costs, and when:

- **The install** is a build like any other layer's: `--setup` does it, a changed declaration redoes
  it, `--dry-run` says it would. The disk image goes to `~/.cache/errand/windows/`, named by what it
  was installed from, so projects declaring the same Windows share one.
- **A boot** starts from a fresh copy-on-write layer over that image — nothing a run left behind
  survives a restart — and the machine then stays up `keep` after its last command. All that time
  it holds its cores and memory, so it holds them **in the queue**, and shows in `errand --queue`.
- **A command** costs a tar of the project in, and of `fetch` out. Commands on one machine take
  turns.

It needs `qemu-system-x86_64` and `qemu-img`, and an **x86-64 host**: KVM on Linux, HVF on an Intel
Mac. Without hardware virtualization it works, in hours. Apple Silicon is not supported.
`ERRAND_VM_VNC=1` shows the screen on `vnc://127.0.0.1:5901`, for watching an install go wrong.

Not yet: entries ( `errand --env win` with a pattern ) and `--batch` — errand itself is a unix
program. A command is what a virtual machine takes for now.

### Other batch systems

Slurm is the only one with a layer so far. errand does however **recognize** being inside a PBS,
OAR, LSF, SGE or Flux allocation, and [stands down from
queuing](/guide/machine#when-somebody-else-owns-the-machine) when it is — the scheduler has already
decided what this process may have.
