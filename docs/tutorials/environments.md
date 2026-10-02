# 2 · Four environments over three machines

Five environments, declared in one file, and one benchmark that does not mention any of them.

```bash
cd examples/02-environments
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
Read the file, adapt it, and `errand --envs` will tell you honestly what is and is not built here.
:::

## Look before you leap

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

You do not have to act on `stale` or `not built`. The next run that needs one of those environments
builds it first — a changed `requirements.txt`, a new pip spec, an edited `.def`, all the same
thing. `--setup` does it now and nothing else; `--no-setup` skips the check; `--setup --dry-run`
says what it *would* run.

## The declaration

Shared pieces are shared with plain Python. There is no second mechanism for this, and none is
wanted: a list is a list.

`errand-project.py` says what the project does — here, only where its code is:

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

Then five environments over the same pieces, in the same file:

```python
# errand-envs.py, continued
errand.envs[ "local" ] = errand.Env(
     [ errand.Micromamba( "demo", python = "3.13", requirements = "requirements.txt" ) ] + FTYPE,
     driver = "cpu" )

errand.envs[ "gpu" ] = errand.Env( CUDA + FTYPE, driver = "cuda", cuda = True )

# The same idea where apptainer does not exist -- a mac, a laptop without root.
errand.envs[ "boxed" ] = errand.Env( [ errand.Docker( image = "errand-demo:1", recipe = "containers/Dockerfile" ) ] + FTYPE,
                                     driver = "cpu", boxed = True )

# A remote machine is not a separate concept: Ssh first, then the same layers.
errand.envs[ "box" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "/home/me/demo" ) ] + CUDA + FTYPE,
                                   driver = "cuda", cuda = True, remote = True )

# ...and a batch system is one more layer, not a separate mode.
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "login.hpc", root = "/scratch/me/demo" ),
                                         errand.Slurm( partition = "gpu", gpus = 1, cpus = 16, time = "2:00:00" ) ]
                                       + CUDA + FTYPE,
                                       driver = "cuda", cuda = True, fp = "64", remote = True )
```

The first one declared, `local`, is the default; `errand.default_env = "gpu"` would say otherwise.

Read a stack outside in. `cluster` is: *that machine*, then *an allocation on it*, then *the
container*, then your command.

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

Nothing above mentions a machine, a container or a precision. Where it runs is a property of the
**invocation**, not of the code — which is what lets one command line run it in four places at once.

The code reads `DEMO_FTYPE` the way any program reads an environment variable. It does not ask
errand anything; the [`Vars` layer](/guide/tags#tags-only-select) is what puts the value there.

## Choosing where

```bash
errand -k bench --env gpu           # by name
errand -k bench --driver cuda       # by tag; every tag name is a flag
errand -k bench --fp 32
errand -k bench -t 'cuda & !remote' # by expression
```

Tags are the keyword arguments on `errand.Env( … )`. Nothing declares them in advance, and an environment
that omits a name matches **any** value of it.

## Running in several places at once

```bash
errand bench_solver --env local,gpu
errand bench_solver --fp 32,64
errand bench_solver --env local,gpu --n=10000,100000     # 4 runs
errand bench_solver -t 'cuda=True'                       # every cuda environment there is
```

Each combination gets its own directory, so the results end up side by side:

```text
runs/bench_solver/solve/
  2026-09-24_18h04m11-local@thishost-method=cg,n=10000/result.yaml
  2026-09-24_18h04m11-gpu@thishost-method=cg,n=10000/result.yaml
  2026-09-24_18h04m11-gpu@gpu-box-method=cg,n=10000/result.yaml
  2026-09-24_18h09m30-local@thishost-method=cg,n=100000/result.yaml
  latest -> the newest of them
  summary.yaml                        <- one row per run: this is the comparison
```

The four runs of one command **share a stamp**, because they are one command; the name says the
rest. `{place}` is the environment *and* the machine — both matter, because the same environment on
two machines is two different sets of numbers, and the same machine with two environments likewise,
which is the whole reason you declared two.

## Leaving it to run

```bash
errand --batch -k bench --env gpu,cluster --fp 32,64
  submitted b7f3 · 8 runs · 4 on login.hpc (slurm 918273…918276), 4 local

errand --watch
```

`--batch` is a **mode, not an environment**: locally it means a detached session, over `Ssh` it means
started and let go, and on `cluster` it turns the `Slurm` layer's `srun` into an `sbatch`. Nothing
else about the run changes — same paths, same queue, same output.

## What to notice

- **A tag selects, a layer acts — and a layer may read the selection.** No environment above
  mentions `fp`, so every one covers every precision;
  `Vars( lambda t: { "DEMO_FTYPE": f"FP{ t.get( 'fp', '64' ) }" } )` is what the child then sees.
  Without the callable form there would be a `local32` beside every `local` and a `gpu32` beside
  every `gpu`, with the precision written twice in each. `--fp 32,64` is two runs *in one
  environment*.
- **`cluster` pins `fp = "64"`**, so `--fp 32` simply does not select it. Saying nothing means every
  value; saying one means only that one.
- **`Ssh` and `Slurm` are layers like the others.** No separate remote mode, no host file, no second
  config.
- **`boxed` is `gpu` without apptainer.** Same tags, same fingerprint, same output paths — only the
  layer differs, because apptainer does not exist on a mac and docker does. Choosing *where* to run
  has nothing to say about which engine holds the image.
- **Requirements live in the layer that installs them.** `requirements.txt` on the micromamba layer,
  `pip = [ … ]` on the container: whichever one changes is the one that gets rebuilt.

## Next

[3 · Adopt an existing suite](./adopt-a-suite), or jump to
[4 · A bench over two machines](./two-machines) to put this one to work.
