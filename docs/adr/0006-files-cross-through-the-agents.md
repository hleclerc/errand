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
in the project's errand state, the remote one in the copy itself (`.errand-copy`, never synced). A
file is hashed again only when its size or mtime changed since the list was made. The walk is `stat`
only, never a read.

**The manifest belongs to the copy, not to a machine.** Two `Ssh` hosts can see one file system (the
login and compute nodes of a cluster, two machines with a shared home). Their roots are then one
copy, reached two ways. A manifest kept by each host's agent would take what the other host pushed
for a change behind errand's back. Kept in the copy, it is the same file whichever host reads it,
and whoever wrote it last was errand. A lock beside it (`.errand-copy.lock`, a directory, since
`mkdir` is atomic on NFS and Lustre) keeps two pushes from writing the copy at once. Nothing has to
be declared: no option names what is shared. That holds however the root is reached, through a
link or not, since the manifest is found inside the directory, not by its path. What is not shared
is unaffected: errand's outputs are a zone, so a scratch directory per host
(`errand_outputs_directory`) is never part of the comparison.

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

**A copy is errand's, except where a zone is declared.** Nobody is meant to edit the copy over
there: it reflects the project here. Only declared **zones** change on that side: what a layer
builds (`kept()`, a build directory), what a run writes and is brought back (errand's outputs, a
`pull`), and errand's own records. That has three consequences.

- **The copy's manifest can be trusted.** What errand sent last time is what is there. So it can
  check only the zones and what a push touches, instead of walking the whole tree.
- **A change outside the zones is a finding, not something to overwrite in silence.** The sync says
  which file changed, when, and that it is about to be replaced. The project here stays the
  reference, but nothing is lost without a word.
- **A zone has an owner and a direction.** A build zone is never pushed into and never deleted by a
  push. A zone to bring back only flows toward here. Errand's records stay on each side. The
  messages say which zone and which rule, not "deleted on <host>".

How this is framed:
- **Zones are the project's.** They are declared once, in the project's errand file, not per layer
  or per environment. Environments share a remote root, so they share its zones too. What a layer
  builds (`kept()`) is added to them.
- **A run that writes outside the zones is not stopped.** Nothing watches it while it runs. The
  next check finds what it changed, and says which file and when.
- **The trusted manifest is checked against the disk when the agent holding the copy starts, and
  when it goes.** In between, the agent trusts it. That is one full walk per agent lifetime instead
  of one per command. On Lustre, that walk is what costs.
- **Three kinds of zone.** `back`: written over there, brought back here. `build`: built over
  there. `errand`: errand's outputs, each side its own. The project declares the first two,
  `errand.configure( zones = { "/results": "back" } )`, with rsync's patterns (a name anywhere, or
  anchored at the root by a leading `/`). `errand` is errand's own. The defaults that were rsync
  excludes split in two: caches and repositories (`.git`, `__pycache__`) are no part of a copy at
  all, and build products (`build`, `.venv`, `*.so`) are `build` zones.
- **What a check finds waits with the manifest.** The agent's check has nobody to tell. It writes
  what it found next to the trusted manifest, with the time it first saw each change. The next sync
  says it, then puts it back. Each such message ends with the zones and how to declare one, since a
  run that writes outside them most likely needs a zone.

**What is copied.** Regular files keep their contents, their mtime and their executable bit. Owner,
group, ACLs and xattrs are dropped. Symlinks stay links, except toward Windows, where they are
followed. Paths are NFC on the wire, since macOS writes NFD. Two names that differ only in case,
headed for a case-insensitive file system, are an error, not a silent overwrite. A file that changes
while it is read is read once more, then reported.

**Watching only says where to look.** On the local side, file system events (FSEvents, inotify)
narrow the walk to the directories that changed since the last sync. They are never trusted alone.
Events get merged or dropped, nothing watches while no process does, and nobody receives events for
Lustre or NFS on another node. Any doubt (a watcher that restarted, an overflow) means a full walk.
The remote side has no watcher. It walks its zones, plus what the push touches, and leaves the rest
of its tree to the trusted manifest (above).

