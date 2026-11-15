# Audit, 2026-11-14: what can run unowned, and what `status` sees

Two read-only audits run after the incident of the orphaned QEMU on lmo. ADR 0008 builds on them. Line
numbers are as of that date.

## Process kinds

| Kind | Parent / detachment | Kill path | Idle path | Guarantee |
|---|---|---|---|---|
| Hub (Mac) | double fork + setsid (`daemon.py:30`) | `agents stop`; SIGKILL → upstreams get stdin EOF | 900 s with no client (`hub.py:241`) | solid |
| Upstream ssh / rsh (Mac) | hub, `start_new_session` (`upstream.py:116`) | `close()`; hub death → EOF | `keep` unused | solid |
| `connect` bridge | stdio of ssh / srun / container | dies with its stdio | — | solid |
| Host / env agent (detached) | double fork + setsid | `agents stop` refused if procs run; `--force` = `os._exit`, procs left | `keep_alive`, procs = busy | idle solid; children best effort |
| Attached agent (apptainer) | fork of the bridge (`daemon.py:109`) | bridge gone → one SIGTERM, `_exit` | same | children SIGTERM only |
| Agent Proc | agent, own session (`spawn.py:104`) | SIGNAL → killpg; client gone + `keep=False` → TERM, KILL 5 s (`procs.py:114`) | none | killpg solid; escalation in client timers |
| Zygote | double fork + setsid (`warm.py:87`) | not reached by agent stop | 900 s fixed; eviction | invisible |
| Zygote fork | zygote, setsid | client signals; client SIGKILL → EOF → killpg (`warm.py:366`) | — | solid |
| `queue hold` | host agent, `keep=False` | stdin EOF → release | heartbeat 30 s | solid |
| Warm Slurm job | sbatch | `agents stop`, scancel, job end | `max(30, keep/4)`, `--time` | solid (cgroup) |
| Foreground srun / salloc | host agent, `keep=True` | INT → TERM → KILL to `sh` group | `--time` | best effort |
| Watched Slurm job | sbatch | scancel on Ctrl-C while watcher alive | `--time` | best effort |
| VM keeper (Mac) | caller, `start_new_session` (`caller.py:71`) | SIGTERM handler → finally; SIGKILL → nothing | `keep`, eviction | best effort |
| QEMU (Linux) | `-daemonize`, ppid 1 (`machine.py:81`) | only the keeper's `stop_there` over the link | only the keeper | none |
| Windows guest / box procs | DETACHED + BREAKAWAY | CTRL_BREAK; `taskkill /T /F` | agent `keep` | no Job Object |
| `--batch` local / ssh nohup | setsid / nohup | none (intended) | — | record + `kill -0` |

What sends SIGTERM to a keeper inside errand: only `errand vm stop` / `python -m errand.vm stop`.

## Kill and keep-alive gaps, ranked

1. QEMU belongs to nobody on its host; claim released with the keeper's stream; `Machine.sweep`
   forgets `qemu.pid` after a day; a network blip in `gone()` stops the VM on purpose.
2. An agent's death (`--force`, SIGKILL, OOM) orphans its procs; the next sweep deletes their
   markers (`agent.py:97-105`, `procs.py:174-186`).
3. Only the group leader is waited for; INT/TERM/KILL timers are daemon threads in the client,
   which exits first (`procs.py:79`, `client.py:134-138`).
4. Ctrl-C on a dead stream: `client.stop` swallows `OSError`, live record unlinked anyway
   (`drive.py:192-194`).
5. No ssh keepalive, no timeout on `agents.shell` (`gateways.py:171`, `client.py:157`): half-open
   TCP blocks the keeper's `alive_there`, so `keep` is never enforced.
6. Watched Slurm: `Lost` kills the watcher thread, no exit mark, cancel event unread
   (`schedulers.py:216-224`, `sessions.py:150`).
7. Zygote invisible, keep fixed at 900 s (`warm.py:116`).
8. Attached agents send SIGTERM only (`agent.py:168`).
9. Foreground salloc/srun: a SIGKILLed salloc keeps the allocation until `InactiveLimit` / `--time`.
10. Windows: no Job Objects, `taskkill /T` misses grandchildren whose parent exited.
11. Minor: `errand forget` on a running batch does not kill it; ssh `--batch` has no cancel;
    `ERRAND_AGENT=off` + Ctrl-C leaves remote work; direct-mode agents not listed.

## What `status`, `agents`, `queue` see

| thing | status | agents | queue |
|---|---|---|---|
| local run, no layers | no | no | its claim |
| local `--batch` | yes | – | – |
| run through an agent, foreground | yes (`state/live`) | its stream if the hub lives | no |
| prepare phase | no | stream | no |
| Ssh / Slurm `--batch` | yes | – | – |
| Slurm allocation held warm | no | stream while the hub lives | no |
| Windows guest run | no (`_remember` never called, `drive.py:203-240`) | stream while the hub lives | – |
| VM keeper + QEMU | no | no | only where QEMU runs |
| orphaned QEMU | no | no | no |
| `queue hold` on lmo | no | no | only `errand queue` on lmo |
| zygote | no | no | its machine only |
| agent with no live hub | no | no | – |

`status` is per project (`errand-outputs/state/`), `agents` and `queue` per user and this machine.
`status` has a side effect: `processes()` → `agents.open` starts the environment agent to ask it.

Side bug: `result_path_for` (`batch.py:226-246`) ignores the submission's stamp, so a running
submission shows the result of an earlier run with the same parameters (guitar_2000, a155 vs 53d7).
