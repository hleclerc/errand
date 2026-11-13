# Fast, and nothing lost: agents

A command used to pay for everything again each time: an ssh login, a shell that reads its rc file,
an `srun` in the queue, a container entered, a Python that imports torch. Now errand pays once. The
first command leaves small processes behind (**agents**), and the next commands go through them.

| | before | with agents |
|---|---|---|
| a run on a machine over ssh | 4–8 s | 0.9–1.8 s |
| a run on a cluster, allocation held warm | the queue's minutes | about 1 s |
| a session that imports torch (CUDA), with `Preload` | 2.9 s | 1.5 s |

There is nothing to declare: agents are the default on a terminal. They stop on their own when
nothing uses them, and a closed laptop does not take the work with it.

## What stays, and where

```text
  here                          the machine Ssh leads to             the end of the stack
  ────                          ────────────────────────             ────────────────────
  errand ── hub ── one ssh ──── host agent ── the layers, once ───── environment agent ── sessions
  errand ──┘                    (rsync, setup, probes)               (micromamba, container, …)
```

- **The hub** is one process here, per user. It keeps the streams to the agents open between
  commands, and several commands share them. The first command to want an agent pays for reaching
  it; the next ones do not.
- **A host agent** runs on each machine errand reaches. It started through one ssh, and everything
  goes through it: the rsyncs, which use it as their remote shell, the checks and builds of `setup`,
  the probes. Nothing logs in again.
- **An environment agent** runs past the layers, with the environment's own interpreter: inside
  the micromamba environment, the module, the container, the allocation. The layers are entered
  once, not once per command. It collects the entries and runs them.

errand itself needs nothing installed over there. Its sources travel, and it finds a Python 3.8 or
later to start on, or makes one for itself. → [Nothing to install over there](./layers/ssh#nothing-to-install-over-there)

## Warm imports: `Preload`

```python
errand.envs[ "gpu" ] = errand.Env( [ errand.Ssh( host = "gpu-box" ),
                                     errand.Micromamba( "torch" ),
                                     errand.Preload( "torch" ) ] )
```

With the [`Preload`](./layers/preload) layer at the end of a stack, a session does not start a new
Python. The environment agent keeps a process beside it that has already imported torch, and each
session is a fork of that process. The project's own modules are always read again. Without the
layer, every session is a Python started anew: you choose.

## Held warm, for a while

Each layer that costs something to start says how long it stays up once nobody uses it:

| what | stays up | declared by |
|---|---|---|
| the hub, a host agent, an environment agent | 15 minutes with nothing to do | `ERRAND_HUB_KEEP_ALIVE` for the hub (seconds) |
| a Slurm allocation | `keep_alive`, if given; otherwise one job per command | [`Slurm( keep_alive = "30m" )`](./layers/slurm#held-warm-keep-alive) |
| a Windows virtual machine | 5 minutes | [`Windows( keep = "5m" )`](./layers/windows#with-a-python-errand-runs-in-it) |

"Nothing to do" means no request and nothing running. A connection held open does not count, which
is what lets the chain come down from the far end. When the environment agent has had nothing to do
for its time, it goes. The node agent above it then has nothing to do either, so the Slurm job ends
and the allocation is released. The same happens with a virtual machine, and finally with the hub.

## Giving way

Something only kept warm is a cost to others while it waits. A virtual machine nobody uses holds
cores and memory, and a process that imported torch holds memory too. They hold their claim in the
[machine's queue](./machine) as one that **gives way**. A command that needs the room asks for it,
and gets it without waiting for the end of a `keep`: the machine stops, the process goes. While it
waits, the command says what it waits for ("…, kept warm, to make room"), and `errand queue` marks
those claims as kept warm.

A Slurm allocation held warm is never stretched to fit. A command runs in it only if it fits: its
ranks within the allocation's tasks, its cores and cards per task within those declared, its
`--time` within what the job has left. Otherwise the command gets a job of its own, sized for it.
If nothing runs in the warm allocation, it is given back first, since it may hold the very nodes.
No `srun` ever asks for more than was allocated. On a shared cluster, a short `keep_alive` is the
polite choice.

## Close the laptop

What the agents start writes its output to disk where it runs, so a closed laptop or a dropped
network loses nothing. The work goes on. `errand attach` follows it again: it shows the output from
the start, waits for the end, and brings the results back.

```bash
errand run --env gpu 'bench/**::*'      # the laptop closes halfway
errand attach                            # later: the rest, the report, the results here
```

## Ctrl-C means stop

Ctrl-C reaches the work wherever it runs, through every layer: over ssh, in a container, in an
allocation, in a Windows guest. The work gets an interrupt first, as at a terminal. If it is still
there after 2 seconds it is told to terminate, and after 5 seconds it is killed. errand then exits
with code 130. A Python that catches `KeyboardInterrupt` and goes on does not keep errand waiting.

## A real terminal

`errand shell` gets a real terminal over there: a pty on Linux and macOS, a pseudo-console on
Windows. Colours, line editing, full-screen programs, Ctrl-C as a key, and the window's size,
followed as it changes.

```bash
errand shell --env cluster      # a shell in the allocation, the container, the environment
errand shell --env win          # cmd.exe in the Windows guest, as at its console
```

## Leaving nothing behind

Agents and the hub stop when they have had nothing to do for their time, and take their sockets
with them. A hub started from sources that have since changed also takes its directory with it.
Errand's directories are named after its sources, so an edit to errand means new ones. When an agent
or a hub starts, it removes the directories beside its own that nobody serves any more: untouched
for an hour, and with a lock that no process holds. Everything lives under `~/.cache/errand`, here
and over there.

## What is up, and stopping it

```bash
errand agents              # the hub, and each agent it keeps a stream to
errand agents stop gpu     # those whose name holds "gpu" go now
errand agents stop         # all of them, and the hub
```

```text
  hub  pid 79636  up 3 s   ~/.cache/errand/hub-c81a3d1d455a
    lmo                              last used 0 s ago, 1 open; kept 15 min unused
    lmo:env-c81a3d1d455a-32772dfcfc  last used 0 s ago; kept 15 min unused
```

Stopping goes from the far end: an environment before the machine or the allocation it runs in. An
allocation held warm goes with its agent, and the job ends. An agent with something running is left
alone, and says so; `--force` stops it anyway.

`errand status` starts with the commands left running when their connection was lost. For each, the
agent says whether the work is still running or has finished and waits to be brought back with
`errand attach`.

## When you want it otherwise

| `ERRAND_AGENT` | |
|---|---|
| `hub` | through the hub. The default on a terminal |
| `direct` | a connection owned by the command, closed with it. The default without a terminal (cron, CI) |
| `off` | no agent: one ssh per remote command, as before |

`ERRAND_WARM=0` starts every session anew, even with a `Preload`. And `-v` shows what goes where:
every command errand starts, including those it hands to an agent.
→ [When something breaks](./upkeep#when-something-breaks)

The design, and why the local side decides while the agents only execute:
[ADR 0005](https://github.com/hleclerc/errand/blob/main/docs/adr/0005-the-local-side-orchestrates-agents-execute.md).
