# 02 — environments

Four environments over three machines, declared in one file, and one benchmark that does not mention
any of them.

```
errandfile.py            where and how things run
requirements.txt     what the local environment installs
containers/cuda.def  what the image is built from
src/solver.py        the work; knows nothing about errand
bench_solver.py      the entries
```

## Look before you leap

```bash
cd examples/02-environments

errand --envs
```

```
  local     driver=cpu                     micromamba:demo             ← default
  gpu       driver=cuda  cuda              apptainer:cuda.sif          stale: recipe changed
  box       driver=cuda  cuda  remote      ssh:gpu-box → apptainer     not built
  cluster   driver=cuda  cuda  remote  fp=64   ssh:login.hpc → slurm:gpu   not built
```

You do not have to act on `stale` or `not built`. The next run that needs one of those environments
builds it first — a changed `requirements.txt`, a new pip spec, an edited `.def`, all the same
thing. `--setup` does it now and nothing else; `--no-setup` skips the check.

## Choosing where

```bash
errand -k bench --env gpu           # by name
errand -k bench --driver cuda       # by tag; every tag name is a flag
errand -k bench --fp 32
errand -k bench -t 'cuda & !remote' # by expression
```

Tags are the keyword arguments on `env( … )` in `errandfile.py`. Nothing declares them in advance, and
an environment that omits a name matches any value of it.

## Running in several places at once

A comma is a matrix. It means the same thing on an environment, on a tag and on a parameter:

```bash
errand bench_solver --env local,gpu
errand bench_solver --fp 32,64
errand bench_solver --env local,gpu --n=10000,100000     # 4 runs
errand bench_solver -t 'cuda=True'                       # every cuda environment there is
```

Each combination gets its own directory, so the results end up side by side:

```
runs/bench_solver__solve/
  4b81e0/                             <- n=10000 method=cg
    thishost/2026-09-24/result.yaml
    cuda.sif@thishost/2026-09-24/result.yaml
    cuda.sif@gpu-box/2026-09-24/result.yaml
    summary.yaml                      <- one row per place: this is the comparison
  summary.yaml                        <- one row per parameter set
```

`{place}` is the host, prefixed by the container when there was one. Both matter: the same image on
two machines is two different sets of numbers.

## Leaving it to run

```bash
errand --batch -k bench --env gpu,cluster --fp 32,64
  submitted b7f3 · 8 runs · 4 on login.hpc (slurm 918273…918276), 4 local

errand --watch
```

`--batch` is a mode, not an environment: locally it means a detached session, over `Ssh` it means
started and let go, and on the `cluster` environment above it turns the `Slurm` layer's `srun` into
an `sbatch`. Nothing else about the run changes — same paths, same queue, same output.

## Notice

- **`bench_solver.py` names no machine.** Where the work runs is a property of the invocation. The
  code reads `DEMO_FTYPE` like any program reads an environment variable; the `Vars` layer is what
  puts it there.
- **A tag selects, a layer acts — and a layer may read the selection.** No environment above
  mentions `fp`, so every one of them covers every precision;
  `Vars( lambda t: { "DEMO_FTYPE": f"FP{ t.get( 'fp', '64' ) }" } )` is what the child process then
  sees. Without the callable form there would be a `local32` beside every `local` and a `gpu32`
  beside every `gpu`, with the precision written twice in each — once to be matched, once to be
  handed over. `--fp 32,64` is two runs *in one environment*.
- **`cluster` pins `fp = "64"`**, so `--fp 32` simply does not select it. Saying nothing means every
  value; saying one means only that one.
- **`Ssh` and `Slurm` are layers like the others.** `cluster` is `Ssh` then `Slurm` then the same
  container the local `gpu` environment uses. There is no separate remote mode, no host file, no
  second config.
- **Requirements live in the layer that installs them.** `requirements.txt` on the micromamba layer,
  `pip = [ … ]` on the container: whichever one changes is the one that gets rebuilt.
