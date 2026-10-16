# Parameters and matrices

## Param

`Param( default )` declares a typed flag — the type comes from the default. Parameters show up in
`errand list` and are echoed before each run:

```python
from errand import bench, Param

if p := bench( "cost", n = Param( 1000, help = "nb of points" ),
                       method = Param( "newton", choices = [ "newton", "lbfgs" ] ) ):
    p.results[ "cost" ] = run( p.n, p.method )
```

```bash
errand run bench/solvers.py::cost --n=5000 --method=lbfgs
```

`Param( 1000 )` is an int, `Param( "newton" )` a string, `Param( 0.5 )` a float — the default's type
is the reader. A value that cannot be read as that type is an error naming the flag, not a surprise
three lines into the body, and `choices = [ … ]` is checked the same way. Every parameter takes a
value on the command line; a yes/no is better spelled
`Param( "no", choices = [ "no", "yes" ] )` than as a bare flag.

A keyword on an entry that is **not** a `Param` has to be a trait or a resource, and anything else
is a `TypeError` saying so — which is what catches `n = 1000` written where
`n = Param( 1000 )` was meant.

## A comma is a matrix

```bash
errand run bench/solvers.py::cost --n=1000,5000 --method=newton,lbfgs    # 4 runs, 4 directories
```

**A comma means a matrix** wherever errand is the one reading — on a declared parameter, on a tag,
on an environment, on the targets themselves:

```bash
errand run bench/solvers.py::cost --n=1000,5000                             # two parameter values
errand run --fp 32,64 bench/solvers.py::cost                                # two values of a tag
errand run --env local,gpu bench/solvers.py::cost                           # two environments
errand run --env local,gpu train.py,eval.py                                 # two targets, two environments
errand run --env local,gpu --fp 32,64 bench/solvers.py::cost --n=1000,5000  # eight runs
```

Each value is an axis, the cartesian product is run, and every combination gets its own record — and
its own directory, with [`-o`](./output) — so the results sit side by side. When there is more than
one run, the grid is said once before anything starts — `4 runs: n = 1000 | 5000, method = newton |
lbfgs` — so a comma that was not meant as one is seen in time.

**An argument nobody declared is not a matrix.** What follows a script or a command is its own, and
passes through as written: `errand run scripts/sweep.sh --size 1024,4096` is one run, given
`1024,4096`, and `-Wl,-rpath` or `python -c "f( 1, 2 )"` mean what they say. To sweep a script, loop
in the shell, or declare the parameter on an [entry](./declaring-work). For the same reason a comma
cannot appear in an environment name or a tag value.

On a declared parameter, **`\,` is a comma**, and only a comma: `--tol 1e-3\,1e-6` is one value with a
comma in it ( quote it, or write `\\,`, so the shell leaves the backslash ). **`,,` is an empty
value**: `--suffix=,_fast` is two runs, one with an empty suffix. No other backslash means anything.
On an `--option=value`, the comma is in the value: `--mode=a,b` is `--mode=a`, then `--mode=b`.

This works on **any** entry, tests included: sweeping a test across four environments is a perfectly
good thing to want, and often the thing you most want.

## What a matrix does to the tree

A matrix is **more names, never more levels** — here as `-o` lays it out under `runs/`; the private
record in `.errand/runs/` has the same shape:

```text
runs/bench_solver.py/solve/
  2026-09-24_18h04m11-local@thishost-method=cg,n=10000/result.yaml
  2026-09-24_18h04m11-gpu@thishost-method=cg,n=10000/result.yaml
  2026-09-24_18h04m11-gpu@gpu-box-method=cg,n=10000/result.yaml
  2026-09-24_18h09m30-local@thishost-method=cg,n=100000/result.yaml
  latest -> the newest of them
  summary.yaml                        <- one row per run: this is the comparison
```

The runs of one command **share a stamp**, because they are one command — however many processes,
machines or scheduler queues that command turns into. The rest of the name says where and with
what. See [Where the output goes](./output).

Read `summary.yaml` after a matrix: one row per run, with the extents across them all. That is the
comparison you ran the matrix for, and it is recomputed by re-reading the neighbouring
`result.yaml` files, so it is always right.

## Matrices and the places they cross

Three things cross, and they cross together:

| axis | spelled | lands in the name as |
|---|---|---|
| a parameter | `--n=1000,5000` | `n=1000` |
| a [tag](./tags) | `--fp 32,64` | part of the environment's identity |
| an [environment](./environments) | `--env local,gpu` | `{env}@{host}` |

Crossing a tag with an environment does *not* multiply blindly: an environment that pins
`fp = "64"` is simply not selected by `--fp 32`, and one that says nothing about `fp` covers every
value of it. [Saying nothing means every value.](./tags)

## Where it is expanded

Matrices are expanded **where the work runs**, one plain run per combination, during the
[preparation](./environments#preparing-then-running): the plan it writes names every run, and that is
what the fetch back, `errand status` and the screen read — for a local run, a run [over
ssh](./remote) and a [detached](./detached) one alike.

## On a screen

[`errand tui`](./tui) builds the same comma. Enter on a case opens a window with every dimension
in it — environments, tags, parameters, how many at once — and ticking two of anything is a matrix,
for exactly the reason a comma is. Below the rule the window shows the command it is about to run,
so the day you want it in a script you already know what to write.

## Next

[Environments](./environments) — the other half of every matrix.
