---
status: proposed
date: 2026-11-12
---

# The local side orchestrates, agents execute, and a hub keeps them alive

Every command crosses its whole stack again, each time. With `ssh lmo $SHELL -ic 'micromamba -n x run
python -m errand run …'`, one ssh connection costs about 600 ms and `micromamba run` 1.4 s. A run
over `Ssh` makes six to eight connections, for push, sources, run and pulls, so 5 to 7 s go by before
the work starts. It pays that twice when it prepares and then runs. ssh is only the most visible of
these costs: apptainer, a module, a VM boot all pay theirs again on every command. Nothing stays
warm either, neither the imports of jax or torch, nor a collected suite, nor an initialised GPU. And
the errand started over there is a second orchestrator, which re-selects, re-resolves and records
on its own side. That is why ADR 0002 needed plans, phases and fetch-backs to keep the two in step.

So we stop crossing the stack per command. Long-lived **agents** sit at the levels of the stack, and
one **local** process drives them. This replaces the "who drives" half of ADR 0002 and keeps its
rule: targets are resolved in the environment.

**The hub.** There is one process per user on the machine errand is typed on. It starts on demand
and owns every channel. `errand` commands become thin clients of it, talking over a unix socket, or
over TCP on 127.0.0.1 with a random token in a user-only file on Windows. It stops after
`keep_alive` minutes without activity. Activity means a command in progress, a screen open, or a
process still alive somewhere below. When it stops, it stops what it started. `--no-agent`, and any
errand without a terminal (cron, CI, inside an allocation), runs the same hub inside the command's
own process instead of as a daemon. There is one code path with two lifetimes, so there is no
one-shot fallback to keep alive. The Windows VM keeper (`python -m errand.vm keep`) was a hub for
one kind of layer, and goes. `errand vm stop` becomes `errand agents` and `errand agents stop
[name]`.

**Two levels of agents.** A **host agent** runs right after a `Gateway`, the layer that leads
elsewhere (`Ssh`, a VM). It runs on the Python `bootstrap` finds or makes over there, and handles
files, setup, the machine's queue and submissions. Every `host.shell( line )` of today's code goes
through it. An **environment agent** runs at the end of a stack, with the environment's own
interpreter, inside the container, after the module. The host agent starts it without a new
connection: one per stack, several at once (`--env a,b` on one machine).

**Agents execute, they never decide.** The local side expands the grid and builds the plan. It also
holds the run queue, writes the records from what comes back, prints, and fetches outputs. An
environment agent offers *operations*, small and without orchestration:

    collect( files, patterns )         -> entries and their declared parameters
    run( entry, params, out_dir )      -> output streamed, then { status, results, seconds }
    build( runner ), list( runner )    -> a pytest / Catch2 / cargo build or listing

These live in `agents/ops.py`, the only part of errand that runs in the environment's
interpreter. It needs `targets/` (importing entry files) and the standard library, never the
command line, the screen, the layers or the queue. The two phases of ADR 0002 become two series of
calls: `collect` and `build`, then `run`. Where nothing separates them, it is the same agent,
started once. **There is no errand started over there any more.**

**A process has a terminal when its client has one.** POSIX gets one from `pty.openpty()`.
Windows gets one from ConPTY (`CreatePseudoConsole`, Windows 10 1809+) through `ctypes`, which keeps
errand free of dependencies, with plain pipes as the fallback. Colours, ctrl-C, resizing,
`errand shell`, a debugger: all of them go through agents.

**One protocol at every hop.** Each layer already gives a byte stream: the stdio of `ssh`, of
`micromamba run python`, of `apptainer exec`, of `srun`. Frames are multiplexed over it as
`[ channel, type, length, data ]`. Channel 0 is control (spawn, signal, wait, files). The others
carry one process's stdin, stdout and stderr, or its pty. The stream is never a tty, so bytes cross
as they are. A host agent relays its environment agents' frames without reading them, and only
renumbers channels.

**Losing the connection loses nothing.** A laptop closes, a network drops: what runs over there must
not notice. So a host agent does not live at the end of the ssh pipe. It is a daemon over there,
listening on a unix socket in `~/.cache/errand/agents/<key>/`. ssh only starts a small `connect`
bridge between its stdio and that socket, and starts the daemon first if there is none. Every
process an agent starts writes its output and its exit code to files in that directory. The channel
only streams them live, and a client that comes back resumes reading from an offset. Here, a run
leaves a file (`.errand/live/<run>.json`: host, agent key, process id) saying where to find it
again. `errand status` reads it, and an `errand attach` follows it. A process may also be started
as one that should not outlive its client, which is what a probe is: it is killed when the client
goes. A daemon with no client and nothing running exits after its `keep_alive`.

**Ctrl-C stops the run.** Here, nothing swallows it: an entry that is interrupted is not an
entry that failed, and nothing runs after it. Over there, the session gets SIGINT, then SIGTERM two
seconds later, then SIGKILL three seconds after that, all of them sent to its whole process group.
So a Python program that catches KeyboardInterrupt and goes on is stopped anyway, and so is a
program that ignores SIGINT. The command exits with 130, and what was stopped is not waited for.

**An agent knows when it is stale.** Each agent carries a key: a hash of errand's sources, the
fingerprint of its stack (the one ADR 0004 decides rebuilds with), and the stamp of what was built.
Before each use, the hub compares the key with what is declared now. An agent that no longer
matches is stopped and started again, and `-v` says why.

