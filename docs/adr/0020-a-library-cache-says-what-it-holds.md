---
status: proposed
date: 2026-11-19
---

# A library's cache says what it holds; errand removes what no longer serves

ADR 0019 gives every run `$ERRAND_CACHES`, where a library keeps its cache by its name. Such a cache only grows: loom's
reached 19 GB on lmo, and 2.7 GB of kernels nobody would ask for again had been measured before loom split its graph.
What a cache holds, what each piece depends on and whether it can be rebuilt is known only to the library. When to
look at it, and what is worth the bytes on a machine, is errand's.

A design grill settled the points below (`grill/cache-eviction/` of 2026-11-19).

## Decision

**A manifest, kept by the library, read by errand.** At the root of its cache, a library that wants it kept tidy keeps
the format `errand-cache/1`. errand reads nothing else, and knows nothing of the library: what an entry is, what its key
means, what it depends on are the library's to say. A cache without the format is never touched, nor is a directory only
tagged `CACHEDIR.TAG` (a package's catalogue among them).

**An entry is a group of paths that go together.** Its `product`, and its `intermediate` paths (which could go alone
while the product stays). It may `need` other entries; an entry marked `shared` is one that others need. A path no entry
names is never removed.

**No file has two writers.** Each process appends to its own journal, `errand-cache-journal/<host>-<pid>-<start>.jsonl`,
opening, writing and closing the file for each line: a `create` when it builds an entry (again when it rebuilds it), a
`use` of the entries it served, once, when it ends. One agent per machine is not one writer per file: the login and the
compute nodes of a cluster see one cache. So a single **compactor**, under a lock that is a directory (`mkdir`, atomic on
NFS and Lustre, taken over after 15 minutes), takes each journal by renaming it, merges it into `errand-cache.json`, and
removes it. Under errand, errand compacts. Without errand, the library compacts by itself past a number of journals
(64 for loom). It never starts errand.

```text
<cache>/errand-cache-journal/<host>-<pid>-<start>.jsonl
    { "op": "create", "entry": "build/kernels/k", "product": [ "build/kernels/k" ], "intermediate": [ ],
      "needs": [ "build/units/u.so" ], "shared": false, "size": 812345, "cost_s": 41.2,
      "deps": { "/abs/path/Cell.h": [ "<sha256>", 1234, 1731999999000000000 ] }, "at": "2026-11-19T10:00:00Z" }
    { "op": "use", "entries": [ "build/kernels/k" ], "at": "2026-11-19T10:05:00Z" }
<cache>/errand-cache.json        { "format": "errand-cache/1", "hash": "sha256", "purged": "…", "entries": { … } }
<cache>/errand-cache.lock/       the compactor's
```

Paths of an entry are relative to the cache; `deps` are absolute (a cache is one machine's), with the size and mtime
they had, so that only a file that moved is hashed again.

**What goes, for now.** No age and no size budget: what the dependencies say must be enough first.

1. An entry not used for a day, one of whose `deps` is gone or holds other contents. The day spares a branch switched
   away and back.
2. A `shared` entry not used for a day that no remaining entry needs, after rule 1 has removed what it removes.
3. Intermediates: in the format, not removed yet.

**When.** On the machine of the run, the first run of a command purges the caches of `$ERRAND_CACHES` that were not
purged for a day. A run, not the agent: the agent does not know which projects it holds caches for. One line is said for
a cache something went from, nothing otherwise. `errand caches [--dry-run]` does it at once, here, and gives each cache's
entries and size.

**The library is responsible for its key and its `deps`.** For loom:

- An entry per kernel (`build/kernels/<name>`), written when ninja built it. A kernel's name is the hash of its generated
  source, not of its headers: a header that changes rebuilds it in place, under the same name, and the entry is written
  again with what it depends on now. Its `deps` are the closure of headers ninja knows, plus the `.py` that built its
  `FfiCode` (`FfiCode.origin`) and what `depends_on =` adds. A kernel whose code changed in Python has another name;
  the old one is found dead only through that file.
- A `shared` entry per domain unit and runtime (`build/units/…`, `build/runtime/…`, with their objects), which goes once
  no kernel left needs it.
- No intermediates declared: a kernel whose `.o` is gone is rebuilt by loom's fast path, which compares them. How much
  the objects weigh on a real cache is to be measured first.

## Considered options

- **A file beside each entry.** Simplest to write, but it is one more name in the library's directories to collide
  with, and errand would walk the cache to find them.
- **The library purges itself (`loom gc`), errand only triggers it.** One calling convention per library, and errand
  could say nothing of what was freed.
- **Writes through errand's agent.** The library would depend on errand, and the agent is not unique per file system.
- **An age limit (60 days) as a safety net.** Left out on purpose: dependencies that say enough make it unnecessary,
  and a limit would hide that they do not. To be reopened if a cache keeps growing.

## Consequences

A cache tidies itself on a machine that runs under errand, by what its library says, a day after what it depends on
changed. A kernel used less than once a day is rebuilt after an unrelated edit of its `.py`: its cost is one
compilation. A process that dies loses its uses, so its entries look older than they are; that only matters to rule 1,
which also needs a dependency changed. Runs by hand compact their journals and remove nothing.
