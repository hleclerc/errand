# Where the output goes

Every run is **recorded**, whether anybody asked or not: command, environment, place, date, status,
duration, output, results — what the history, [the screen](./tui), `errand status` and `--batch`
read. The record is in the project's tree, in `errand-outputs/runs/…`, where you can read it.

`-o` gives each run an **output directory of its own** as well: the run's directory under
`errand-outputs/runs/`, handed to the command as `$ERRAND_OUT_DIR`, and whatever is written into it
is brought back. `--out` puts the runs somewhere else — another tree, or a pattern of your own with
`{path}` `{name}` `{when}` `{place}` `{env}` `{params}`:

```bash
errand run -o "bench/solvers.py::cost" --n=1000,5000   # errand-outputs/runs/bench/solvers.py/cost/…
errand run --out "results/{env}/{when}" train.py       # results/gpu/2026-09-25_18h04m11/
```

Either way it is laid out the same, and the rest of this page describes it, from `runs/` down.

**The file's path and the case's name to find a case, then one flat list of its runs**, each cleared and recreated as it
starts. Only the run directory is cleared; everything above it accumulates.

```text
runs/{path}/{name}/{when}-{place}[-{params}]/
runs/{path}/{name}/latest -> the newest of them

runs/bench/solvers.py/cost/2026-09-25_18h04m11-gpu@gpu-box-method=newton,n=5000/
runs/bench/solvers.py/cost/2026-09-25_18h11m02-local@laptop-method=cg,n=5000/
```

A plain command has no file and no case: it is `runs/{first word}/{when}-{place}[-{args}]/` —
`errand run make -j16` lands in `errand-outputs/runs/make/…-local@laptop--j16/`.

The file's path — from the project root, extension included — and the name are how you *look* for
work: they are what you typed to run it, so they are directories. Two `test_ot.py` in two
directories, or a `solve.py` beside a `solve.cpp`, never share one. Everything that tells two **runs** of that case apart is one directory name, in the
order you would say it out loud: **when, where, and with what.**

::: tip Why not a level per dimension
A tree with a level per dimension reads beautifully drawn in a README and badly when it is a `cd`
away, and the level whose name was a hash of the parameters could not be read at all.

A matrix is more *names*, never more levels.
:::

## The three parts of a run's name

**`{when}`** is the moment the **command** started, to the second — one stamp for the whole
invocation, however many processes it turns into. That is what lets the `-j 8` children, the batch
job the scheduler starts tomorrow and the run over ssh all land in the directory that was predicted
for them.

**`{place}`** is the environment and the machine — `default@gpu-box`, `cuda@gpu-box`. Both matter
and neither is enough: the same environment on two machines is two different sets of numbers, and
the same machine with two environments likewise, which is the whole reason you declared two. The
environment stands for its container rather than the other way round — an image is one of the things
an environment *is*, and the name is the one you chose.

**`{params}`** is what was asked for, in words — cut at a readable width with a short hash on the
end when there is more of it than anyone would read.

