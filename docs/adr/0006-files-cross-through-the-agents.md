---
status: proposed
date: 2026-11-13
---

# Files cross through the agents, by manifest, not through rsync

Every copy errand makes is an rsync today. The push of the project (`gateways.push`: `--delete -i`,
`RSYNC_EXCLUDES`, errand's own outputs, the `kept()` paths of every layer). The pulls of results
(`gateways.fetch`). errand's own sources (`bootstrap.ship`). The Windows guest (`vm/transfer.py`,
an rsync and ten DLLs pinned from MSYS2 and installed into the image). Since ADR 0005, rsync's
remote shell is `python -m errand.agents rsh`, which goes through the hub and the host agent to start
`rsync --server` over there.

Four things are wrong with that.

- **rsync must be on both ends.** It is not on a Windows guest, which is why MSYS2 is pinned. It is
  not in a minimal image, and not on every machine a user can ssh into. macOS now ships openrsync,
  whose flags and output are not quite rsync's.
- **The chain is long.** rsync starts the `rsh` process, which reaches the hub, which reaches the host
  agent, which starts `rsync --server`. Each link has its own lifetime. On 2026-11-13 a hub started by
  that `rsh` kept rsync's pipes open, and a push waited forever for an end of stream that never came.
- **Every push walks both trees in full.** On Lustre or NFS (jz), a walk of `stat` calls is the
  slow part of a push that changes nothing.
- **The rules are rsync flags.** They are rebuilt in several places (push, ship, the guest), and the
  pull guesses which directories to bring back.

So files cross through the agents. A **sync** is one more operation of the protocol, on a channel of
its own, between the local side and the agent that holds the other copy.

**A manifest on each side.** For a root and a selection, each side lists its files as
`path → ( size, mtime_ns, mode, hash )`. It keeps that list from one sync to the next: the local one
in errand's per-user directory, the remote one in the agent's directory. A file is hashed again only
when its size or mtime changed since the list was made. The walk is `stat` only, never a read.

**The local side decides, the agent applies.** This is ADR 0005's rule. The selection (excludes,
errand's outputs, `kept()` paths) is computed here and sent with the request. The agent never applies
rules of its own. A push goes like this:

1. The local side sends its manifest.
2. The agent answers with what it lacks or has in another version, and what it has that is not in the
   manifest.
3. The local side sends whole files, compressed (zstd when there, zlib otherwise).
4. The agent writes each one beside its target and renames it into place.
5. The deletions are applied and shown, as `deleted on <host>` is shown today.

A pull is the same, the other way round. What to bring back is known, not guessed: the processes an
agent started say what they wrote under the run's output directory.

**What is copied.** Regular files keep their contents, their mtime and their executable bit. Owner,
group, ACLs and xattrs are dropped. Symlinks stay links, except toward Windows, where they are
followed. Paths are NFC on the wire, since macOS writes NFD. Two names that differ only in case,
headed for a case-insensitive file system, are an error, not a silent overwrite. A file that changes
while it is read is read once more, then reported.

**Watching only says where to look.** On the local side, file system events (FSEvents, inotify)
narrow the walk to the directories that changed since the last sync. They are never trusted alone.
Events get merged or dropped, nothing watches while no process does, and nobody receives events for
Lustre or NFS on another node. Any doubt (a watcher that restarted, an overflow) means a full walk.
The remote side always walks. Runs write into its tree, and so do other sessions.

**Before any agent exists.** errand's sources are shipped before there is an agent to receive them.
That first copy is a tar on the stdin of the bootstrap ssh, unpacked by the Python `bootstrap`
already finds over there. It is small and rare, since `.sources` already skips it when nothing
changed. Once an agent answers, the sources go by sync like anything else.

**rsync stays, as an option.** A sync sends whole files, with no rolling checksum. That is fine for
sources and results. It is a loss for a large file that changes a little, such as a checkpoint or a
dataset appended to. `transfer = "rsync"` on an `Ssh` keeps the old path for such a project until a
delta for large files is worth writing.

## Considered options

- **Ship a static rsync where it is missing, as MSYS2's is for Windows.** It still needs a binary per
  OS and architecture, it keeps the `rsh` chain, and the rules stay rsync flags.
- **Speak rsync's protocol over our channel**, with no `rsh` process. That shortens the chain, but
  rsync must still be on both ends.
- **A tar per command.** This is what the Windows guest did before rsync: everything crosses every
  time.
- **Trusting the watcher, with no walk.** Rejected for the reasons above. A missed event is a file
  that silently never reaches the other side.

## Consequences

A remote machine needs ssh and a Python, nothing else. The guest image loses MSYS2. A push that
changes nothing costs one walk on each side and one exchange of manifests, with no extra process.
In return, the corner cases rsync settled long ago become ours: links, permissions, interrupted
copies, case, Unicode, files that change while they are read. Each one needs a test before the sync
becomes the default. Throughput through Python and our frames will be below rsync's for large
volumes; how far below is measured, not assumed.

## Order of work

1. The manifest and the sync between two directories on this machine. The corner cases above are
   tests.
2. The push over `Ssh` behind an option, measured against rsync on lmo and jz with otrec, loom and
   sdot-ffi. Three cases: cold, warm with no change, and one file changed.
3. The pulls, from what the processes say they wrote.
4. errand's sources: tar on the first ship, sync afterwards.
5. The Windows guest: sync through its agent, and MSYS2 goes.
6. Sync becomes the default, rsync the option.
7. Local watching as a hint.
