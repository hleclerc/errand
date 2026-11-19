---
status: proposed
date: 2026-11-19
---

# Caches are looked after per file system, by the first machine that reaches them

ADR 0020 lets errand remove what a library's cache no longer needs, by rules, with no age and no size budget. It left
three things out: seeing the caches (how many entries, how big, what is dead, on which machine), removing by hand what
the rules keep (what has not served for weeks, what is dead but was used today, the same entry on every machine), and
caches errand cannot judge from where it stands: `deps` are absolute paths as the run saw them, and a run in a container
sees the image's `/usr/include`, not the host's.

A design grill settled the points below (`grill/cache-views/` of 2026-11-19).

## Decision

**A file system, not an environment.** A cache lives on a file system: this machine's, another machine's, a VM's own
disk. An environment is only a way in: a container shares its host's file system, and a VM taken out of the
configuration still holds its caches as long as its host knows it. So caches are found and looked after by the
machine that holds them, not through `--env`.

**Each machine keeps a registry of its caches.** A run that hands `$ERRAND_CACHES` to its program writes it down,
as it sees it, in `~/.cache/errand/caches/<hash>.json` (`{ path, id, views, project, seen }`), as it writes its leaf in
`seen/`. A registry entry whose directory is gone is dropped when read. The registry is what lets the machine's agent
know which caches it holds, which ADR 0020 could not: the agent did not know which projects it held caches for.

**A directory reached by several names is one.** The first run to use a `$ERRAND_CACHES` writes
`errand-caches.id` in it once: `{ id, host, made }`, a random id and the machine that made it. Two registered paths
with the same id are the same directory: a host path and its bind in a container, or a home shared over NFS by two
machines (`lmo = n22`). It is shown once and changed once. The machine that holds it is the one that made it: the first
machine that reached it, unless another is chosen by hand (`errand caches hold MACHINE [DIR...]`, `h` on a place in
the caches tab), which rewrites the holder in `errand-caches.id`: on a cluster, the login node whose agent errand
reaches, rather than the compute node whose run made the directory.

**A view says where `deps` were seen.** errand gives each run `$ERRAND_CACHES_VIEW`: empty on a machine as it is,
`apptainer:<image>` or `docker:<image>` in a container (from the environment's layers). A library copies it into each
`create` line as `view` (optional in `errand-cache/1`: absent is the bare machine). A purge judges the `deps` of the
entries of its own view only, and marks an entry it finds dead with `dead` (when it found it so), which a later
`create` of the entry clears. A dead entry used within a day stays, marked. Nobody else hashes anything: a screen
reads the marks.

**Journals are read, never taken.** ADR 0020's compactor took a journal by renaming it, reading it and removing it;
a writer that had opened it just before wrote its line into a file already read. On cinaps' NFS, with writers and
compactors on node14 and the login node at once, 9 lines of 900 were lost that way. A compactor now reads each journal
from where the last compaction stopped (`journals`: name -> inode and offset, in the manifest), whole lines only, and
removes a journal once it is read to its end and untouched for a day. A `create` older than the one merged is skipped.
The same run then lost none of 900, over about 4,900 compactions on the two hosts. loom's own compactor does the same.

**Who purges.** The host agent of a machine (`agents/host-…`), when it starts and then once a day, purges the
registered caches it holds, in the bare view. A run in a container purges its own view's entries, at most once a day
per cache and view (`purged_views`). A bare run purges only when no host agent runs on its machine, so that a machine
errand only ever runs on by hand is still tidied.

**Two agent ops** (`look`, served by every agent, asked by the TUI and the page through the agent they already ask):

- `caches { days, entries: [ names ], purge: { dry_run, unused_days } }`: each registered directory, compacted when
  its lock is free, with per cache the entries, their size, how many are dead and how many have not served for `days`
  (default 30), and the entries of the caches named; the VM guests of the machine, asked over their ssh as `table`
  asks them. With `purge`, ADR 0020's rules first.
- `caches_remove { id, cache, keys | rule: "dead" | "unused", days, guest }`: under the compactor's lock. Removing a
  shared entry takes the entries that need it; after any removal by hand, shared entries nothing needs go at once,
  without the day's wait. An entry used a moment ago goes all the same: a library tolerates an entry that disappears.

**The command.** `errand caches [MACHINE...] [--dry-run] [--unused DAYS]`: this machine by default, or machines of
the ledger by name; ADR 0020's rules, and with `--unused`, also the non-shared entries not used for DAYS days (and the
shared entries left needed by nobody). No "everywhere" on the command line: removing on every machine is done on a
screen, where what goes is seen first. `errand status` gives each machine's caches: entries, size, dead.

**The screens.** A third tab, `caches` (`3` in `errand tui`, the same tab in `errand web`): per cache name, a row per
machine (entries, size, dead, unused for N days); unfolded, the entries of that cache merged across machines, each
with its size, last use and where it is: by default only those dead or unused for N days somewhere, `v` for all.
`n` sets N (30 by default). On a machine's row: `i` removes its dead (invalid) entries, `u` those unused for N days;
on the cache's own row, the same on every machine; on an entry: `d` removes it where it is dead or unused, `D`
everywhere it is. Each asks first, saying how many entries, how
many bytes, on which machines.

## Considered options

- **`errand caches --env X`, run in the environment.** The view would be right, but a cache is not an environment's:
  a VM taken out of the configuration would lose its caches from sight, and two environments on one host would show
  one directory twice.
- **One cache directory per view (`caches@<env>/`).** Rejected: where a library puts its binaries for a given
  toolchain is the library's responsibility, and errand keeps one `$ERRAND_CACHES` per machine and project.
- **The host agent judges every entry.** Wrong for a container's entries, whose `deps` are the image's files.
- **A cross table (a column per machine) at the first level.** Dense, but unreadable in a terminal; the merged
  entries show the same thing one level down.
- **Refuse to remove a shared entry that others need.** Safer-looking, but the entries that need it would be rebuilt
  anyway once it is gone; taking them along says so in the confirmation.

## Consequences

The library has one more field to copy (`view`, from `$ERRAND_CACHES_VIEW`); until it does, all its entries count as
the bare machine's, as before this ADR. Entries made in a container are judged only when a run happens in that
container; a container never used again keeps its marks as they were, and its entries are removed by hand (unused for
N days). A cache directory seen by no run since this ADR is not in any registry: the next run writes it down. A
directory shared over NFS is purged by the machine that made it, and by nobody if that machine stops running errand:
it is still shown and removed by hand from any machine that reaches it. On a cluster, the first machine is often a
compute node (on cinaps, node14 made the project's `caches/`): it has no host agent, so the directory is purged by the
bare runs there until the login node is made to hold it (`errand caches hold cinaps`, done on 2026-11-19). A process alive for more than a day whose journal was just removed
writes its `use` line to a new file of the same name, which is read from its start.
