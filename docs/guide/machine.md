# Sharing a machine

```bash
errand run make -j16                  # shared: waits only if the machine is full
errand run -x ./bench --n 1e7         # a benchmark: the machine to itself
errand run --cpus 8 --ram 16G ./solve # what it needs, so neighbours can be let in
errand run --gpus 1 python train.py   # one card, and told which
errand queue                          # what the machine has, and what holds it
errand wait                           # return once nothing holds it
```

A timing taken while something else ran is not a timing. So every `errand run` takes a claim on the
machine it runs on, and the claims of every errand on that machine — two terminals, two projects,
the same user — are counted together.

## Any command, under the queue

Every run takes a claim, shared unless asked otherwise. It runs once the machine has room for it, on
this machine or on the one its `--env` leads to:

| option | |
|---|---|
| `-x`, `--exclusive` | the machine to itself. What a measurement wants |
| `--cpus N`, `--ram 8G`, `--gpus N` | what it needs, counted against what the machine has |
| `--ranks N` | that many MPI processes, each needing the above ( [Several processes](./mpi) ) |
| `--no-queue` | do not wait, and hold nothing |
| `-n`, `--label NAME` | its name in `errand queue` |
| `-m`, `--mem 8G` | a memory *ceiling*: past it, the command is killed, not the machine |
| `-l`, `--log FILE` | its output goes there too |
| `-q` | no banners |

A run with no `-x` and no resources holds a shared slot: it waits only while an exclusive run holds
the machine or waits for it. An exclusive run waits for what is already running, then holds
everything back while it runs.

An [entry](./declaring-work) can say what it needs itself ( `cpus = 4`, `gpus = 1`, `exclusive` ),
and a `bench` is exclusive by default. The command line adds to it.

## Looking at the queue

```bash
errand queue
```

```text
The machine (gpu-box)
  has  cpus=32  ram=128000M  gpus=2
  nightly  the whole machine  412s  pid 81233
  train.py  gpus=1  gpu 0  35s  pid 81502
  win  cpus=4, ram=8192  1204s  pid 80122  ( kept warm: gives way )
  /run/user/1000/errand-queue-1000-gpu-box
```

`errand wait` returns once nothing holds the machine and nothing waits for it: the end of a script
that must not start before the benchmarks are done.

## An exclusive request is not overtaken

Whatever arrives after a queued exclusive request **waits behind it**. Otherwise a steady stream of
small runs would starve a benchmark for ever.

## A card is assigned, not merely counted

A run that asked for `gpus = 1` is told **which** card, through `CUDA_VISIBLE_DEVICES`
( and `HIP_VISIBLE_DEVICES`, `ROCR_VISIBLE_DEVICES` ). Two runs that both asked for one get different
cards; counting alone would let both use the first. An exclusive run gets all of them.

Claims nest: a process that was itself given cards 2 and 5 sees them as 0 and 1, and hands 0 and 1
down.

## Kept warm, and giving way

What is only kept warm — a [Windows virtual machine](./layers/windows) nobody uses at the moment, a
process that has imported torch ahead ( [`Preload`](./layers/preload) ) — holds a claim that **gives
way**. A run that would fit without it asks for the room and gets it at once, and the warm thing
goes. `errand queue` marks those claims as kept warm. → [Agents and keeping warm](./agents)

## Memory ceilings

With `-m 8G`, where the user's systemd bus allows it, the command runs in a
`systemd-run --user --scope` with `MemoryMax` set: a runaway allocation takes down the command, not
the machine. Without a bus ( over ssh, from cron ) the command still runs, without its ceiling.

## Stale claims are reclaimed

A claim is touched every few seconds while its work lives. One that has not been touched for half a
minute is reclaimed, and its owner, if it ever comes back, is told it lost it. That is how a killed
run is told apart from a long one.

## Waiting is not part of the run

`duration_s` in the [record](./output) counts the work, not the time spent waiting for the machine:
a benchmark's numbers must not depend on who else was around.

## An errand inside an errand

A run started by another run **inherits its claim** instead of queueing. The parent holds its claim
while it waits for the child, so a child that queued would wait for itself.

## Inside a batch allocation

In a [Slurm](./layers/slurm) allocation that errand keeps warm, the allocation is the machine:
errand's queue shares it out between the commands that run in it, with a queue per allocation.

In any other batch job — a Slurm job you submitted yourself, or another scheduler's, recognized by
its variables — errand does not queue at all. The scheduler has already decided what
this process may have, and a second queue would only wait for itself.

## Where the queue lives

One queue per user and per machine: a directory of claims in `$XDG_RUNTIME_DIR`, else the temporary
directory, named after the machine. No daemon. A home shared over NFS never merges two machines'
queues.

## Next

[What is running](./status): everything errand started, on every machine.
