---
status: proposed
date: 2026-11-19
---

# `errand serve`: a service the agent keeps, under the queue, until nobody uses it

Two needs came up the same week.

- **Ollama on lmo.** An application (boucles) asks an LLM through an ssh tunnel. The card (RTX 2080 Ti,
  11 GB) is shared with computations. A script beside errand, `~/.local/bin/ollama-errand` on lmo, does
  what errand does not: `garde` takes 10 GB of the card with `python -m errand.queue hold`, starts
  `ollama serve` with the cards granted, asks `/api/ps` every 2 s and says `busy` (a model is loaded)
  or `warm` (the claim gives way), stops Ollama and gives the card back on `evict` while warm, or after
  10 minutes with neither a model nor a connection. `relais`, the command forced by the tunnel's key in
  `authorized_keys`, starts the keeper under a lock if it is not running, waits for Ollama, and relays
  its stdin and stdout to the port.
- **sviz** (ADR 0017): the viewer of `.sviz` directories is a small HTTP server that should exist while
  a page uses it, one per user, and be listed and stopped like the rest of what errand starts.

Both are a **service**: a long-lived process, started on demand, never twice, stopped when nobody uses
it, optionally holding a share of the machine that it gives back when a computation needs it while it
rests. Today `hold` is not a documented command, no command manages a server, and the script redoes,
outside errand, the lock, the ownership and the cleanup that agents exist for (ADR 0008).

Settled in a grill on 2026-11-19 (`grill/serve/`).

## What errand has already (checked in the code, 2026-11-19)

- **Claims** (`queue.py`): a file under `claims/`, kept by a thread that touches it every 5 s, stale
  after 30 s. `mark( path, preemptible )`, `evict()`, `evicted()`, `Granted.preemptible()`. `_acquire`
  asks the preemptible claims to go (`evict/<claim>`) when a request would fit without them; their
  holder releases. Marking busy clears a pending eviction.
- **`hold`**: `python -m errand.queue hold '{"needs": …, "label": …}'` prints `granted d0,d1`, reads
  `warm` / `busy` on stdin, prints `evict` once per warm period, releases when stdin closes. The Windows
  VM uses it through a remote agent (`vm/claim.py`, `vm/keeping.py`).
- **Order**: only exclusive and growing requests write a `waiting/` file. A plain waiter is recorded
  nowhere: it polls every 0.25 s, and a later request that fits passes it.