**Before any agent exists.** errand's sources are shipped before there is an agent to receive them.
They are a tar on the stdin of the bootstrap line, unpacked by the Python over there (or `tar`). The
tar is small, and rare, since `.sources` already skips it when nothing changed. It is always a tar
(step 5 below says why).

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
changes nothing costs a walk here, a walk of the zones there, and one exchange of manifests, with
no extra process. Zones turn today's rsync excludes into declarations. A change of the copy outside
them is something errand can name and report.
In return, the corner cases rsync settled long ago become ours: links, permissions, interrupted
copies, case, Unicode, files that change while they are read. Each one needs a test before the sync
becomes the default. Throughput through Python and our frames will be below rsync's for large
volumes; how far below is measured, not assumed.

## Order of work

1. The manifest and the sync between two directories on this machine. The corner cases above are
   tests.
2. Zones: the project declares them. Their rules, the check when the agent starts and when it goes,
   and the messages when a change falls outside them. (Done in `sync.py`; the rsync push already
   leaves declared zones alone. Calling the check from the agent waits for step 3.)
3. The push over `Ssh` behind an option, measured against rsync on lmo and jz with otrec, loom and
   sdot-ffi. Three cases: cold, warm with no change, and one file changed.
   Done: `Ssh( transfer = "sync" )` or `ERRAND_TRANSFER=sync`. Measured on lmo from the Mac on
   2026-11-15, push only, the host agent already up (it starts in 1.4 s, once). Both sides run
   Python 3.14, so chunks cross as zstd. The copies came out identical.

   | project  | selection         | rsync cold | sync cold | rsync warm | sync warm | rsync 1 file | sync 1 file |
   |----------|-------------------|-----------:|----------:|-----------:|----------:|-------------:|------------:|
   | otrec    | 2597 files, 407 MB | 73.6 s | 20.9 s | 1.33 s | 0.73 s | 1.27 s | 0.78 s |
   | loom     | 309 files, 6 MB    | 1.96 s | 0.95 s | 1.35 s | 0.59 s | 1.15 s | 0.60 s |
   | sdot-ffi | 3851 files, 237 MB | 41.5 s | 24.6 s | 1.58 s | 0.92 s | 1.43 s | 0.94 s |

   The cold gain comes from compression (rsync runs without `-z`). The warm gain comes from having
   no `rsh` chain and no remote walk. jz is not measured yet, and neither is a large file that
   changes a little, the case where rsync's delta should win.
4. The pulls, from what the processes say they wrote. Done: `op: pull` streams what is under the
   paths asked for (the plans, the run directories the plan lists, the layers' `fetch`). It adds
   and replaces, and deletes nothing here, as rsync without `--delete` did. A file of the same size
   is hashed on both sides first, and a file that is still being written is read again once. The
   anchored `back` zones are added to what every command brings back, through rsync as well.
   Checked on lmo with otrec (`lmo-sif`, `ERRAND_TRANSFER=sync`, twice): push and pulls went through
   the agent. The first push removed 151 stale files under `src/sdot/` that the local project no
   longer has, and listed them. rsync had left them there; why is not known.
5. errand's sources: tar on the first ship, sync afterwards. Done, and simpler than planned: a tar
   every time, no sync. New sources mean a new sources key, so a new agent. The agent's start is
   what ships them, before any agent of these sources exists, so a "sync afterwards" would never
   run. The tar (270 kB) crosses on the stdin of the line that already checked `.sources`, through
   the hub's agent or one ssh. It is unpacked beside the copy and moved into its place, with
   Python, else `tar`. This is not behind the `transfer` option: rsync is no longer needed to start
   errand anywhere. On lmo a ship through a warm hub takes 0.21 s.
6. The Windows guest: sync through its agent, and MSYS2 goes.
7. Sync becomes the default, rsync the option.
8. Local watching as a hint.