**Each level goes quiet on its own.** `keep_alive =` is set on every layer that leads to an agent
(`Gateway`, `Scheduler`, `Interpreter`). It defaults to the `Env`'s value, then to `configure`'s.
An idle environment agent exits and frees its GPU memory or its container. A host agent exits once
it has no environment agent and is idle. A warm allocation is released when its node agents exit.
The hub goes last. `errand agents stop <name>` stops one agent and everything below it.

**Schedulers cut the chain, unless asked.** Under `--batch` nothing stays connected. The
preparation (`collect` and `build`, which size the allocation) is done before submitting. The job
runs `python <boot> worker plan.json`: the same environment agent, driven by a file instead of a
channel. It runs each case and writes each result as it goes. `status` and `watch` read those files
through the host agent, and the hub writes the local records as it fetches them. **Alive** mode is
explicit: the host agent on the login node holds an allocation (`salloc`) and starts one **node
agent** per node with `srun --ntasks-per-node=1`, relayed over srun's stdio. Environment agents
start on each node. MPI is still launched by `mpiexec` or `srun`, from node 0's agent, since that is
how ranks get wired together. The other node agents serve observation, node-local files and
distributed non-MPI entries.

**What is built is built where it is used.** A layer placed after a scheduler is built inside the
allocation, by a node agent. That is the allocation of preparation under `--batch`, the warm one in
alive mode. This covers a `/scratch` or a filesystem mounted only on compute nodes, or a module
available only there. A layer placed before it is built from the host agent, as today. The Python
bootstrap follows the same rule.

**The machine's queue is taken where the work runs.** The session that runs the cases takes and
releases each claim itself (file locks shared with everything on that machine, other hubs and other
users included), as the remote errand did. This was first meant to be the host agent's job. But a
claim held by a process tied to a client's connection would be released when the connection drops,
while the work goes on, and a session's own claims are inherited by what it starts, containers
included. Under a scheduler there is no claim: the scheduler does that job.

**Layers say what they are.** The behaviour that `isinstance` and `hasattr( …, "run" )` probe
today becomes explicit abstract base classes:

    Layer
    ├── Overlay          wraps the command's surroundings        Vars, Module, Nix, Guix
    ├── Launcher         starts the command, N times             Mpi
    ├── Interpreter      chooses `python`                         Venv, Micromamba, Uv
    │   └── Container    + an image, mounts                       Apptainer, Docker, Podman
    ├── Scheduler        submit, watch, cancel, size              Slurm, Oar, Pbs, Sge, Lsf
    └── Gateway          opens a channel to elsewhere             Ssh, Windows
    Artefact (mixin)     a built thing and its record             Venv, Micromamba, Uv, containers

An incomplete layer then fails when it is declared, not on its first run. The public API
(`errand.Venv( … )`, `errand.Ssh( … )`) does not change.

**Consequences.** Commands after the first start in milliseconds where they took seconds, and an
environment that stays up keeps what it has loaded. Rerunning a computation without re-importing
needs one more step (below). The remote errand and its second set of decisions disappear, and with
them the drift between what was planned here and what was resolved there. The price is a
long-lived process to get right: lifetimes, staleness, and errors that cross three hops and must
still say where they happened. `--batch` keeps a file-driven worker, which is the one place where
errand code still runs unattended over there.

**Order of work.** Each step keeps the suite green on 3.8 and 3.13, with real runs on lmo.

1. Reorganise what does not depend on this: `cli/`, `tui/`, `vm/`, `runner/`. *Done.*
2. Protocol, channel, hub, and the host agent over `Ssh`. `host.shell` and rsync go through it.
   *Done.*
3. Environment agents and a session in them (`agents/ops.py`), driven from here (`cli/drive.py`).
   The remote errand goes where no scheduler or VM is on the way. *Done.*
4. Schedulers and `--batch` through the same session. In the foreground, it is started through the
   layers (`srun …`) by the host agent, or its log is read for a watched job. `--batch` prepares
   here, then submits it. The old path (`ssh … python -m errand`) is gone. *Done.*
5. The Windows VM as a `Gateway`: an agent in the guest, started through the layer, sessions there.
   pty on POSIX, ConPTY on Windows. *Done.* The keeper stays as it is: the machine is held for as
   long as a command uses it, then for its `keep`. Having the hub hold it would keep 8 cores and
   16G busy for the hub's 15 minutes, against what `keep = "0"` asks for.
6. Slurm held warm (`keep_alive`): an `sbatch` whose batch step is a node agent, reached by
   `srun --overlap`, an environment agent inside it, MPI from node 0, and the layers after the
   scheduler built inside the allocation. *Done.* An agent's idleness is counted from what it runs
   and is asked, not from who is connected, and an agent stays while one below it is busy. The
   other nodes have no agent of their own yet: only MPI reaches them.
7. Imports kept warm: a zygote beside each environment agent imports, never runs anybody's code,
   and forks a session for each request. Every session is a copy of its own, so nothing leaks
   from one to the next. What it imports is learned from past sessions, never the project's own
   modules. It never preloads a module whose import starts threads, OpenBLAS's pool aside, which
   handles a fork itself. It never initialises CUDA, and it goes when a module it imported
   changes. numpy's and torch's generators are reseeded in each fork. Signals reach the fork, and
   a client killed outright takes its fork with it. On lmo, torch with a CUDA matmul: 1.5 s
   instead of 2.9 s. POSIX only. It is chosen, not imposed: the `Preload( *modules, learn = True )`
   layer turns it on for a stack, and without it a session is a Python started anew. *Done.*

**Not decided here.** The protocol's exact message set. Whether a hub may serve several users of one
machine (no, for now).
