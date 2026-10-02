# Detached runs

`--batch` launches the work and gives you the shell back. It is a **mode, not a layer**: it means
the same thing in every context, and what changes is only how each one lets go.

```bash
errand --batch -k bench --env gpu,cluster --fp 32,64
  submitted b7f3 - 8 run(s) - 4 on login.hpc (batch 918273), 4 on this machine (local 41288)
  errand --status    errand --watch
```

| context | waiting | detached |
|---|---|---|
| local | subprocess | a session of its own, which survives the terminal |
| `Ssh` | ssh, output streamed | started over there and released, output to a file |
| `Slurm` | `srun` | `sbatch`, which *is* the detachment: it returns as soon as the job is queued |

Nothing else about the run changes — same paths, same queue, same output.

## The output tree is the state

Because [the paths were worked out before anything started](./output#the-three-parts-of-a-run-s-name),
**the arrival of a result file where one was expected is itself the completion signal.**

No protocol between the two sides, no daemon, nothing that can get out of sync.

What is kept locally is only what the tree cannot say — which runs belong to one submission, and
what handle each place was given. The side that expanded the matrix is the only one that ever knew
those runs went together.

### Where a run happened is looked for when it cannot be known

A run detached on this machine has a predictable place, and the record says so. A remote one does
not — it carries the other machine's name — and neither does a batch job, which carries the name of
whichever compute node the scheduler picked.

The parameter directory *is* predictable in every case, so that is what gets searched, and the
result naming this run's environment and parameters is the one.

## Keeping track

```bash
errand --status        # one shot, plain text
errand --watch         # the same, live, until everything has landed
errand --forget b7f3   # drop a submission from the list, keeping its results
```

```text
b7f3  -k bench --fp 32,64 --env gpu,cluster   2026-09-24 12:04   6/8 [######  ]
    gpu: local 41288 on this machine - finished
    cluster: batch 918273 on login.hpc - running
                        gpu@thishost            cluster@node15
      cost  fp=32, n=1000   ok seconds=12.4        ok seconds=13.1
      cost  fp=32, n=5000   ok seconds=61.2        ok seconds=64.8
      cost  fp=64, n=1000   ok seconds=11.2        ...
      cost  fp=64, n=5000   ...                    ...
```

Grouped by submission, because that is the unit you launched and the unit you will compare.

Inside one, the matrix reads as a **table** — parameters down, places across — since that is the
shape it has, and a flat list of eight lines hides the one axis you were varying. A cell shows the
[kept](./declaring-work#the-four-traits) number once there is one, so a column slower than its
neighbour is visible without opening anything.

`--watch` holds no state of its own: it polls the tree and the batch systems, so it can be started,
killed and restarted at any point, and several can watch at once.

## The same thing on a screen

[`errand --tui`](./tui) shows this table on its runs page, over the same tree. Tick `detach` in the
launch window, close the window, open it tomorrow: the state was never in the screen.

## Results come back when you ask

A finished remote run sits there until something collects it. `--status` and `--watch` are what
collect it — results are [pulled, not pushed](./remote#results-are-pulled-not-pushed).

## Next

[The screen](./tui).
