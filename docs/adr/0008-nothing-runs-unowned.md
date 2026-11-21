---
status: accepted
date: 2026-11-14
---

# Nothing runs unowned: an owner on each machine, a ledger here

On 2026-11-14 a QEMU started by errand ran on lmo for an hour and a half, and no errand command
could see it or stop it. QEMU was started with `-daemonize`, so its parent was init. Its keeper,
the only process that knew about it, ran on the Mac and drove it one line at a time through the
agent. The keeper got a SIGTERM. While it was stopping it lost the connection, and it never got as
far as the kill. Its claim on lmo was released, because that claim was tied to the keeper's stream.
`errand status` did not list it: status reads one project's records, and the VM's state was in
`~/.cache/errand/vm/` on the Mac.

Two read-only audits then went through every kind of process errand starts. A process whose kill or
idle exit depends on a Python `finally`, a signal handler, or an ssh line that may fail can be left
behind. That is the case for the VM keeper, for the processes of an agent that dies, for the
SIGTERM-then-SIGKILL escalation (its timers run in the client), for the zygote, and for Windows
processes whose parent has already exited. `errand status` misses everything per user: VMs, warm
allocations, zygotes, remote claims, guest runs, and agents that no live hub knows about.

ADR 0005 places agents at each level of the chain. This ADR gives them one more job: **each agent
owns what it starts, on its own machine, and the only things allowed to end that ownership are the
process's own end or a kill.**

## Decision

**The owner is on the same machine, and it writes what it owns to disk.** Every process an agent
starts gets a record in its `proc/<id>/meta.json`: the pgid, the process's start time, and the
project root. On Linux the agent is a child subreaper (`PR_SET_CHILD_SUBREAPER`), so what its
sessions start cannot escape to init (not done in step 1, see below). When an agent starts, its
sweep looks at the records left by an earlier life. A record whose pgid is still alive, with the same start time, is killed with
killpg, TERM then KILL, and is not just forgotten. A pid that has been reused, which the start time
detects, is left alone. The ownership chain therefore survives the owner's death: the next owner
finishes the job.

**Escalation belongs to the owner.** Ctrl-C sends one `stop` frame. The agent then runs INT, TERM
after 2 s, and KILL after 5 s, on the whole group. Once the leader has exited, it still sends KILL
to whatever is left in the group. The client's timers go. `--force` on an agent stops its processes
in the same way before the agent exits. An attached agent (apptainer) escalates in the same way.

**The VM keeper is an agent process on the machine that runs QEMU.** `python -m errand.vm keep`
becomes a `keep=True` Proc of the host agent of lmo, so it is counted, listed and stopped like any
other process. QEMU loses `-daemonize`. It is the keeper's child, in its group, with
`PR_SET_PDEATHSIG=SIGKILL`, and its pid is in the keeper's record. A keeper killed outright takes
QEMU with it. A keeper killed together with its agent is swept by the next agent. The claim is taken
by the keeper itself, over there, and no longer by a `queue hold` tied to a stream from the Mac. The
start and use locks move over there too. There is no list of holders: a command that uses the VM
is a session in the guest, and that is what holds it (below).

**What a guest runs keeps its VM up, and nothing else does.** The keeper treats the guest agent as
busy (same rule as the `busy` file of node agents) for as long as a session runs in it; a command
between two of its sessions is covered by the `keep`. A closed laptop does not stop the
VM in the middle of a session. The VM goes after its `keep` once nothing is running there and
nobody holds it.

**Ssh connections notice when they are dead.** `ServerAliveInterval=15` and `ServerAliveCountMax=4`
are on by default, and every question an agent asks about a liveness has a timeout. A half-open
connection, after a laptop sleep or a NAT dropping it, becomes `Lost` within a minute instead of
blocking a `keep` for ever.

**A ledger, per user, here.** Everything a command starts somewhere is written to
`~/.cache/errand/ledger/<id>.json` before it starts, and removed only once its end has been seen:
an EXIT received, a dead pid confirmed, a job gone from `squeue`. This covers runs here, sessions
through an agent, guest runs, preparation phases, the places of a `--batch`, VMs, warm allocations
and zygotes. Each entry gives the project, the kind, the machine, the agent's target, and how to ask
about it. A Ctrl-C that could not be delivered leaves the entry marked "stop requested" instead of
erasing it.

