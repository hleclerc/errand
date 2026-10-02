# Output files

The output tree is the whole state: there is no database, no ledger and no daemon. What a run wrote,
and what errand knows about it, are the same files. See
[Where the output goes](/guide/output) for the shape and the reasoning.

```text
runs/{file}/{name}/{when}-{place}[-{params}]/result.yaml
runs/{file}/{name}/{when}-{place}[-{params}]/output.txt
runs/{file}/{name}/latest -> the newest of them
runs/{file}/{name}/summary.yaml
```

`{when}` is `2026-10-02_14h22m07` — one stamp for the whole invocation. `{place}` is `{env}@{host}`.
`{params}` is what was asked for in words, cut at a readable width with a short hash on the end when
there is more of it than anyone would read.

## result.yaml

Every field, in the order it is written:

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

A few things worth knowing:

- **`duration_s` excludes the waiting.** How long the machine was busy is not part of how long the
  work took, and counting it would make a benchmark's numbers depend on who else was around.
- **`commit` and `dirty` are provenance, not policy.** errand records that the tree was dirty and
  runs anyway.
- **A value that did not mean to be serialized degrades to its `repr`** rather than taking an
  otherwise good run's result file down with it.
- **`file` is relative to the root when it is under it, absolute when it is not.** A file reached
  through a symlink must not cost a run its record.

## output.txt

Written **as the run talks**, not at the end. It is the only place a case running over there, or
beside seven others under `-j`, says anything at all — so `tail -f` works on it, and so does
[the screen](/guide/tui), which is the same thing.

It is absent, and `output_file` is `null`, when the body printed nothing.

## summary.yaml

One per directory that holds runs or other summaries, recomputed on every run by **re-reading the
tree** rather than kept in a ledger. So it is always right, and it repairs itself: delete it, or
delete half the runs, and the next run puts it back correct.

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

## latest/

A symlink to the newest run, so every run can be stamped without costing you a stable path. Leave a
tab open on `latest/shape.png` and reload it — that is what
[`experiment`](/guide/declaring-work#test-bench-track-experiment) sets `stable_path` for.

On a filesystem without symlinks its absence is a loss, not a failure: the run still writes
everything else.

## What else is on disk

| | |
|---|---|
| `.errand/` | the per-project working directory: environment records, the command history the screen reads, the handles of [detached](/guide/detached) submissions. Untracked |
| the queue | a directory of claims, one per user per host, outside any project. `errand --queue` reads it |

Neither is anything you need to open. The queue is state about *this machine right now*; `.errand/`
holds what the output tree cannot say — which runs belonged to one submission, and what was built
from which declaration.

## Writing your own files

Anything you like, into `p.out_dir`:

```python
if p := experiment( "the shape of it" ):
    plot( ).savefig( p.out_dir / "shape.png" )
    ( p.out_dir / "frames" ).mkdir( )
    ( p.out_dir / "mesh.vtu" ).write_bytes( mesh( ) )
```

Only the run directory is cleared and recreated as the run starts; everything above it accumulates.
