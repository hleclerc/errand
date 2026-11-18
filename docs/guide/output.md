# Results and records

```bash
errand run --env cluster -o python train.py        # train.py writes into $ERRAND_OUT_DIR; it comes back
errand run --env cluster --pull plots python plot.py   # plots/ comes back from the other machine
errand run --out "results/{env}/{when}" python train.py   # your own layout
ls errand-outputs/runs/train.py/                   # one directory per run, and latest
```

Every run leaves a **record** in the project: what ran, where, when, how it ended, and what it
printed. With `-o`, it also gets a directory of its own for the files it writes, brought back from
wherever it ran. Everything is plain files under `errand-outputs/`: no database, nothing to query
but the tree.

## Its own directory: `-o`

```bash
errand run --env cluster -o python train.py
```

```python
# train.py
import os, pathlib
out = pathlib.Path( os.environ.get( "ERRAND_OUT_DIR", "out" ) )
torch.save( model, out / "model.pt" )
```

`-o` hands the command the run's directory as **`$ERRAND_OUT_DIR`**. What it writes there is brought
back with the record, from the other machine, the container, the allocation. Without `-o`, the
variable is not set: nobody is handed a directory they did not ask for.

`--out` does the same under another tree, or as a pattern from the project root:

```bash
errand run --out results python train.py                   # results/train.py/…
errand run --out "results/{env}/{when}" python train.py    # results/gpu/2026-09-25_18h04m11/
```

The pattern takes `{path}` `{name}` `{when}` `{place}` `{env}` `{params}`, described below.

`{params:a,b}` keeps only the parameters it names, in that order:

```bash
errand run --out "results/{params:case,method,n}/{when}" bench.py --case=ring --method=lu --n=5000 --path=data/x
# results/case=ring,method=lu,n=5000~3f9c1e/2026-09-25_18h04m11/
```

A name stays short, and says what tells your runs apart. When the run has parameters left out of it
( `path` above ), a short hash of all of them goes on the end: two runs that differ only by those
are still two directories. With every parameter named, there is no hash.

An [entry](./declaring-work) always has its directory, as `p.out_dir`.

## Bringing back more: `--pull`

A command that writes elsewhere in the project, over there, gets it back with `--pull`:

```bash
errand run --env cluster --pull plots --pull checkpoints python train.py
```

Each `DIR` is relative to the project root, and comes back after the command, whether it passed or
failed. Other ways something comes back:

