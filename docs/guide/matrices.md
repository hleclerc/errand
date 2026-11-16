# Several runs: grids

```bash
errand run --grid=, --env local,gpu,cluster python bench.py     # three runs, one per environment
errand run --grid=, --fp 32,64 python bench.py                  # one per value of a tag
errand run --grid=, 'bench/solvers.py::cost' --n=1000,5000      # one per value of a parameter
errand run --grid=, --env local,gpu 'bench/solvers.py::cost' --n=1000,5000   # four runs
```

Several values make several runs **only under `--grid=SEP`**, and SEP is what splits them. One command,
every combination, each with its own [record](./output), side by side.

## The grid is asked for

Without `--grid`, a value is one value, whatever it holds. Commas are too common to mean a grid on
their own: a tuple, a list, a `1e-3,1e-6` written as one thing. So the grid is said, with a separator
that fits the values:

```bash
errand run --grid=, --env local,gpu python bench.py     # two environments
errand run --grid=+ 'bench/shapes.py::grid' --shape=1,2+3,4   # two values, each holding a comma
```

- `--grid` is errand's option: it goes **before** the target, and one separator serves the whole
  command.
- A value without the separator is one value: `--grid=, … --n=1000,5000 --tol=1e-6` is two runs.
- The separator twice is an empty value: `--suffix=,_fast` is two runs, one with an empty suffix.
- There is no escape. A value that holds the separator asks for another separator.
- A comma without `--grid` where it cannot be one value — an environment name, a tag value, a
  number — is an error that says how to ask for the grid.
- Targets keep their own commas: `prep.py,train.py` is two targets, `--grid` or not.

When there is more than one run, the grid is said before anything starts, so a grid you did not mean
is seen in time:

```text
  4 runs: n = 1000 | 5000, method = newton | lbfgs
```

## What can vary

| axis | written | lands in the run's name as |
|---|---|---|
| an [environment](./environments) | `--grid=, --env local,gpu` | `local@laptop`, `gpu@gpu-box` |
| a [tag](./tags) | `--grid=, --fp 32,64` | the environment's tags, in the record |
| a parameter of an entry | `--grid=, … --n=1000,5000` | `n=1000`, `n=5000` |

They cross: every environment, with every tag value it covers, with every parameter value. An
environment that pins `fp = "64"` is not selected by `--fp 32`, so crossing does not multiply
blindly. [Saying nothing means every value](./tags#saying-nothing-means-every-value).

**A script's or a command's arguments are not a grid**, `--grid` or not. What follows them is theirs,
passed as written: `errand run --grid=, python sweep.py --size 1024,4096` is one run, given
`1024,4096`, and `-Wl,-rpath` or `python -c "f( 1, 2 )"` mean what they say. To sweep a script's
values, declare them as parameters of an [entry](./declaring-work), or loop in the shell.

## What a grid does to the tree

More names, never more levels. One command is one stamp, however many runs, machines or batch jobs
it turns into:

```text
errand-outputs/runs/bench.py/
  2026-09-24_18h04m11-local@laptop/
  2026-09-24_18h04m11-gpu@laptop/
  2026-09-24_18h04m11-cluster@node15/
  latest -> the newest of them
  summary.yaml            one row per run: the comparison
```

Read `summary.yaml` after a grid: one row per run, and the range of every number across them. See
[Results and records](./output#summaries).

## Where it is expanded

A grid of environments is expanded here: each environment gets its share of the command. A grid of
parameters is expanded **where the work runs**, during the
[preparation](./environments#preparing-then-running): the plan names every run, and that is what
comes back, what [`errand status`](./status) shows, and what an allocation is sized from. The other
machine never sees a grid, only plain runs.

Under [`--batch`](./detached), `errand status` shows a grid as a table: parameters down, places across.

## Next

[Several processes (MPI)](./mpi).
