# 02 — environments

Four environments over three machines, declared in one file, and one benchmark that does not mention
any of them.

```
errand-project.py    what the project does: where its code is
errand-envs.py       where and how things run
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
  local    driver=cpu                    micromamba:demo -> vars                     <- default
  gpu      cuda  driver=cuda             apptainer:cuda.sif -> vars                  stale
  boxed    boxed  driver=cpu             docker:errand-demo:1 -> vars                not built
  box      cuda  driver=cuda  remote     ssh:gpu-box -> apptainer:cuda.sif -> vars   unknown
  cluster  cuda  driver=cuda  fp=64  remote  ssh:login.hpc -> slurm:gpu -> …         unknown
```

`unknown` is honest rather than optimistic: only the other machine can say what it has.

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

Tags are the keyword arguments on `errand.Env( … )` in `errand-envs.py`. Nothing declares them in advance, and
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
runs/bench_solver/solve/
  2026-09-24_18h04m11-local@thishost-method=cg,n=10000/result.yaml
  2026-09-24_18h04m11-gpu@thishost-method=cg,n=10000/result.yaml
  2026-09-24_18h04m11-gpu@gpu-box-method=cg,n=10000/result.yaml
  2026-09-24_18h09m30-local@thishost-method=cg,n=100000/result.yaml
  latest -> the newest of them
  summary.yaml                        <- one row per run: this is the comparison
```

The four of one command share a stamp, because they are one command; the name says the rest. A
matrix is more names, never more levels.

`{place}` is the environment and the machine. Both matter: the same environment on two machines is
two different sets of numbers, and the same machine with two environments likewise -- which is the
whole reason you declared two.

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
- **`boxed` is `gpu` without apptainer.** Same tags, same fingerprint, same output paths — only
  the layer differs, because apptainer does not exist on a mac and docker does. Choosing where to
  run has nothing to say about which engine holds the image.
- **Requirements live in the layer that installs them.** `requirements.txt` on the micromamba layer,
  `pip = [ … ]` on the container: whichever one changes is the one that gets rebuilt.
