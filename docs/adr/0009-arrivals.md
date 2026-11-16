---
status: accepted
date: 2026-11-15
---

# Arrivals: what is asked for, may come late, and is owned meanwhile

ADR 0008 puts an owner on every machine, beside what it runs. It leaves a gap: the time between
asking for something and its owner being there. A Slurm job waits in the queue, and no agent runs on
any node yet. A VM boots, and its guest agent does not answer yet. A bridge has started an agent that
does not listen yet. During that time the thing exists somewhere, or is about to, and nobody over
there owns it. If the command that asked goes away, what was asked for can still arrive later, with
nobody to take it.

The same review found that errand reaches a Slurm cluster in two ways, and that only one of them has
an owner on the node. The other is a bare `srun` whose stop depends on Slurm's own handling of a
killed `srun` or `salloc`.

## What waits today

Checked in the code on 2026-11-15.

| Where | What is asked for | Who waits, where | Deadline | If the waiter goes |
|---|---|---|---|---|
| Slurm, waited (`srun`, `salloc`) | a job in the queue | `srun` on the login node, a process of its agent | none | `on_stop` cancels it by name (ADR 0008) |
| Slurm, held warm (`alive.py`) | an `sbatch` whose batch step is an agent | a shell loop on the login node, polling `squeue` every 2 s | none | the job stays queued; once it runs, its agent leaves after `max( 30 s, keep / 4 )` unused |
| Slurm, watched (`watch`) | an `sbatch` job | `watch_job` on the client's side | none | the job runs to its end; Ctrl-C cancels it |
| errand's queue (`queue.claim`) | room on a machine | the process that claims, polling | none | its waiting file goes with it |
| VM (`using.py`, `keeping.py`) | room in the queue, then Windows booting | the hold, then the keeper, on the QEMU host | `BOOT_TIMEOUT` for the boot only | the keeper goes after `keep` |
| An agent started by a bridge (`daemon.connect`) | an agent that listens | the bridge | `WAIT` = 15 s | the agent goes after `keep_alive` |
| A zygote (`warm.session`) | a zygote that listens | the session | `WAIT` = 20 s, then cold | the zygote goes with its agent (ADR 0008) |
| An environment agent, a container's attached agent | a bridge through the layers, then an agent | the client, through the host agent | the ping's 30 s | same as an agent |

## Decision

**An arrival** is a thing asked for that is not owned yet where it will run. Every wait uses that
word and shows in `errand status`. The full rule below (a lease, leaving when nobody waits) applies to
what holds resources for long: Slurm allocations and VMs. Short starts (a bridge, a zygote) keep
their deadline of a few seconds and nothing more.

