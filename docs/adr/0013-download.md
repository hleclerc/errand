---
status: proposed
date: 2026-11-18
---

# `errand.download`: a file by its hash, in a cache errand declares itself

ADR 0012 gave a project cache zones. A project that downloads its input data (otrec: measured
sinograms) still has to write the same few things: where the file goes, a check of its hash, a
`.part` renamed once whole, two runs that must not fetch it at once, a progress line, and what to
say on a node with no internet. Every project writes them again, and each has its own cache.

A run cannot declare a zone itself. The local side decides what crosses (ADR 0005), and by the
time a run starts over there, the push is done. So a download cannot "mark a file as cache" when
it happens. It has to land in a zone that was declared before the push.

## Decision

**`path = errand.download( url )`.** It gives the path of the file, downloaded if it is not there
yet. `sha256 = "…"` is a check, never required. Standard library only (`urllib`, `hashlib`), so
`import errand` stays cheap.

**Where: a cache zone errand declares itself.** `/errand-cache` at the project root, a `cache` zone
(ADR 0012) that every push and every command's pull carry, as `errand-outputs` is an `errand` zone.
Inside, a file is at
`downloads/<sha256>/<its name>`: the name from the URL (or `name =`), so that a tool that reads the
extension still does, under a directory named by the contents. Two machines that fetch the same file
write the same path with the same bytes: there is no conflict to have.

**The hash is never required.**
- Not given, the file is fetched once and put under the hash of what came. The next call finds it
  through a small index, one file per URL (`downloads/by-url/<hash of the URL>.json`). Nothing
  is said: a URL is enough to name a file.
- Given, it is checked after the download, and a file already under that hash is used without
  any network. A file that does not match is removed and is an error, which says both hashes.
- The index is a cache file too. Two machines that both fetched a URL whose contents changed in
  between disagree on it, and the sync says so (ADR 0012). Giving the hash settles it.

**The steps.** A `.part` beside the target, renamed once whole and checked. A lock (a directory,
`mkdir` is atomic on NFS and Lustre) per file: a second run that wants it waits for the first, then
finds it there. Progress is an `errand.step` (ADR 0010): name, bytes, fraction when the size is known.
An interrupted download starts over; no resume.

**No internet: up the chain of agents.** That is what the agents are for. A run that cannot reach
the URL asks the side that drives it. The request goes as a line of the run's journal (ADR 0010),
said as a mark of its session to the side here, which follows it anyway. Then, in order:

1. the agent of the host over there (the login node of a cluster, the machine around a
   container) downloads it into the copy, which is the run's file system or shares it;
2. failing that, this side downloads it into the project here, and sends it into the copy
   through that agent, as a push does.

The answer (the hash, or why it failed) is written beside the downloads over there, where the run
waits for it, then removes it. Downloaded here, the file is in the project's cache here too.
A run nobody follows (detached, `errand submit`) is not told to ask, and fails saying so, as a run
started by hand with no internet does. `errand download URL` fills the cache here beforehand, and
the next push carries it.

**Outside errand.** The same call, the same path from the project root (`errand.cache_dir`'s rule),
the same checks. A script run by hand shares its downloads with the runs.

**Other languages.** `$ERRAND_PYTHON -m errand download URL` prints the path, asking up the chain
as the call does. In a shell script, `eval "$ERRAND_STEPS_SH"` adds a `download` function, as it
adds `step`.

**What stays out.** Authentication, headers, mirrors, resuming, decompressing. A project that needs
them downloads by itself into a cache zone of its own (ADR 0012).

## Considered options

- **Mark a file as cache when it is downloaded**, with a list errand reads before the next push.
  The first run on a node with no internet still finds nothing, and the zone would depend on what
  ran last. A zone declared up front is simpler and always right.
- **A cache under the home folder, shared by projects** (`~/.cache/errand/downloads`). Several
  projects would share their data, but a copy only carries what is in the project, and a cluster's
  home is often small. A project that wants it can make `errand-cache` a link (followed toward
  Windows, kept as a link elsewhere).
- **The hash required.** Safest, but the hash of a file not yet downloaded is rarely known, and a
  URL already names it.
- **No internet is an error that says to run `errand download` here.** Simple, but it is exactly
  what the agents can do for the user: the side here follows the run and can reach the URL.
- **Leave it to each project.** It is what otrec does today, with an environment variable that
  errand does not pass on (it passes `key=value` arguments, not variables).

## Consequences

A project downloads with one call, and a node with no internet gets the file through the next push.
Every machine that ran a download sends the file back here, once, and it then goes to every other
copy. `errand-cache` grows as the cache zone does: never pruned by errand, removed by hand on each side.
Files downloaded without a hash can conflict through the index, until a hash is given. The
protocol gains a `download` request of the host agent, and a way to send one file into the copy.

## Order of work

1. `errand.download`, the zone declared by default, the lock and the steps. Tests: a local HTTP
   server, a wrong hash, two runs at once, no network.
2. Up the chain: the want in the journal, the mark, the host agent's `download`, the file sent
   from here. Tests with `local` agents and a URL only this side reaches.
3. `errand download` on the command line, and the shell function.
4. otrec: its `cached_download` replaced by `errand.download` in the experiments' entries.

Steps 1 to 3 done on 2026-11-18 (`errand/downloads.py`, `cli/relay.py`, `op: download` and
`op: receive` of an agent, `tests/test_downloads.py`). Tried on this machine with `local` agents
standing for the host, then on lmo on 2026-11-18 (`lmo-numpy`): a direct download, one through
lmo's host agent (the run behind a dead proxy), and one only the Mac could reach (a server on its
`127.0.0.1`), downloaded here and sent. Each came back here with the cache's pull. That run showed
one waste, fixed since: a file a run downloaded, back here, was pushed whole once more, because
the copy's manifest did not know it. A push now asks the copy for the hash of a cache's file it
does not know, and records it. Not tried through a Windows guest, nor on a cluster.
