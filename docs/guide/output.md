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

## On the terminal

```text
lmo · 2 entries  lmo@node12
▸ solve  exp_demo.py:5 · n=3
  │ it 2 residual 1.0e-02                 what the case wrote on stdout
  ┃ warning: slow convergence             on stderr
  ╰ PASS solve  903 ms · residual 0.001
▸ broken  exp_demo.py:15
  ┃ ValueError: the matrix is singular
  ╰ FAIL broken  8 ms  ValueError: the matrix is singular
    ↳ errand-outputs/runs/exp_demo.py/broken/2026-11-18_14h04m33-lmo@node12/output.txt
```

Each case has a header, at the left edge, its output behind a gutter, and an end line that closes the
gutter ( `╰` ), in the column of its output: its status, how long it took,
its results when they are short numbers or words, and, when it failed, where its whole output is.
A failure's traceback shows the case's frames and its libraries', not errand's nor the import
machinery's; `-v` shows them all. A case run elsewhere colors its output as it would on this terminal:
errand sets `FORCE_COLOR` and `CLICOLOR_FORCE` for it when this terminal shows colors, unless
`NO_COLOR` is set or they already have a value. The gutter is drawn on this terminal, never written into the record: copy from `output.txt` to get
the lines as they were. What errand does to get there — the push, errand's sources sent, the pull —
is said on the line at the bottom while it lasts, never in the history: its numbers ( files, bytes,
seconds ) are written in the journal of each run concerned, `steps.jsonl`, as
`{"transfer": "push", "s": 2.05, "files": 8, "bytes": 117108, …}`.

With `-j`, each case is drawn as one block when it ends, everything it wrote in it, whoever wrote it.
While they run, the bottom has a line for each, with its step:

```text
1 ▸ case a · iteration 41 · ▕████▏ 41 % · 2 min left
2 ▸ case b · 12 s
lmo: ssh:lmo -> vars
1-9 / tab: a case in front · esc: back
```

A digit ( the case's number, which stays with it ) or Tab puts a case in front: its last lines scroll
live above the lines, its block still drawn whole at its end. Esc goes back.

### A case that asks

A case reads the keyboard here, wherever it runs, when the keyboard and the screen are a terminal's:

- one case running: type as you would to it, the terminal echoes and edits the line, Enter sends it,
  Ctrl-D ends its input;
- under `-j`: put it in front, then type: the line is edited at the bottom ( `› 12▏` ), Enter sends it,
  and it goes in the case's output as a terminal would have shown it. Ctrl-D ends its input, Esc goes
  back.

A case that wrote a line without its end, then nothing for two seconds, says so on its line:
`⌨ waits for input?` -- a hint, errand cannot know. Off a terminal ( a pipe, a CI log, `--batch` ), a
case run elsewhere gets EOF at once: nothing waits for an answer that cannot come. Run here, it reads
the input errand was given ( `echo 12 | errand run …` ). `--plain` drops the gutter and the colors; `$ERRAND_OUTPUT` ( `bar`, `spaces`,
`off`, `plain` ) or `errand.configure( output = … )` chooses for a machine or a project.

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

- a `back` [zone](./sync#zones), declared once in the project:
  `errand.configure( zones = { "/results": "back" } )`;
- `fetch = [ "build" ]` on a [`Windows`](./layers/windows) or [`WindowsBox`](./layers/windows-box)
  layer, after each command.

Only what was asked for comes back. The rest of the copy over there, and the records of other
runs, stay where they are ( [Results are pulled, not pushed](./sync#results-are-pulled-not-pushed) ).

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
  output.txt       everything it printed, both streams interleaved, a child's included
  stdout.txt       the process's standard output, as written to it
  stderr.txt       its standard error, apart
  model.pt         what it wrote there, with -o
```

**`stdout.txt` and `stderr.txt` are the raw streams**: what the process wrote to its descriptors,
the C library's writes, a child's, and a fault handler's included. `output.txt` is both, interleaved as
they came. On Linux and macOS a small process of its own copies them, and outlives the run: a segfault
or an abort leaves in `stderr.txt` everything written up to the end -- with Python's word on where it
crashed -- and that process writes the run's `result.yaml` for it ( `status: FAIL`, `error: the process
ended during the run…`, no `duration_s` ). On a terminal, it takes the streams through two
pseudo-terminals: what runs still sees a terminal ( colors, progress bars ), and what it shows here goes
behind the gutter. On Windows, what Python writes is copied instead, and a child's output is only shown.

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