**Until it arrives, it is owned by the agent of the process that waits for it**, on that process's
machine. The process writes in its record (`ERRAND_PROC_DIR`) a `waiting` file (what it waits for,
since when, for whom, the job's id), updated as the state changes. `table` reads it, and `errand
status` shows it ("slurm job 81234 pending, 2 h 10"). Where something must be cancelled when the
waiter is stopped, the waiter writes a `cancel` line there too (the `on_stop` of ADR 0008, renamed).
It stays armed while the waiter lives, and runs only at the end of a stop.

**Everything is shared.** An allocation and its agent are shared: every command of the environment
that fits in it runs there. What runs in it is exclusive by default: a command claims the whole
allocation in the node's errand queue, or only the part it declares (`--cpus`, `--gpus`, the
entry's own needs), and another command then runs beside it. A command that does not fit in what is
left asks Slurm for another allocation, with its own agent and shared in turn. One that fits but
finds the allocation busy waits in the node's queue, and says what it waits for.

**A shared arrival holds no cancel; it holds leases.** Each command waiting for an allocation touches
its own `wanted-<id>` beside the allocation (`~/.cache/errand/alloc/<name>/`, on a file system the
login and compute nodes share) every 30 s. When the allocation's agent starts and finds no lease
fresher than 60 s, it leaves at once, and the job ends. Where no lease can be read (no shared file
system), the idle delay of today applies. A job still queued costs nothing, so a waiter that goes
cancels nothing.

**Every Slurm command goes through an allocation with an agent on its first node.** The bare `srun`
disappears: `keep_alive = 0` is an allocation for one command, given back when it ends. `errand
shell` is a terminal through the node's agent. MPI ranks are started by that agent, with an `srun`
inside the allocation, as in the warm allocation today. A watched job (`watch = N`) stays as it is,
an exception: one `sbatch` per command, asked about from afar, owned by Slurm and its `--time`.

**An allocation can be sized apart from the commands it serves:** `Slurm( allocation = { "time":
"2:00:00" } )` asks Slurm for that, the qos computed from it (to land in a priority queue up to its
threshold, Jean Zay's `-dev`), and commands run in it as long as they fit in what is left (time,
GPUs: `alive.fits`). What `allocation` does not say comes from the command. The allocation is given
back after `keep_alive` without use, so asking for the threshold costs only what is used.

**The VM already follows the rule:** its keeper owns it on the QEMU host, `use.lock` is the lease,
and `keep` is the delay. One addition: a VM that has never served, and that nobody holds once it has
booted, stops at once instead of after its `keep`.

**Queues have no deadline by default:** a cluster's queue may take hours, and that is normal. Every
wait records when it started, and `status` shows it. An option (`wait =`) comes only when a need
does.

**There is no mode without agents any more.** `ERRAND_AGENT=off` goes, and with it every fallback
it needed: the bare `srun`, the cmd.exe line handed to a Windows guest over ssh, one ssh per remote
command. The modes left are `hub` and `direct`. One way to run, stop, list and report on every node
is simpler to read and to keep right than two.

## Consequences

The Slurm path becomes one: the warm allocation's mechanism serves every command, with `keep_alive`
saying only how long an unused allocation stays. Its shell loop on the login node becomes the waiter
of an arrival: it writes `waiting`, touches its lease, and is a process of the login node's agent,
stopped with it. A command's resources are carved in the node's queue rather than by Slurm, which
lets several small commands share one allocation that went through the queue once.

Removing the agentless mode removes code from `drive.py`, `there.py`, `gateways.py`, the Windows
layers and `machine.py`. The `-daemonize` fallback of an install goes too.

## Order of work

1. Remove `ERRAND_AGENT=off` and its fallbacks. *Done, 2026-11-15*: `ERRAND_AGENT=off` is now an
   error that names this ADR. `Over.shell` always goes through the host agent (no ssh per line, no
   "no agent" warning); `drive` has no agentless session; every VM and box command and `errand
   shell` go through the guest's agent, and `Windows.run` / `WindowsBox.run` refuse; `Ssh.run` no
   longer hands a command to a gateway behind it; an install over ssh runs QEMU as a process of the
   host's agent, with no `-daemonize`. `ship` and `_remote` keep their plain ssh in `direct` mode:
   that is how an agent gets there in the first place.
2. Records of arrivals: `waiting` and `cancel` (renamed from `on_stop`) in a process's record, `table`
   and `status` showing them. *Done, 2026-11-15*: `agents/arrival.py` (`waiting( what, job, key )`,
   `arrived()`, and `SHELL_WAITING` for scripts) writes `$ERRAND_PROC_DIR/waiting`; a state change
   keeps the wait's start. It is said by errand's queue (room on a machine), a command's hold on a
   VM (another command uses it, queued, booting) and the loop that waits for a warm allocation
   (slurm job pending, configuring). `status` shows "waiting: slurm job 81234 pending, 2 min" in
   place of "running"; a command's hold on a VM now shows under its project, the keeper with the
   machines. Not tried for real: a Slurm wait (no cluster used this time), a VM booting.
3. Slurm: every command through an allocation with an agent; the node's queue carves it; a command
   that does not fit gets another allocation; `keep_alive = 0`; `errand shell`; leases and an agent
   that leaves when nobody waits; `allocation = { … }`. *Done, 2026-11-15*: `Slurm.wrap` gives only
   `sbatch` ( watched ); every other command goes through `alive.Allocation`, sized by
   `allocation = { … }` and by the command's own needs when it does not fit the declared one
   ( another allocation, its own agent ). Inside, `ERRAND_ALLOCATION` makes the node's queue carve
   the allocation ( CPUs from the affinity, memory from Slurm ), and a command that says nothing takes
   all of it. `keep_alive = 0` is an allocation for one command ( node agent 5 s ); `errand shell` is a
   terminal through the allocation's agent. Leases: the waiting loop touches `wanted-<pid>` every 2 s,
   removes it on any stop ( `trap` on INT TERM HUP: `sh` takes none of them as an EXIT ), and leaves
   when whoever started it is gone ( `sshd` sends a command without a terminal no signal ); the
   job's script gives the allocation back at once when no lease is younger than a minute. Two holes
   found by the real run and closed: the hub kept making a bridge whose command had gone ( it now
   kills it when the last command waiting for it goes ), and without a hub a TERM killed the client
   but left its bridge ( `upstream.direct` ends its bridges on TERM, HUP and exit ). And without a
   hub, the waiting loop ( and an environment's or a guest's agent line ) went by a plain `ssh`, around
   the host's agent: `status` could not see it, nor the ledger the machine. `rsh` now carries the mode of
   the command that made the line, and opens the host agent itself when there is no hub. Not covered: a
   client killed by SIGKILL in `direct` mode leaves its local `ssh`; the loop then waits on.
   Tried for real on cinaps ( node22 ): a command through an allocation ( `ERRAND_ALLOCATION` and
   `SLURM_JOB_ID` set ), the allocation given back after its keep, a pending command stopped by
   `timeout` leaving neither loop nor lease. Not tried: Jean Zay ( its environments are watched ),
   a job starting with no lease ( two are queued on node22 for that ).
4. The VM that never served stops once booted if nobody holds it. *Done, 2026-11-15*: once ready,
   the keeper marks the machine as not served yet; the first time a command holds `use.lock` or a
   session runs in the guest, it has served. Until then, nobody using it means `keep` is ignored, and
   the machine stops at the next check ( 2 s ). The hold that asked takes `use.lock` before the boot
   ends, so a command still there when Windows answers counts as served. Tried for real on lmo
   ( win-numpy, image installed in 41 min ): a command stopped by a TERM while the VM booted -- `ready`
   at 22:52:44, `stopped` and QEMU gone by 22:52:49; a command run to its end -- the VM stayed `ready`
   six minutes after it ( `keep` = 5 min, plus the guest's last `running` ), then stopped.

## Settled with Hugo, 2026-11-15

`grill/arrivals/decisions.md`, four rounds.
