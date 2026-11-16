# Agents and keeping warm

Without errand, every command pays for its whole path again: an ssh login, a shell reading its rc
file, an allocation, a container entered, a Python importing torch. errand pays once. The first
command leaves small processes behind, **agents**, and the next commands go through them.

| | each time, by hand | through agents |
|---|---|---|
| a run on a machine over ssh | 4–8 s | 0.9–1.8 s |
| a session that imports torch (CUDA), with `Preload` | 2.9 s | 1.5 s |

Nothing to declare: agents are how errand runs anything. They stop on their own when nobody uses
them.

## Where they run

```text
  here                          the machine Ssh leads to             the end of the stack
  ────                          ────────────────────────             ────────────────────
  errand ── hub ── one ssh ──── host agent ── the layers, once ───── environment agent ── sessions
  errand ──┘                    (push, pull, setup, probes)               (micromamba, container, …)
```

- **The hub**: one process here, per user. It keeps the connections to the agents open between
  commands, and several commands share them.
- **A host agent** on each machine errand reaches. It is started through one ssh; after that the
  pushes and pulls, the builds of `setup` and the probes all go through it. Nothing logs in again.
- **An environment agent** past the layers, with the environment's own interpreter: inside the
  micromamba env, the module, the container, the allocation. The layers are entered once, not once
  per command.

Nothing is installed over there. errand's sources travel, and it finds a Python 3.8 or later to
start on, or makes one for itself. → [Nothing to install over there](./layers/ssh#nothing-to-install-over-there)

Each agent also keeps track of everything it starts, on its own machine. That is what
[`errand status`](./status) reads, and what lets the next agent clean up after one that died.

## Kept warm, for a while

| what | stays up when unused | set by |
|---|---|---|
| the hub, a host agent, an environment agent | 15 minutes | `ERRAND_HUB_KEEP_ALIVE` for the hub (seconds) |
| a Slurm allocation | 1 minute by default; `0`: one job per command | [`Slurm( keep_alive = "30m" )`](./layers/slurm) |
| a Windows virtual machine | 5 minutes | [`Windows( keep = "5m" )`](./layers/windows) |

An allocation kept warm means the next command that fits in it starts at once, without a new
`sbatch` and without entering the layers again. "Unused" means no request and nothing running; an
open connection does not count. So the chain comes down from the far end: the environment agent
goes, then the node agent, the Slurm job ends, and finally the hub.

## Warm imports: `Preload`

```python
errand.envs[ "gpu" ] = errand.Env( [ errand.Ssh( host = "gpu-box" ),
                                     errand.Micromamba( "torch" ),
                                     errand.Preload( "torch" ) ] )
```

With [`Preload`](./layers/preload) at the end of a stack, a session is a fork of a process that has
already imported torch. Your project's own modules are always read again. Without the layer, every
session is a fresh Python: your choice.

## Giving way

Something kept warm costs others while it waits: an idle VM holds cores and memory, a process with
torch imported holds memory. Their claim in the [machine's queue](./machine) **gives way**: a command
that needs the room gets it at once, and the VM or the process goes. `errand queue` marks those
claims as kept warm.

A warm Slurm allocation is never stretched. A command runs in it only if it fits: ranks, cores and
cards per task, and `--time` within what the job has left. Otherwise it gets a job of its own. On a
shared cluster, a short `keep_alive` is the polite choice.

## Ctrl-C stops the work

Ctrl-C reaches the work wherever it runs: over ssh, in a container, in an allocation, in a Windows
guest. The work gets an interrupt, then a terminate after 2 s, then a kill after 5 s, with everything
in its process group. The agent over there does this, so it happens even if your connection is
already gone. errand exits with code 130.

## A real terminal

`errand shell` gets a real terminal over there: a pty on Linux and macOS, a pseudo-console on
Windows. Colours, line editing, full-screen programs, Ctrl-C as a key, window resizing.

```bash
errand shell --env cluster      # a shell in the allocation, the container, the environment
errand shell --env win          # cmd.exe in the Windows guest
```

## Listing and stopping agents

```bash
errand agents              # the hub, and each agent it keeps a connection to
errand agents stop gpu     # those whose name contains "gpu"
errand agents stop         # all of them, and the hub
```

```text
  hub  pid 79636  up 3 s   ~/.cache/errand/hub-c81a3d1d455a
    lmo                              last used 0 s ago, 1 open; kept 15 min unused
    lmo:env-c81a3d1d455a-32772dfcfc  last used 0 s ago; kept 15 min unused
```

Stopping goes from the far end: an environment before the machine or the allocation it runs in. An
agent with something running is left alone and says so; `--force` stops it, and what it runs.

## What stays on disk

Under `~/.cache/errand` (or `$ERRAND_CACHE_DIR`), errand keeps only what is live: sockets, locks,
pids, the records of running processes. Agents remove the directories nobody serves any more. What
piles up belongs to the project, in its `errand-outputs/`:

| what | where | until |
|---|---|---|
| a command's output, kept for `errand attach` | `errand-outputs/state/procs/` | it is brought back |
| run records | `errand-outputs/runs/` | you remove them |
| Windows images | `errand-outputs/builds/windows/` | a newer one is ready |

→ [Where errand writes](./storage)

## Modes

| `ERRAND_AGENT` | |
|---|---|
| `hub` | through the hub. The default on a terminal |
| `direct` | a connection that belongs to the command and closes with it. The default without a terminal (cron, CI) |

There is no mode without agents: every machine errand runs on has one, so what runs there is
tracked, listed and stopped the same way everywhere.

`ERRAND_WARM=0` starts every session anew, even with a `Preload`. `-v` prints every command errand
starts, including those it hands to an agent. → [When something breaks](./upkeep#when-something-breaks)

The design: [ADR 0005](https://github.com/hleclerc/errand/blob/main/docs/adr/0005-the-local-side-orchestrates-agents-execute.md),
[ADR 0008](https://github.com/hleclerc/errand/blob/main/docs/adr/0008-nothing-runs-unowned.md),
[ADR 0009](https://github.com/hleclerc/errand/blob/main/docs/adr/0009-arrivals.md).
