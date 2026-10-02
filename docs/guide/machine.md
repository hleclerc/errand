# Sharing the machine

An entry says what it needs, and nothing gets to ignore it:

```python
if p := bench( "solve" ):                            # exclusive: the machine to itself
if p := test( "wide", cpus = 4, ram = "8G" ):        # a share of it
if p := test( "on the card", gpus = 1 ):
```

`cpus`, `ram` and `gpus` are counted against what the host has. `exclusive` is the blunt version,
for when the answer is "all of it and no neighbours" — and it is what [`bench`](./declaring-work#test-bench-track-experiment)
sets for you.

An exclusive entry waits for what is already running and holds everything else back while it runs;
everything else proceeds as long as the machine has the room.

## The queue lives outside the process

One per user per host, so it is shared by every `errand` on that machine — two terminals, two
projects, no interference. It is a directory of claims, not a daemon.

```bash
errand --queue        # what the host has, and what is holding it
errand --no-queue     # this run does not wait, and does not hold
```

## Any command, under the queue

The queue is not only for entries. A bare `--` with no `--env` runs **that command, on this
machine**, once the queue lets it:

```bash
errand -- make -j16                      # shared: it waits only if the machine is full
errand -x -- ./bench --n 1e7             # a benchmark: the machine to itself
errand --cpus 8 --ram 16G -- ./solve     # what it needs, so neighbours can be let in
errand -l build.log -n "nightly" -- ./all   # a log file, and a name in the queue
errand -q -- ./quiet                     # no banner
```

| flag | |
|---|---|
| `-x`, `--exclusive` | the machine to itself. This is what a measurement wants |
| `--cpus`, `--ram` | what it needs, counted against the host |
| `-m`, `--mem` | a memory *ceiling* for the command (default `8G`, `24G` exclusive) |
| `-n`, `--label` | its name in `errand --queue` |
| `-l`, `--log` | stdout and stderr go there |
| `-q`, `--quiet` | no banner |

A shared command is run at low priority (`nice -n 5`); an exclusive one is not, having nothing to
be polite to. Where the user bus allows it, the command is put in a `systemd-run --user --scope`
with `MemoryMax` set, so a runaway allocation takes down the command and not the machine. Without a
bus — over ssh, from cron — the command still runs, only without its ceiling.

```bash
errand --queue        # what is holding the machine, and what is waiting for it
errand --wait         # return once nothing holds it and nothing is queued for it
```

### An exclusive request is not overtaken

Whatever arrives after a queued exclusive request **waits behind it**. Otherwise a steady stream of
small work would starve a benchmark for ever, which is the one thing a queue is for.

## A card is assigned, not merely counted

An entry that asked for `gpus = 1` is told **which** one, through `CUDA_VISIBLE_DEVICES` (and the
`HIP` / `ROCR` spellings). Two entries that both asked for one get different cards.

Counting alone would let them both pick the first and neither would measure anything.

An exclusive run gets all of them. Claims nest correctly: a process that was itself given cards 2
and 5 sees them as 0 and 1, and hands 0 and 1 down.

## A heartbeat, not a promise

A claim records who holds it and is **touched while the work lives**. One whose timestamp has gone
stale is reclaimed, and its owner, if it ever comes back, finds it gone.

That is the only honest way to tell a killed run from a long one: a benchmark that has been running
for six hours is indistinguishable from a corpse except by whether anything is still breathing. The
same heartbeat answers the same question for [detached runs](./detached) — one mechanism, not two.

## Waiting happens outside the measurement

How long the machine was busy is not part of how long the work took, and counting it would make a
benchmark's numbers depend on who else was around.

## An errand inside an errand

**It inherits the claim** instead of waiting for it. The entry that started it is holding one while
it waits, so a child that queued would be waiting for something its own parent cannot release until
the child is done.

Same rule as the batch systems: what has already been granted is not asked for twice.

## When somebody else owns the machine

Inside a Slurm, PBS, OAR, LSF, SGE or Flux allocation, `errand` does not queue at all. The scheduler
has already decided what this process may have, and a second queue on top of it would only wait for
itself.

What the work asks for is **handed over** instead: the [`Slurm`](/reference/layers#slurm) layer
turns the entries' `cpus`, `ram`, `gpus` and `exclusive` into `--cpus-per-task`, `--mem`, `--gpus`
and `--exclusive` on the submission. A dispatched command carries several entries, so the allocation
is the largest of them, and exclusive if any one of them is.

**What the environment states explicitly wins:** whoever wrote `Slurm( cpus = 16 )` knew something
about that partition an entry cannot.

**Everything is optional, `partition` included.** What is not stated is not passed, and the cluster
applies its own default — which stays correct when the cluster is rearranged, and a name copied out
of somebody else's script does not.

```python
# errand-envs.py
import errand

errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "login.hpc", root = "/home/me/proj" ),   # NOT /tmp
                                         errand.Slurm( time = "2:00:00" ) ] )                        # the default partition
```

::: danger The root must be on a shared filesystem
A batch job runs on a compute node, and `/tmp` there is not the `/tmp` you pushed to. The job lands
somewhere that has never heard of your project, and says so in terms of a failed `chdir` followed by
an import error, neither of which points at the cause.

`errand` checks for that before submitting and tells you plainly.
:::

## Next

[Where the output goes](./output) — the other half of a shared machine is knowing whose numbers are
whose.
