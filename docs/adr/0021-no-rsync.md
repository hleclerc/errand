---
status: accepted
date: 2026-11-19
---

# errand does not use rsync

ADR 0006 moved every copy onto the agents: a sync by manifest, on a channel of the protocol. It kept
rsync as an option (`Ssh( transfer = "rsync" )`, `ERRAND_TRANSFER=rsync`) for a large file that
changes a little, whose delta rsync sends and a sync does not. Since step 7 (2026-11-16) the sync
has been the default, and no environment file asks for rsync.

The option kept a second copy of every rule. The push had `RSYNC_EXCLUDES`, `own_paths()` as
`--exclude`, the runs made over there found by a `find` and protected by `P` filters
(`runs_over_there`, `protect_runs`), the cache zones sent with `--ignore-existing`. The pull had the
unfinished runs listed by another `find` and excluded (`unfinished_excludes`). errand started on
Windows downloaded MSYS2's rsync and ssh (pinned, eleven packages, into `msys2-rsync/`), because
Windows' own `ssh.exe` cannot carry MSYS2's rsync. And the rules drift: ADR 0019's `CACHEDIR.TAG`
directories, each side's own, are honoured by the sync and not by rsync, which has no such filter.

## Decision

**rsync is gone from errand.** Every copy is a sync through the agent over there:

| what rsync did | what does it now |
|---|---|
| the push before a run, of `errand setup`, of an image built elsewhere (`build_on`), of `also` checkouts | `gateways.push` → `syncop.push`, with `gateways.selection()` (zones, `kept()` paths, errand's outputs) |
| the pulls of results and `back` zones, finished runs only | `gateways.fetch` → `syncop.pull( finished_only )` |
| the pulls of cache zones, nothing replaced | `syncop.pull( keep = True )` |
| one file brought back at once (`errand.view`) | `gateways.fetch_file` → `syncop.pull` |
| a preparation's build carried between two machines (ADR 0011) | `gateways.put` → `syncop.push` |
| errand started on Windows, copying to a POSIX host | the same sync; Windows' `ssh.exe` only starts the agent |
| errand's own sources onto a new machine (`bootstrap.ship`) | already a tar on the stdin of one ssh line (ADR 0006): needs `sh` and `tar` there, nothing else |
| the Windows guest | already through the guest's agent (ADR 0006, recipe 3) |

`Ssh` has no `transfer` field; `ERRAND_TRANSFER` is not read. `vm/transfer.py` (MSYS2's packages)
is removed, and with it `local_rsync`, `local_ssh` and the zstd unpacking they needed. A record of a
detached run that still carries `"transfer"` in its `ssh` is read as before.

`python -m errand.agents rsh` stays: it is a remote shell through the agent, which the environment
agents, a guest's agent and the nodes of an allocation are reached by. Only rsync's `-e` string
(`upstream.rsh`) goes.

## Consequences

- One set of rules for what crosses, in `sync.Selection` and `syncop`: a rule added there holds for
  every copy (ADR 0019's tags included).
- A large file that changes a little crosses whole. Such a file belongs in a zone (`back`, `cache`),
  or outside the project. Not measured on jz.
- Nothing errand needs over there beyond ssh, `sh`, `tar` and a Python it can find or make.
- errand started on Windows downloads nothing to copy with; a key in Windows' ssh-agent works for
  copies too, since only `ssh.exe` is used.
- An `msys2-rsync/` left in errand's local cache by an older errand is not removed: delete it by hand.
