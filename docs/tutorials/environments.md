# 1 · Four environments

Four places to run: here, in a container, on a GPU server over ssh, on a Slurm cluster. One file
declares them, and one benchmark names none of them.

```bash
cd examples/01-environments
```

```
errand-project.py      what the project does: where its code is
errand-envs.py         where and how things run
requirements.txt       what the local environment installs
containers/cuda.def    what the image is built from
src/solver.py          the work; knows nothing about errand
bench_solver.py        the entries
```

::: info These places do not exist on your machine
`gpu-box`, `login.hpc`, the `demo` micromamba environment and the CUDA image are somebody else's.
Read the file, adapt it, and `errand envs` tells you what is and is not built here. The file also
declares a `windows` environment; [tutorial 3](./cluster-and-vm) walks through that one.
:::

## Look first

```bash
errand envs
```

```text
Environments
  local    driver=cpu                    micromamba:demo -> vars                                    <- default
  gpu      cuda  driver=cuda             apptainer:cuda.sif -> vars                     stale
  boxed    boxed  driver=cpu             docker:errand-demo:1 -> vars                   not built
  box      cuda  driver=cuda  remote     ssh:gpu-box -> apptainer:cuda.sif -> vars      unknown
  cluster  cuda  driver=cuda  fp=64  remote  ssh:login.hpc -> slurm:gpu -> …         unknown
```

`unknown` means only the other machine can say what it has.

You do not have to act on `stale` or `not built`. The next run that needs the environment builds it
first: a changed `requirements.txt`, a new pip spec, an edited `.def`, all the same.
`errand setup` builds now and does nothing else. `--no-setup` skips the check.
`errand setup --dry-run` says what it would run.

## The declaration

Shared pieces are shared with plain Python. A list is a list.

`errand-project.py` says what the project does. Here, only where its code is:

```python
# errand-project.py
import errand

errand.configure( src = [ "src" ] )          # prepended to every child's PYTHONPATH
```

`errand-envs.py` says where it runs:

```python
# errand-envs.py
import errand

CUDA = [
    errand.Apptainer( image  = "containers/cuda.sif",
                      recipe = "containers/cuda.def",   # what to (re)build the image from
                      flags  = [ "--nv" ],
                      pip    = [ "jax[cuda13]" ] ),     # installed INTO the container
]

FTYPE = [ errand.Vars( lambda t: { "DEMO_FTYPE": f"FP{ t.get( 'fp', '64' ) }" } ) ]
```

Then the environments, over the same pieces:

```python
# errand-envs.py, continued
errand.envs[ "local" ] = errand.Env(
     [ errand.Micromamba( "demo", python = "3.13", requirements = "requirements.txt" ) ] + FTYPE,
     driver = "cpu" )

errand.envs[ "gpu" ] = errand.Env( CUDA + FTYPE, driver = "cuda", cuda = True )

# The same idea where apptainer does not exist: a Mac, a laptop without root.
errand.envs[ "boxed" ] = errand.Env( [ errand.Docker( image = "errand-demo:1", recipe = "containers/Dockerfile" ) ] + FTYPE,
                                     driver = "cpu", boxed = True )

# A remote machine: Ssh first, then the same layers.
errand.envs[ "box" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "/home/me/demo" ) ] + CUDA + FTYPE,
                                   driver = "cuda", cuda = True, remote = True )

# A batch system: one more layer.
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "login.hpc", root = "/scratch/me/demo" ),
                                         errand.Slurm( partition = "gpu", gpus = 1, cpus = 16, time = "2:00:00" ) ]
                                       + CUDA + FTYPE,
                                       driver = "cuda", cuda = True, fp = "64", remote = True )
```

The first one declared, `local`, is the default. `errand.default_env = "gpu"` would say otherwise.

Read a stack from the outside in. `cluster` is: that machine, then an allocation on it, then the
container, then your command. → [Layers](/guide/layers/)

## The work names no machine

```python
# bench_solver.py
FTYPE = os.environ.get( "DEMO_FTYPE", "FP64" )

if p := bench( "solve", n = Param( 10_000, help = "number of unknowns" ),
                        method = Param( "cg", choices = [ "cg", "direct" ] ) ):
    t = time.perf_counter( )
    x = solve( n = p.n, method = p.method )
    p.results[ "seconds" ]  = time.perf_counter( ) - t
    p.results[ "residual" ] = residual( x )
    p.results[ "ftype" ]    = FTYPE          # recorded, so the rows say which is which
```