- a `back` [zone](./layers/ssh#what-gets-pushed), declared once in the project:
  `errand.configure( zones = { "/results": "back" } )`;
- `fetch = [ "build" ]` on a [`Windows`](./layers/windows) or [`WindowsBox`](./layers/windows-box)
  layer, after each command.

Only what was asked for comes back. The rest of the copy over there, and the records of other
runs, stay where they are ( [Results are pulled, not pushed](./layers/ssh#results-are-pulled-not-pushed) ).

## The runs tree

```text
errand-outputs/runs/
  train.py/
    2026-09-25_18h04m11-gpu@gpu-box/
    2026-09-25_18h11m02-local@laptop/
    latest -> 2026-09-25_18h11m02-local@laptop
    summary.yaml
  make/
    2026-09-25_18h20m40-local@laptop-args=-j16/
```

A run's directory is

```text
runs/{path}/{when}-{place}[-{params}]/
```

- **`{path}`** is the file, from the project root, extension included: what you typed to run it. A
  command is its first word ( `make` ). Two `solve.py` in two directories, or a `solve.py` beside a
  `solve.cpp`, never share one. An [entry](./declaring-work) adds its name below:
  `runs/bench/solvers.py/cost/…`.
- **`{when}`** is the moment the command started, to the second. One stamp for the whole command,
  however many processes, machines or batch jobs it turns into: that is what lets every part of it
  land in a directory known before it ran.
- **`{place}`** is the environment and the machine: `gpu@gpu-box`. The same environment on two
  machines gives two sets of numbers, and so does one machine with two environments.
- **`{params}`** is what was asked for, in words: the arguments ( `args=-j16` ) or an entry's
  parameters ( `method=newton,n=5000` ), sorted. Past a readable width it is cut, with a short hash on
  the end: what falls past the cut is not in the name. To choose what is, name it in a `--out`
  pattern: `{params:case,n}`.

The directory is cleared and recreated when its run starts; everything above it accumulates. A
[grid](./matrices) adds names, never levels.

**`latest`** is a symlink to the newest run. Leave a viewer open on `latest/shape.png` and reload it.
On a filesystem without symlinks it is simply missing.

## What a run directory holds

```text
2026-09-25_18h04m11-gpu@gpu-box/
  result.yaml      always: what ran, where, how it ended -- written last
  output.txt       what it printed, when it printed anything
  stdout.txt       the process's standard output, as written to it
  stderr.txt       its standard error, apart
  model.pt         what it wrote there, with -o
```

**`stdout.txt` and `stderr.txt` are the raw streams**: what the process wrote to its descriptors,
the C library's writes, a child's, and a fault handler's included. `output.txt` is what was shown,
both interleaved. On Linux and macOS a small process of its own copies them, and outlives the run:
a segfault or an abort leaves in `stderr.txt` everything written up to the end -- with Python's word
on where it crashed -- and that process writes the run's `result.yaml` for it ( `status: FAIL`,
`error: the process ended during the run…`, no `duration_s` ). A stream that is a terminal is left
alone ( colors, progress bars ): what Python writes to it is copied instead, and so on Windows.

**A process that fails says the last of its stderr.** When a run ends by a nonzero exit status or a
signal ( `exit 3`, `signal SIGSEGV` ), the last lines of `stderr.txt` follow the reason, in the
report and in `error:`. A session that dies over there is said the same way, with the case it was in.

**A run comes back once finished.** From another machine, a run's directory is brought back only
once its `result.yaml` is written: never half of one, however early you ask ( `errand status` on a
`--batch` ). And a pull never deletes here: what you have that is gone over there stays.

```yaml
name: train.py                       # the file, or the entry's name
file: train.py                       # relative to the root when it is under it
date: 2026-09-25T18:04:11+02:00
env: gpu
place: gpu@gpu-box                   # environment and machine, as in the directory name
host: gpu-box
commit: 4f2a1b9                      # short HEAD, or null outside a git tree
dirty: true                          # the tree had uncommitted changes
errand: 2026.11.03.2                 # which errand wrote it
status: PASS                         # PASS | FAIL | SKIP
error: null                          # the reason, for FAIL and SKIP: `exit 1`
duration_s: 12.406                   # the work, not the waiting
ram_mb: 1840.2                       # peak memory
params: { }                          # what was asked for
tags: { driver: jax }                # the tags of the environment
results: { }                         # an entry's p.results
output_file: output.txt              # or null
```

- **`duration_s` leaves out the waiting.** Time spent waiting for the machine is not time the work
  took.
- **`commit` and `dirty` are provenance.** errand records that the tree was dirty, and runs anyway.
- **`output.txt` is written as the run talks**, not at the end, so `tail -f` works on it, here or on
  the other machine.
- A value that cannot be written as yaml is written as its `repr`, rather than losing the record.

## Summaries

Each case has a `summary.yaml` beside its runs: one row per run, and the range of every number across
them. That is the file to read after a [grid](./matrices).

```yaml
passed: 7
failed: 1
runs: 8
duration_s: [ 11.9, 64.8 ]
seconds: [ 11.2, 64.8 ]
entries:
  2026-09-25_18h04m11-gpu@gpu-box-n=5000:   { status: PASS, runs: 1, duration_s: 12.406, seconds: 12.406 }
  2026-09-25_18h04m11-local@laptop-n=5000:  { status: PASS, runs: 1, duration_s: 61.2, seconds: 61.2 }
```

It is recomputed after every run by reading the `result.yaml` files beside it, so it is always right:
delete it, or half the runs, and the next run writes it again. Numbers are summarized per key
( min and max ); a single value prints as a value, a spread as a pair. Strings are kept in
`result.yaml` and left out.

## What else is on disk

Everything errand writes for a project is in one directory at its root:

```text
errand-outputs/
  runs/     the record of every run, as above
  builds/   what errand built, and its records of it: records/ ( one yaml per artefact, the build
            logs ), windows/ ( Windows images )
  state/    errand's bookkeeping: plans, command history, --batch submissions, the output kept
            for errand attach
```

`runs/` is for you to read; `state/` is not. `errand init` adds `errand-outputs/` to `.gitignore`.
Delete `errand-outputs/runs/` and you have deleted the records, nothing else.

The queue of the machine is elsewhere, outside any project: see [Sharing a machine](./machine).

## Where the tree goes

`errand.configure( outputs_directory = "errand-outputs" )` moves it, relative to the project root or
absolute; `ERRAND_OUTPUTS_DIR` overrides it on one machine, for a scratch disk. `builds_directory`
moves `builds/` alone. Over ssh, [`Ssh( errand_outputs_directory = … )`](./layers/ssh) puts the
other machine's tree on its scratch. See [Configuration](./configuration) and
[Where errand writes](./storage).

A project that still has a `.errand/` or a `runs/` from an older errand has them moved into
`errand-outputs/` the first time errand runs there.

## Next

[Let it run: --batch and attach](./detached).
