---
status: proposed
date: 2026-11-18
---

# A cache zone: what both sides add to, and nobody replaces

ADR 0006 made a copy errand's, except in its zones. A `back` zone is written over there and brought
back. A `build` zone is built over there, never pushed into, never deleted. Neither fits two needs
that came up with otrec.

- **Downloaded input data.** An otrec experiment downloads measured sinograms (ESRF) into a cache
  directory. A compute node of a cluster often has no internet. It must find the files there,
  so what the cache holds here has to be pushed. What a run downloads there must not be deleted by
  the next push, nor reported as a change outside the zones.
- **Results that are expensive to compute.** Memoized intermediate results. A run writes them over
  there. They stay there across pushes, and they come back here, so that the next machine gets them
  too.

Today, the first one is a file outside any zone: pushed, and what a run adds there is moved aside
at the next push. Declared `back`, it is never pushed. Declared `build`, it is neither pushed nor
brought back.

## Decision

A third kind of zone, **`cache`**: `errand.configure( zones = { "/data-cache": "cache" } )`, with the
patterns of the other zones (a name anywhere, or anchored at the root by a leading `/`).

**Both sides add, nobody replaces.** A file of a cache zone is immutable by its name.

- **A push sends what the copy lacks.** A file of the cache here that is not over there is sent,
  with its mtime, as any other file. Nothing over there is replaced, and nothing is deleted.
- **A command brings back what this side lacks.** An anchored cache zone that names one path
  (`/data-cache`, no `*?[`) is pulled after each command, as an anchored `back` zone is. Only what
  is missing here comes. A cache named anywhere (`memo`) is only pushed and left alone, as a `back`
  zone named anywhere is.
- **Same name, other contents: a conflict, said, not resolved.** A file present on both sides,
  whose contents differ (size, then hash), stays as it is on each side. Each sync that meets it says
  so, with the path and the zone. It is not an error: a run is not stopped because two machines
  computed one result to different last bits. The way out is the name: put a version, a parameter
  set or the expected hash in it (`sinogram-<sha256>.h5`, `memo/<key>.npz`). A cache whose names say
  their contents never has a conflict. A file that only needs its mtime set is no conflict and is
  not touched.
- **Deleting is never propagated.** A file removed on one side comes back from the other at the
  next sync. To drop a file for good, remove it on both sides. errand does not prune a cache: what
  a cache is worth keeping is the project's call, not the transport's.
- **Not a finding.** What appears in a cache zone over there is no change outside the zones: the
  check of ADR 0006 does not report it, and the push does not move it aside.
- **Checked file by file, not by walk.** The copy's trusted manifest may not know what a run wrote
  in a cache since the last walk. So before a file of a cache is written over there, the agent looks
  at its target. A file already there is not replaced: same contents, it is recorded; other
  contents, it is a conflict. No walk of the cache zone is needed for that, and on Lustre a cache of
  data is exactly what should not be walked at each push.

**How a run finds it.** errand runs a command from the root of the copy, so the zone's path from the
root is the cache. `errand.cache_dir( "/data-cache" )` gives that path, absolute, created if it is
missing: the nearest directory above the current one that holds a project file (`errand-*.py`),
joined with the zone's path. Outside errand, run by hand, it is the same project's cache. A library
does not import errand for this. The entry (or the experiment's `main`) passes the directory down,
as an argument, the way errand passes everything else: no environment variable is set for it.

**With `transfer = "rsync"`.** The push sends each anchored cache zone with `--ignore-existing` and
no `--delete`, and the pull brings it back the same way. rsync does not say conflicts: a file
present on both sides is left as it is, silently.

## Considered options

- **A conflict is an error.** Safer for inputs, which should be byte-identical. But it stops a run
  for a result recomputed on another machine, which is the second use. The message keeps the
  information, and a content-addressed name removes the case.
- **The newer one wins.** A silent overwrite in a zone whose point is that nothing is recomputed:
  rejected.
- **Content-addressed storage kept by errand** (a store of blobs by hash, names as links). It
  settles conflicts by construction, but it is a store to design, prune and expose to the run, for
  what a naming convention gives.
- **Two kinds, `input` (pushed only) and `cache` (both ways).** The difference is only whether
  what a run adds comes back. One kind is simpler. A data cache whose files a node downloaded
  coming back here costs one transfer, once.
- **Tombstones, so that a deletion propagates.** A record of what was deleted, on each side, and
  when. Not worth it while nobody prunes caches automatically.

## Consequences

A downloaded dataset is pushed once to each copy, and reaches nodes without internet. A result
computed on one machine reaches the others through here. A cache that grows is pulled after each
command: only what is new crosses, but the first pull of a large cache over there is large, and
the cache here grows with every machine's. Pruning is by hand, on each side. Conflicts are said
at each sync until somebody renames or removes one side; with rsync they are silent.