**`errand status` reads the ledger, then asks the owners.** For each machine in the ledger it asks
the agent over there for its whole process table (a new `procs` op: processes, their project, the
claims of that machine's queue). It goes through the hub if one is up, and otherwise through a
`connect` that **starts nothing**: no socket, so it reports "agent gone" and falls back to `kill -0`
over ssh. What an agent runs and the ledger does not know about is shown too. That is how work
started from another machine, or before the ledger existed, is found. By default it shows the
current project in full, then one line per other project or orphan ("guitar_2000: 3 running on
lmo", "lmo: orphaned VM"); `--all` expands everything.

**What is kept warm has a keep, a listing and a stop.** The zygote takes the environment's
`keep_alive`, leaves when its agent leaves, and is shown and stopped by `errand agents`. `errand
agents` also lists VMs, which `errand vm stop` used to cover alone. On Windows, each Proc is put in a
Job Object `KILL_ON_JOB_CLOSE` owned by the agent, which `taskkill /T` is not.

**An agent on every node that runs work, a Windows guest included.** There are two ways to own
a process. A persistent agent outlives its client, keeps sessions, pools what is set up, and
answers `status`. A kernel-held tie (a lock, PDEATHSIG, a process group, a Job Object) ends the
process with whatever it is tied to: certain and cheap, but nothing outlives the link. A node
needs an agent when the link to it can break apart from its processes (ssh, a sleeping laptop),
or when nothing upstream bounds its life (a machine, an allocation). A node whose life is bounded
upstream, like a QEMU guest under its keeper, could do with the kernel tie alone. We put an agent
there anyway, for speed and uniformity: one way to run, stop, list and report on every node.
So `Windows` always has a Python (`python` defaults to a pinned python.org release), errand
always runs in the guest through its agent, and the command handed to cmd.exe over plain ssh
is only a fallback when agents are off. On Windows, each process an agent starts is put,
suspended, into a Job Object `KILL_ON_JOB_CLOSE` whose handle only the agent holds. A stop ends
the whole tree with `TerminateJobObject`, even when the leader has already exited, which
`taskkill /T` cannot do. An agent that dies, however it dies, closes the handle, and the kernel
ends everything it started. Nothing is left for the next agent to sweep.

## Consequences

The guarantee no longer depends on a process that lives somewhere else, nor on a connection that
holds: what runs on a machine is owned on that machine, and an owner's death is finished by the
next owner. The price is one more file per process, a sweep that kills, and an ssh round trip per
machine for `status`. QEMU no longer lives without its keeper, which means a VM can no longer
survive its agent being restarted: an agent that becomes stale (ADR 0005) stops its VM. A
`--batch` run over ssh (`nohup`) remains outside any agent by design, but it is in the ledger and
can be cancelled.

Side fix found by the audit: `result_path_for` (`batch.py`) matched a `--batch` submission to the
result of an earlier run with the same parameters. It also has to check the submission's stamp.

## Order of work

1. The owner: pgid and start time in `meta.json`, a sweep that kills, escalation in the agent,
   ssh keepalive. Tests: SIGKILL of an agent with a running process, then restart; an `sh` that
   ignores SIGINT and SIGTERM; a backgrounded grandchild. *Done, 2026-11-14.* The subreaper is
   not in: a zygote leaves its session on purpose, and what makes itself a session of its own
   (`setsid`) is out of reach of a process group. Only a cgroup would catch it, and that is
   Linux only.
2. The VM keeper under the host agent, QEMU as its child, the claim over there. Real test on lmo:
   `kill -9` of the agent, of the keeper, and of the ssh link, with a VM up. *Done, 2026-11-14*:
   a command's hold is `python -m errand.vm use` (a process of the host agent that may not outlive
   its client), which starts the keeper through the same agent. On lmo: the VM stops after its
   `keep`; errand `kill -9`'d on the Mac lets go of it at once; the keeper `kill -9`'d takes QEMU
   with it (PDEATHSIG); the agent `kill -9`'d leaves the keeper running, and the next agent kills
   it. Still open: "a session runs in the guest" (agents' `running` files) was not tried on a
   guest with a Python. An install driven over ssh still starts QEMU with `-daemonize`: it is a
   foreground command, but its QEMU outlives it if it is killed.
3. The ledger and `procs`, `status` across all of it, without starting anything. *Done,
   2026-11-15*, simpler than written above: the records each agent keeps on its machine are the
   truth, so the ledger only says **where to look** (one entry per ssh machine reached, kept two
   weeks), not what runs. `python -m errand.agents table` reads a machine's agent directories from
   disk (an agent's lock says whether it lives, pid and start time whether its process does), the
   VMs whose keeper is there, and each guest that is up, over its ssh. `status` runs it here, and
   over one ssh per ledger machine, after shipping errand's sources if needed: no agent is asked,
   none is started, and a dead agent's orphans show. On Linux, a process carrying
   `ERRAND_AGENT_DIR` whose agent is gone and that no record holds is shown as unowned: that is how
   two trainings started on lmo by an errand from before step 1 were found, their agent's directory
   removed under them. The neighbour sweep now keeps a directory with a record that cannot say it
   ended. Every `meta.json` records the pid, and the project's store. Not done: the queue's claims
   in the table, and `--batch` work over ssh (still in `errand status`'s batch part).
4. Zygote, Windows Job Objects, foreground Slurm (`scancel` of `$SLURM_JOB_ID` on stop), the
   watcher on a lost connection. *Windows part done, 2026-11-15*: `Windows.python` defaults to
   3.13.16 and every guest runs through its agent; Job Objects in `agents/winjob.py`. Tested in a
   real guest on lmo (sdot-ffi's image): a detached grandchild whose parent has exited goes on a
   stop; Ctrl-C on the Mac ends the session, its script and the grandchild; `taskkill /F` of the
   guest agent takes its whole tree with it. *The rest done, 2026-11-15*:
   - A process can leave its owner a word for its stop: the agent gives it `ERRAND_PROC_DIR`, and a
     shell line written there as `on_stop` is run when it is stopped, by its agent or, for an
     orphan, by the next one -- last, once INT and TERM had their chance. A waited `srun` / `salloc` is named `errand-<id>` and leaves
     `scancel --name` there (by absolute path: an agent's PATH may lack the profile's). Not tried
     on a real cluster yet.
   - The zygote keeps as long as its agent (`ERRAND_AGENT_KEEP`), goes as soon as its agent's pid
     is gone (`ERRAND_AGENT_PID`), killing what it forked, and writes its pid: `table` lists it,
     `status --all` and `errand agents` show it. `errand agents` lists this machine's VMs too.
   - The watcher of a watched Slurm job always says its end (an exception no longer kills its
     thread silently), treats any failed question as one lost question, and retries `scancel`,
     saying so when it could not.
   - Ctrl-C that cannot reach the work (a stream already lost) keeps the live record, marked
     `stop_requested`, instead of erasing it; `status`'s "left running" reads the tables, and no
     longer starts an agent to ask.
   - An install driven over ssh starts QEMU as a `keep=False` process of the host's agent: the
     command gone or cut off, the agent stops it. `-daemonize` only with agents off. Not run on a
     real install.
   - Side fix: a result carries its command's `stamp`, and a `--batch` submission only takes the
     results of its own stamp.
   - *2026-11-20*: `errand stop ID...` ( `--mine` ): the same `kill` as `k` in `errand tui`, from the
     command line, by the id `status` shows, on whichever machine runs it ( this one directly, another
     through its agent ). The kill op takes `wait`: the escalation is done before the answer, so a
     command that leaves sees the end. A run waiting in a machine's queue is a process of its agent
     like another: stopped, its `waiting/` request goes ( a dead pid is dropped at once ) and what was
     behind it moves up. A `--batch` submission is stopped by its handle ( process group, `scancel` ).
     `errand stop` alone, at a terminal, lists what runs or waits and asks which; `status` shows the ids
     of the projects it says in one line.

## Settled with Hugo, 2026-11-14

1. VM holders: no lease. The busy guest, then the `keep`.
2. `status`: the current project in full and one line per other project, `--all` to expand.
3. An agent that dies: the next one kills its processes, it does not adopt them.
4. Order: the owner first (step 1), then the VM.
5. An agent on every node, a Windows guest included (option B, 2026-11-15): for speed and uniformity.