**`latest/`** is a symlink, so every run can be stamped without costing you a stable path. Leave a
tab open on `latest/shape.png` and reload it. That is what
[`experiment`](./declaring-work#test-bench-track-experiment) sets `stable_path` for. On a filesystem
without symlinks its absence is a loss, not a failure: the run still writes everything else.

## What lands in a run directory

The leaf always holds `result.yaml`, plus `output.txt` if the body printed anything.

```yaml
name: cost                           # the entry's name
file: bench/solvers.py               # relative to the root when it is under it
line: 42                             # the call site
kind: bench                          # test | bench | experiment
date: 2026-09-25T18:04:11+02:00      # the directory carries the day; this says when
env: gpu                             # the environment's name
place: gpu@gpu-box                   # environment and machine: what the directory says
host: gpu-box                        # hostname, first component
commit: 4f2a1b9                      # short HEAD, or null outside a git tree
dirty: true                          # the tree was not clean when this was taken
errand: 0.1.0                        # which errand wrote it
status: PASS                         # PASS | FAIL | SKIP
error: null                          # the message, for FAIL and SKIP
duration_s: 12.406                   # the work, not the waiting
ram_mb: 1840.2                       # peak RSS
params: { n: 5000, method: newton }  # what was asked for
tags: { driver: jax, fp: "64" }      # the environment that was selected
results: { seconds: 12.406, iterations: 31 }   # whatever the body put in p.results
output_file: output.txt              # or null, when the body printed nothing
```

The directory is dated to the **day** — that is what a path can carry and stay readable — so the
record carries the hour, with the offset it was written under. Two runs of the same case on the same
day land in the same directory, and `date` is what tells them apart.

A few things worth knowing:

- **`duration_s` excludes the waiting.** How long the machine was busy is not part of how long the
  work took, and counting it would make a benchmark's numbers depend on who else was around.
- **`commit` and `dirty` are provenance, not policy.** errand records that the tree was dirty and
  runs anyway.
- **A value that did not mean to be serialized degrades to its `repr`** rather than taking an
  otherwise good run's result file down with it.
- **`file` is relative to the root when it is under it, absolute when it is not.** A file reached
  through a symlink must not cost a run its record.

`output.txt` is written **as the run talks**, not at the end: it is the only place a case running
over there, or beside seven others under `-j`, says anything at all. So `tail -f` works on it, and
so does [the screen](./tui), which is the same thing.

It is absent, and `output_file` is `null`, when the body printed nothing.

Write anything else you like into the same directory — an `.svg`, a `.vtu`, a folder of frames.
For an errand entry, `p.out_dir` is that directory; a script or a command gets it as
`ERRAND_OUT_DIR`, set only with `-o` or `--out`:

```python
if p := experiment( "the shape of it" ):
    plot( ).savefig( p.out_dir / "shape.png" )
    ( p.out_dir / "frames" ).mkdir( )
```

## Summaries

Above the runs there is a `summary.yaml` at the case's root, one row per run and the extents across
them all. That is what you read after a matrix.

It is recomputed on every run by **re-reading the neighbouring `result.yaml` files** rather than
kept in a ledger, so it is always right and repairs itself. Delete it, or delete half the runs, and
the next one puts it back correct.

Numeric values in `p.results` are summarized (min and max) at every level above the run, which is
what makes two dates or two machines comparable without you declaring anything:

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

**Numbers are kept per key.** Folding `seconds` and `iterations` into one min/max would put a
stopwatch and a counter in the same interval and say nothing about either; what a history is for is
watching one quantity move.

**One value prints as a value, a spread prints as a pair** — `seconds: 12.4` against
`seconds: [ 11.9, 12.4 ]`. A row that has not moved should not look like it has.

Only numeric entries of `p.results` are summarized. A string you record is kept in `result.yaml` and
left out of the extents, which is what you want for something like `ftype: FP32`.


::: info Known to be unresolved
What a summary should say *across* places. Min and max per row are enough to read, but deciding that
a machine got slower is a different question, and one that wants to know something about noise.
:::

## What else is on disk

Everything errand writes for a project is in one directory at its root, `errand-outputs/`:

```text
errand-outputs/
  runs/       the record of every run, laid out as above
  builds/     what errand built and its records of it: records/ ( one yaml per artefact, and the
              build logs ), windows/ ( the Windows images )
  state/      errand's bookkeeping: plans, the command history the screen reads, the handles of
              detached submissions, the output kept for `errand attach`
```

| | |
|---|---|
| `errand-outputs/` | the project's: every run, what was built, errand's bookkeeping. Untracked — `errand init` adds it to `.gitignore` |
| the queue | a directory of claims, one per user per host, outside any project. `errand queue` reads it |

`runs/` is what you open; `state/` is not meant to be read. The queue is state about *this machine
right now*; `errand-outputs/` holds every run's record, and what a tree cannot say — which runs
belonged to one submission, and what was built from which declaration.

## Where the tree goes

`errand-outputs/` is `errand.configure( outputs_directory = "errand-outputs" )`, relative to the
project root or absolute — overridden for one machine by `ERRAND_OUTPUTS_DIR`, a scratch disk or a
shared filesystem. `builds/` can go elsewhere on its own with `builds_directory`. See
[Configuration](./configuration). Those are the paths errand writes to, and they are the whole
state: there is no database, no ledger and no daemon. Delete `errand-outputs/runs/` and you have
deleted the records of the runs, nothing else. For everything errand writes, in the project and
out of it, and how to put it on another disk, see [Where errand writes](./storage).

A project that had a `.errand/` and a `runs/` from an older errand has them moved into
`errand-outputs/` the first time errand runs there — and over there at the next push — once.

## Next

[Running elsewhere](./layers/ssh) — and why the paths above being *computable* is what makes a remote
run work at all.
