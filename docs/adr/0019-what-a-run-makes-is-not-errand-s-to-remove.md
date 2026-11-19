---
status: proposed
date: 2026-11-19
---

# What a run makes is not errand's to remove; a library's caches are errand's to place

A push of `~/Projects` to lmo says, at each sync:

    ┆ sdot-ffi/src/sdot/precompiled-kernels/cpu-x86-64: kept there, it holds *.so ( build zone )
    ┆ sdot-ffi/sdot-ffi: kept there, it holds dist ( build zone )

These directories were made over there by a run (`make wheels` collecting loom's catalogue, on
2026-11-14), not by a sync. They are not in the project here, so each push plans to delete them,
fails (they hold `*.so`, a `build` zone), and says so. Then it records them in the copy's trusted
manifest as if errand had written them, and the next push does it all again.

Two things are wrong.

- **Who made it decides.** A sync may remove what a sync wrote and the project no longer has. What a
  run made is not errand's: it is moved aside when it is a file (ADR 0006), never removed. A directory
  that a run made should not even be a candidate, and what it says is not "kept", it is "this is not
  zoned".
- **The zone is known by the library that writes it, not by the project.** loom writes its catalogue
  into the package (`<package>/precompiled-kernels/<tag>/`), and the kernels it compiles into a per-user
  cache. Neither the project nor errand knows that, and ADR 0013 explains why a run cannot declare a
  zone: the push is over when it starts.

## Decision

**1. Only what errand wrote is errand's to remove.** The copy's trusted manifest keeps, beside what
errand wrote, the directories a push could not remove because a run's files are in them (`theirs`).
Such a directory is said once, with what it holds and how to zone it. Then it is only removed
once it is empty, without a word. It goes back to errand's when the project has it again.

**2. A directory tagged as a cache is a zone, on whichever side it is.** A directory holding a
`CACHEDIR.TAG` whose first line is the standard signature
(`Signature: 8a477f597d28d172789f06886806bc55`, <https://bford.info/cachedir/>) is skipped by a walk,
as a `build` zone is: never sent, never removed, never a finding. Each side keeps its own. The tag is
on the disk, so it is found by the side that walks it -- over there by the agent, at the push that
follows the run that wrote it. No configuration, and the library does not import errand. pytest,
cargo, ruff and others already write it; loom writes it in its catalogue and its caches.

`build` and not `cache` (ADR 0012): what such a directory holds is regenerated from the sources, for
one machine (a catalogue for `x86-64-v3` or `sm_75`, 19 GB of objects in loom's build cache on lmo).
Carrying it back here, then to every other machine, costs more than it saves.

**3. A library asks errand where its caches go: `ERRAND_CACHES`.** Every run gets `ERRAND_CACHES`, an
absolute directory of the place: `<errand outputs>/caches` of the copy (`errand-outputs/caches`, or
the scratch disk `errand_outputs_directory` names). A library puts its cache in a subdirectory named
after itself (`$ERRAND_CACHES/loom`) and tags it (2). Unset -- a run by hand, a user who never heard
of errand -- the library uses its own default. An explicit setting of the library
(`LOOM_CACHE_DIR`) wins over both.

This is the one variable errand sets for a library. ADR 0012 sets none for a cache zone, because the
entry is there to pass its path down; a compiler three calls below the entry has no such path, and
should not have one.

## Considered options

- **The catalogue as a `cache` zone of ADR 0012, declared in the project file.** Both sides add to it.
  But the declaration would be in every project that uses sdot, by path, and the catalogue would come
  back here from every machine and go to every other: a wheel built here would ship the cards of lmo.
- **The library calls `errand.declare_zone( path )` at run time.** Too late for the push it should
  have changed, and it makes the library import errand.
- **An errand-specific marker (`.errand-zone`, holding a kind).** It could say `cache` as well as
  `build`. Nobody else writes it, and the standard tag already says what is needed: regenerable, not to
  be copied.
- **Keep the per-user cache (`~/.cache/loom`).** It works, but errand knows nothing of it: on a cluster,
  each environment file sets `LOOM_CACHE_DIR` to the scratch disk by hand, and the home quota is the
  error when it does not.

## Consequences

The lines above are said once, then never again; the stray `sdot-ffi/sdot-ffi` of lmo too, which only
a hand removes. A directory that a run makes and the tag covers is never said at all.

loom's build cache moves, for runs under errand, from `~/.cache/loom` to `errand-outputs/caches/loom`
of the copy: a cold cache once per machine, unless the old one is moved there. A run by hand and a
run under errand on the same machine then have two caches; setting `LOOM_CACHE_DIR` gives them one.

With `transfer = "rsync"`, the tag is not read (rsync has no such filter): only the zones are.