Nothing here mentions a machine, a container or a precision. Where it runs is chosen on the command
line, which is what lets one command run it in four places at once.

`bench` and `Param` are errand's own entries, which are optional: a plain script or a pytest suite
works the same way. → [Writing entries](/guide/declaring-work)

The code reads `DEMO_FTYPE` like any environment variable. The [`Vars` layer](/guide/tags#tags-only-select)
puts the value there.

## Choosing where

```bash
errand run --env gpu "bench_solver.py::*"            # by name
errand run --driver cuda "bench_solver.py::*"        # by tag: every tag name is a flag
errand run --fp 32 "bench_solver.py::*"
errand run -t 'cuda & !remote' "bench_solver.py::*"  # by expression
errand run --env gpu nvidia-smi                      # any command, in that place
```

`bench_solver.py::*` is every entry of that file. Without the `::`, `bench_solver.py` would run as
a plain script, which is what a `train.py` wants.

Tags are the keyword arguments of `errand.Env( … )`. Nothing declares them in advance, and an
environment that omits a tag matches any value of it. → [Tags](/guide/tags)

## Several places at once

```bash
errand run --grid=, --env local,gpu "bench_solver.py::*"
errand run --grid=, --fp 32,64 "bench_solver.py::*"
errand run --grid=, -o --env local,gpu "bench_solver.py::*" --n=10000,100000  # 4 runs
errand run -t 'cuda=True' "bench_solver.py::*"                                 # every cuda environment
```

`--grid=,` says that a comma separates values. Without it, a value is one value.
→ [Grids](/guide/matrices)

Each combination gets its own record, side by side:

```text
errand-outputs/runs/bench_solver.py/solve/
  2026-09-24_18h04m11-local@thishost-method=cg,n=10000/result.yaml
  2026-09-24_18h04m11-gpu@thishost-method=cg,n=10000/result.yaml
  2026-09-24_18h04m11-local@thishost-method=cg,n=100000/result.yaml
  2026-09-24_18h04m11-gpu@thishost-method=cg,n=100000/result.yaml
  latest -> the newest of them
  summary.yaml                        <- one row per run: the comparison
```

The runs of one command share a stamp. `{place}` is the environment and the machine: the same
environment on two machines gives two sets of numbers, and so does one machine with two
environments. → [Results and records](/guide/output)

## Letting it run

```bash
errand run --grid=, --batch --env gpu,cluster --fp 32,64 "bench_solver.py::*"
```

```text
  submitted b7f3 - gpu on this machine (local 41288), gpu on this machine (local 41290), cluster on login.hpc (batch 918273)
  errand status    errand watch
```

Three places, not four: `cluster` pins `fp = "64"`, so `--fp 32` does not select it.

`--batch` is a mode, not an environment. Here it is a detached process. Over `Ssh` it is a command
started and let go of. On `cluster` it is an `sbatch`, which returns once the job is queued. Paths,
records and output stay the same. → [Let it run](/guide/detached)

## What to notice

- **A tag selects, a layer acts, and a layer may read the selection.** No environment mentions `fp`
  except `cluster`, so the others cover every precision. `Vars( lambda t: … )` turns the selected
  value into what the child sees. Without it you would need a `local32` beside every `local`.
- **Saying nothing means every value; saying one means only that one.** That is why `cluster` drops
  out of `--fp 32`.
- **`Ssh` and `Slurm` are layers like the others.** No remote mode, no host file, no second config.
- **`boxed` is `gpu` without apptainer.** Same tags, same output paths. Only the layer differs,
  because a Mac has docker and not apptainer.
- **Requirements live in the layer that installs them.** `requirements.txt` on the micromamba
  layer, `pip = [ … ]` on the container: whichever changes is rebuilt.

## Next

[2 · Numbers over two machines](./two-machines) puts this to work on a real server.
[3 · A cluster, a Windows VM, and what is running](./cluster-and-vm) goes further: an allocation
kept warm, a Windows build, and `errand status`.
