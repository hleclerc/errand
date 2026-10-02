# Where the output goes

**Two directories to find a case, then one flat list of its runs**, each cleared and recreated as it
starts. Only the run directory is cleared; everything above it accumulates.

```text
runs/{file}/{name}/{when}-{place}[-{params}]/
runs/{file}/{name}/latest -> the newest of them

runs/solvers/cost/2026-09-25_18h04m11-gpu@gpu-box-method=newton,n=5000/
runs/solvers/cost/2026-09-25_18h11m02-local@laptop-method=cg,n=5000/
```

The file and the name are how you *look* for work — they are what you typed to run it — so they are
directories. Everything that tells two **runs** of that case apart is one directory name, in the
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
[`experiment`](./declaring-work#test-bench-track-experiment) sets `stable_path` for.

## What lands in a run directory

The leaf always holds `result.yaml`, plus `output.txt` if the body printed anything.

```yaml
name: cost
file: bench/solvers.py
line: 42
kind: bench
date: 2026-09-25T18:04:11+02:00     # the directory carries the day; this says when
env: gpu
place: gpu@gpu-box
host: gpu-box
commit: 4f2a1b9           # + dirty: true when the tree was not clean
errand: 0.1.0
status: PASS
duration_s: 12.406
ram_mb: 1840.2
params: { n: 5000, method: newton }
tags: { driver: jax, fp: "64" }
results: { seconds: 12.406, iterations: 31 }
output_file: output.txt
```

The directory is dated to the **day** — that is what a path can carry and stay readable — so the
record carries the hour, with the offset it was written under. Two runs of the same case on the same
day land in the same directory, and `date` is what tells them apart.

`output.txt` is written **as the run talks**, not at the end: it is the only place a case running
over there, or beside seven others under `-j`, says anything at all. So `tail -f` works on it, and
so does [the screen](./tui), which is the same thing.

Write anything else you like into the same directory — an `.svg`, a `.vtu`, a folder of frames:

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
what makes two dates or two machines comparable without you declaring anything.

::: info Known to be unresolved
What a summary should say *across* places. Min and max per row are enough to read, but deciding that
a machine got slower is a different question, and one that wants to know something about noise.
:::

## Where the tree goes

`configure( out = "runs" )` — see [Configuration](./configuration). It is the one path errand
writes to, and it is the whole state: there is no database, no ledger and no daemon. Delete `runs/`
and you have deleted your results, nothing else.

## Next

[Running elsewhere](./remote) — and why the paths above being *computable* is what makes a remote
run work at all.