- **Agents**: a process they start has a marker (`proc/<id>/meta.json`, its group), is stopped by INT,
  TERM after 2 s, KILL after 5 s on its group, and runs its `cancel` (ADR 0008's `on_stop`). A
  `keep=True` process outlives the client that started it (the VM keeper). A live process keeps its
  agent alive.
- **Transport**: the agents' frames already carry raw bytes (`IN`, `OUT`; rsync goes through them).
  There is no socket operation and no port forwarding (`errand web` tells users to `ssh -L`).

## Decision

### Declaring a service

```python
# ~/.config/errand/services.py  ( $XDG_CONFIG_HOME ), or any project file errand reads
import errand

errand.services[ "ollama" ] = errand.Service(
    [ "/usr/local/bin/ollama", "serve" ],
    env   = { "OLLAMA_HOST": "127.0.0.1:{port}", "OLLAMA_KV_CACHE_TYPE": "q8_0" },
    gpus  = 1, gpu_ram = "10G", label = "ollama (boucles)",
    busy  = errand.http_json( "/api/ps", lambda r: bool( r[ "models" ] ) ),
    idle  = "10m",
    port  = 11435,               # optional: the address announced on 127.0.0.1
    grace = "10s" )
```

and the same, ad hoc, on the command line:

    errand serve [--gpus N --gpu-ram R --ram R --cpus N -n LABEL] [--idle 10m] [--busy-if CMD]
                 [--port P] [--name NAME] [--ensure] [-f] -- <command of the server>

- A service is **one per (user, machine, name)**. The name: declared, `--name`, else the label, else
  the command's first word.
- The user's file is new: errand reads envs in the project and its parents only, and a service belongs
  to a machine and a user, not a project. The relay of boucles is started by ssh from `~`, outside any
  project. Project files may declare services too.
- `{port}` in the arguments and in `env` is the **internal** port, errand's to choose (below); `$PORT`
  holds it as well. The cards granted are given as `errand run` gives them (`CUDA_VISIBLE_DEVICES`,
  `HIP_VISIBLE_DEVICES`, `ROCR_VISIBLE_DEVICES`, `ERRAND_CLAIM`).

### A keeper per service, owned by the host agent

`errand serve NAME` asks the host agent of the machine (ADR 0005) to ensure the service. Under the
agent's lock: if it runs, its address is answered; otherwise the agent starts its **keeper**,
`python -m errand.serve keep NAME`, a `keep=True` process (stdlib only), and two requests at once start
one. `errand serve` returns once the service answers, and prints its address; `-f` stays in the
foreground, and Ctrl-C stops the service. `--ensure` is the same without a message when it already runs.

The keeper holds everything of one service: the claim (its 5 s thread), the announced port and the
relay to the internal one, the probe, the server process (its child, in its group), the rules to stop.
The agent only starts it, lists it and stops it. A keeper that dies: the agent kills the server's group
(ADR 0008), and the claim goes stale in 30 s.

### Ports, and how errand sees use

- **Internal port**: free, chosen by errand, given to the command (`{port}`, `$PORT`). The server listens
  there, on 127.0.0.1.
- **Ready**: the internal port accepts a connection (or `ready = callable`, for a server that accepts
  before it is ready).
- **Announced port**, optional: `port = P`, or, without it, chosen by errand and **kept for the name**
  (`~/.cache/errand/serve/<name>.json`), so that an address stays the same from one start to the next.
  The keeper listens there, on 127.0.0.1, and relays each connection to the internal port. Without an
  announced port, a service is reached only by `connect` and `forward`, through the user's own agent.
- Every connection passes the keeper, so **errand counts the open connections** itself, on every
  system, with no `/proc/net` nor `lsof`.

**Use is open connections, never throughput.** A server that thinks for an hour before answering sends
nothing, and must not look abandoned. So:

- while at least one connection is open, the service is used, silent or not;
- while the probe says busy, it is used, with no connection (Ollama with a model loaded);
- the `idle` clock starts only when there is **no connection and no busy**, and starts again from zero
  at the next connection.

A client that keeps a connection open for nothing (an HTTP keep-alive) delays the stop: the risk is
taken on that side, keeping too long, never killing in the middle of a computation.

### The probe: busy or not

It only says whether the claim is firm (`busy`) or gives way (`warm`); use by connections exists
without it. Declared as a function (`busy = callable( port ) -> bool`, with helpers such as
`errand.http_json( path, predicate )`), or `--busy-if CMD` on the command line (exit code 0 = busy,
`{port}` replaced). Asked every 2 s, with a 5 s timeout. **A probe that fails or does not answer counts
as busy**: a saturated server that no longer answers `/api/ps` is precisely in the middle of a
computation. A server that has crashed is seen by its process ending, not by the probe. Without a
probe, a service with a claim is warm as soon as it has no connection; without a claim, the probe is
useless.

### The queue: waiting, in order

- **Every waiting request is recorded** (`waiting/`), not only the exclusive and growing ones, and the
  oldest goes first: FIFO for all, `errand run` included. A small job that would fit beside a request
  waiting for the whole card waits behind it (no backfill for now). This changes the queue for
  everyone; it is the rule one expects, and what "not overtaken" needs.
- **While the service waits for its share**, the announced port is already held: a connection that
  arrives is accepted and **waits**, then is relayed when the server answers (the relay of the script,
  for every client). The keeper **gives up the wait** when nobody waits any more for `idle`: no
  connection open, no `errand serve` waiting for it (the script's `ATTENTE_MAX`, under the same rule).
- `errand queue` shows the claim with its label, and `( kept warm: gives way )` while warm, as it does
  for the VM.

### Stopping

The keeper stops the server with the agents' sequence (INT, TERM, KILL on its group), with `grace`
before KILL (10 s by default: a server may have a card to empty), then releases the claim. It stops:

- on an eviction **while warm** (marking busy clears an eviction, as today);
- after `idle` without connection nor busy;
- on Ctrl-C in the foreground (`-f`), or `errand serve stop NAME`;
- when the server ends by itself: the keeper ends too, with no restart; the next connection or
  `errand serve` starts it again.

### `connect` and `forward`

- **`errand serve connect NAME`**, on the service's machine: ensures the service, waits for it, relays
  stdin and stdout to it. What `command=` in `authorized_keys` runs (the relay of boucles). Its
  connection counts like any other.
- **`errand serve forward [--env E] NAME [--port N]`**, here: a local port whose every connection goes
  through the agents, one channel per TCP connection, to the service over there, ensured if needed. A
  **native operation of the agent** ("open a connection to 127.0.0.1:P and relay it") rather than a
  bridge process per connection. It stays inside the connection errand already holds: no `ssh -L`.
  It comes after the rest; `sviz open --there` (ADR 0017) is its first user.

### `errand hold`, documented

The protocol of `python -m errand.queue hold` becomes a command: `errand hold [needs] [-n LABEL]`
prints `granted <cards>`, reads `warm` / `busy`, prints `evict`, releases when its stdin closes.
Unchanged for the Windows VM, which keeps calling it as it does.

### Seen, and what is not

- `errand status` lists the services: name, state (`waits for gpu (2 connections waiting)`, `starting`,
  `busy`, `warm`, `idle for 3 min`), connections, address; and the queue's claims, which it does not
  show today.
- The queue is per user and per machine, and stays so. The guide says it: a server started under
  another account (a systemd service) is not seen, and its share of the card is not counted.
- A port on 127.0.0.1 is open to every account of the machine. The internal port of a server always is
  (the server opens it); the announced port is optional, and without it errand adds no door. With one,
  access control is the service's (sviz puts a token in its URLs). The guide says it.

## Considered options

- **`errand serve` as a foreground keeper**, like `ollama serve`, to be detached by the user (nohup,
  systemd, the relay). What the script does today; it leaves "who starts the keeper, under which lock"
  to each user. The host agent is already one per user and machine, and owns what it starts.
- **Throughput as activity.** Kills a server that is slow to answer. Rejected.
- **Counting connections from the system** (`/proc/net/tcp`, `lsof`, `netstat`): per system, and blind
  on Windows. Holding the port costs one hop in Python, negligible for tokens or frames of 80 kB.
- **Only connections through `connect` / `forward`**: misses a local browser on sviz's port.
- **A probe that fails counts as idle**: stops a saturated server. Rejected.
- **FIFO for services only**: two rules for one queue.
- **Services declared only in project files**: the relay runs outside any project.
- **Restart a server that dies**: hides crashes; the next connection starts it again anyway.

## Consequences

- `ollama-errand garde` becomes the `ollama` service above, and `ollama-errand relais` becomes
  `errand serve connect ollama` in `authorized_keys`. The card is listed, given way, and given back
  as by any errand claim.
- sviz is started, listed and stopped by errand where errand is installed, and starts itself elsewhere.
- The queue becomes FIFO for every request. A job that used to slip beside a big waiter now waits.
- errand reads a user-level file for the first time.
- `forward` gives a general way to reach a server on another machine through errand: the ssh tunnel of
  boucles could use it too, later.

## Steps

1. **The queue**: every waiter recorded, FIFO; tests for order, and for the VM's `hold` unchanged.
2. **Declarations**: `errand.Service`, `errand.services`, `~/.config/errand/services.py`, the command
   line form; `errand.http_json`.
3. **The keeper** (`errand/serve.py`): claim, internal and announced ports, relay and connection count,
   probe, ready, stop rules, waiting connections; the agent's `serve` operation (ensure under its
   lock, `keep=True`); `errand serve`, `-f`, `--ensure`, `stop`.
4. **`connect`**, then **`errand hold`** documented; `errand status` and `errand queue` show services
   and claims. Tried for real: Ollama on lmo through the tunnel of boucles, with a computation that asks
   for the card while it rests.
5. **sviz** through `errand serve --ensure` (ADR 0017, step 6).
6. **`forward`**: the agent's socket operation, one channel per connection; then `sviz open --there`.
7. The guide (`docs/guide/serve.md`, beside `machine.md` and `agents.md`), the API reference.
