# What is running

```bash
errand status          # this project in full, one line per other project
errand status --all    # every project in full
```

```text
running   ( on mac, lmo: this machine, and every machine work was sent to from it )
  sdot-ffi
    lmo          3f2a9c1e  run tests/test_w2.py::*  --env lin  12 min  running
    jz           7c01d2aa  run train.py  --env jz            2 min   waiting: slurm job 81234 pending, 2 min
  guitar_2000: 2 running on lmo
  lmo: windows vm 80103674 ready, 8 cpus 16G
```

One command answers the question you otherwise answer with an ssh per machine, a `ps`, a
`squeue` and a guess: **what did I start, where, and is it still there?**

## What it shows

- **Runs**, wherever they are: here, over ssh, in an allocation, in a container, in a Windows guest.
- **Where a run is**, when it says so with [`errand.step`](./steps): `running · iteration 41 · ▕████▏      ▏ 41 %`.
- **What waits** for something that is not there yet, in place of `running`:
  `waiting: slurm job 81234 pending, 2 h 10`, `waiting: room on lmo: gpus (0 free of 2, needs 1)`,
  `waiting: windows vm 80103674 booting`.
- **What is kept warm**: an allocation held between commands, a Windows VM, environment agents and
  processes with torch already imported (`Preload`). Agents and zygotes are counted on one line;
  `--all` lists them.
- **Orphans**: a process whose agent died. The next agent on that machine stops it.
- **Unowned** processes (Linux): something errand started that no record holds any more, an older
  errand's for instance. It is shown with the `kill` that stops it.
- **Commands whose connection was lost**: still running, or finished and waiting for
  [`errand attach`](./detached#close-the-laptop) to bring the results back.
- **`--batch` submissions**, and how they are doing. → [Let it run](./detached)

A machine that cannot be reached is listed as `cannot say`, with the reason, not silently skipped.

## Stopping a run

```bash
errand stop 6575aafc            # that one, wherever it runs ( a prefix of its id is enough )
errand stop 6575aafc ea9ec989   # several
errand stop b7f3                # a --batch submission, by its id
errand stop --mine              # everything this project runs, on every machine
errand stop                     # at a terminal: what runs or waits, numbered; answer 1 3, 2-4 or all
```

The id is the one `errand status` shows: on each run's line for this project, at the end of the
line of another project ( `--all` shows its runs in full ). The run is found where `errand status` finds it, then its
machine's agent stops it as `k` in `errand tui` does: INT, TERM after 2 s, KILL after 5 s, to its
whole process group, then what it said must happen when it stops (a Slurm job it queued is
cancelled). `errand stop` comes back once it is gone, and `errand status` no longer lists it.

A run **waiting** for room in a machine's queue ( `waiting: room on node14: the machine to itself` )
is stopped the same way: its place in the queue goes with it, and what waited behind it moves up.
This is how work left queued by a command stopped on this side is removed, without `errand tui`.

A `--batch` submission was let go by a handle, not given to an agent: `errand stop` ends its
process group here or over ssh, or `scancel`s its job. Its record stays, with what it wrote;
`errand forget ID` drops it. A process in a Windows guest, or on a node of an allocation, is not
stopped from here: `errand vm stop`, `errand agents stop`, or its own command.

## How it knows

Every machine errand runs work on has an [agent](./agents). The agent writes down each process it
starts, in its own directory, on that machine: the process group, its start time, the project.

`errand status` reads those records. It reads this machine directly, and every machine work was
sent to from here over one ssh each. The list of those machines is the **ledger**,
`~/.cache/errand/ledger/`, which keeps a machine for two weeks after its last use. Nothing is
started to answer: no agent, no allocation, no VM.

A Slurm allocation kept warm runs its agents on a compute node, where the login node can read
neither their locks nor their processes. So for each allocation whose job runs, `errand status` asks
its first node the same question, with `srun --overlap` inside the job: nothing new is asked of
Slurm. Its rows show as `login > node`.

Typed on a machine that runs work (a lab server, say), `errand status` shows everything its agents
run, whoever started it and from wherever.

### The machines asked

The machines are those work was sent to from here: errand keeps them, and forgets one after two
weeks without work sent there. Looking at a machine ( `errand status`, `errand tui` ) does not keep it.

```bash
errand machines                       # which, most recently used first
errand machines forget h              # not asked any more, until work is sent there again
errand machines rename cinaps lab     # shown as `lab`, whatever name reaches it
errand machines watch jz on           # always contacted ( auto: while work is sent there )
errand machines gauges jz off         # its CPU / memory / GPU gauges not measured; what runs there still followed
```

A machine reached under several names ( `cinaps` and `hugo.leclerc@cinaps` ) is one: the same ssh
name but for the user, the same label, or the same hostname answered. It shows its oldest name, or
the label it was given.

A machine no work was sent to for a day is **dormant**: neither `errand status` nor `errand tui`
contacts it, so that no agent of errand's starts for nothing on a machine others share ( a cluster's
login node ). `errand status` names it; `errand tui` shows it greyed. `a` on a dormant machine in
`errand tui` or `errand web` watches it from now on; on a machine watched, `a` switches its gauges off
( or on again ): no CPU, memory or GPU measured there, what runs there followed all the same. Both are
saved. `errand agents stop` contacts every machine, dormant or not.

In `errand tui`: `f` forgets the machine under the cursor, `r` names it, `k` kills what runs there,
each once confirmed. Forgetting a machine stops nothing over there: `k`, or `errand agents stop`, does.

## Stopping work

| what | how |
|---|---|
| the command in front of you | **Ctrl-C**. It reaches the work through every layer |
| everything kept warm | `errand agents stop` |
| what matches a name | `errand agents stop gpu` |
| an agent that still runs something | `errand agents stop --force` |
| everything, then this machine's agent and page again ( errand changed ) | `errand agents restart` |
| Windows VMs, here and over every `Ssh` | `errand vm stop` |
| a `--batch` submission | see [Let it run](./detached) |

Ctrl-C is handled by the agent over there, not by the errand in front of you: an interrupt first,
a terminate after 2 s, a kill after 5 s, on the whole process group. It happens even if your
laptop's connection is already gone. → [Agents: Ctrl-C](./agents#ctrl-c-stops-the-work)

## What happens when something dies

| what dies | what happens |
|---|---|
| your laptop sleeps, the network drops | the work goes on; `errand attach` picks it up |
| the errand command you typed | its agent stops what it started (unless it was `--batch`) |
| an agent, by SIGTERM or a logout | it stops what it runs before it goes |
| an agent, by SIGKILL or the OOM killer | the next agent on that machine finds what it left and kills it |
| a VM's keeper | QEMU goes with it |
| the command waiting for a Slurm job | the job is cancelled; an allocation kept warm ends on its own once unused |

That is the rule behind the whole part: **nothing errand starts runs without someone on that
machine keeping track of it.** The design is in
[ADR 0008](https://github.com/hleclerc/errand/blob/main/docs/adr/0008-nothing-runs-unowned.md) and
[ADR 0009](https://github.com/hleclerc/errand/blob/main/docs/adr/0009-arrivals.md).

## Next

[Agents and keeping warm](./agents) · [Sharing a machine](./machine) ·
[Slurm allocations](./layers/slurm) · [Windows VMs](./layers/windows)
