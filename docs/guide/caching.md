# Data and results, computed once

A measured dataset, a reference solution, a reconstruction that takes an hour, kernels compiled by a
library: none of it should be fetched or computed twice, on any machine. errand gives a project
three tools for that, and looks after what libraries keep.

| what | how | where it lives |
|---|---|---|
| a file at a URL | `errand.download( url )` | `errand-cache/downloads/`, every machine |
| a result too long to compute twice | `@errand.memo` | `errand-cache/memo/`, every machine |
| your own cache directory | `zones = { "/data-cache": "cache" }` + `errand.cache_dir` | that directory, every machine |
| a library's cache ( compiled kernels ) | `$ERRAND_CACHES/<name>` | per machine, tidied by errand |

The first three live in a [cache zone](./sync#a-cache-zone): both sides add to it, nothing in it is
replaced, and the [sync](./sync) carries what the other side lacks. Computed on a GPU server, a
result comes back here after the command, and reaches the cluster with the next push.

## A file at a URL

```python
import errand

sino = errand.download( "https://example.org/data/scan-042.h5", sha256 = "9f2c…" )
```

The path of the file, downloaded if it is not there yet, under
`errand-cache/downloads/<sha256>/<name>` at the project root: named by its contents, so two machines
that fetch it write the same bytes at the same path. `sha256` is checked when given, never required;
a URL already fetched is found again without the network. Two runs that want one file at once fetch
it once, and a progress line says how it goes.

**A node with no internet** is the usual case on a cluster. A run that cannot reach the URL asks up
the chain: the host over there fetches it into the copy, else this side fetches it and sends it. The
run waits meanwhile. A run nobody follows fails and says what to do:

```bash
errand download https://example.org/data/scan-042.h5
```

here, and the next push brings it. A shell script gets the same as a function:
`eval "$ERRAND_STEPS_SH"; f=$( download URL )`.

## A result computed once

```python
@errand.memo( version = 2 )
def reconstruct( sino, n_iter = 500 ):
    ...
```

The result is kept by the function's arguments, in `errand-cache/memo/`, and read back the next time,
on this machine and on every machine the cache reaches. The key hashes the function ( its file and
name ), `version`, and the arguments bound to its signature, defaults included, by what they hold:
numbers, strings, containers, dataclasses, enums, numpy, jax and torch arrays ( dtype, shape, bytes ),
a `Path` by its file's contents. Anything else is an error that says what to do.

- **The code is not part of the key**: raise `version` when what the function computes changes
  ( `source = True` adds its own source ).
- **Arrays are kept as `.npz`**, the rest pickled; `save` and `load` replace that.
- **Two runs that want one result compute it once.**
- `ERRAND_MEMO=off` computes and keeps nothing; `refresh` computes and replaces.

→ [`memo` in the Python API](/reference/python-api#memo)

## A cache directory of your own

A library that already downloads or memoizes into a directory of its own only needs that directory
to be a cache zone, and to be told where it is:

```python
# errand-project.py
errand.configure( zones = { "/data-cache": "cache" } )

# in the run
loader = Dataset( cache = errand.cache_dir( "/data-cache" ) )
```

`errand.cache_dir` gives the same path in a run over there and in a script run by hand here.

## A library's caches, kept tidy

Every run gets `$ERRAND_CACHES`, a directory on the machine it runs on. A library that keeps a cache
( compiled kernels, say ) puts it in `$ERRAND_CACHES/<its name>`, and falls back on its own default
when the variable is not set. These caches are each machine's own: nothing there crosses.

Such a cache only grows. A library that keeps the format `errand-cache/1` at its root says what each
entry is and what it depends on, and errand removes what no longer serves: entries whose dependencies
changed or went, then shared ones nothing needs any more, at most once a day. A cache without the
format is never touched. → [A library's caches](./storage#a-library-s-caches-errand-caches)

```bash
errand caches                    # this machine: what each cache holds, what is dead, removed
errand caches lmo --dry-run      # another machine, only said
errand caches --unused 30        # also what has not served for 30 days
```

Every machine at once: the caches tab of [`errand web`](./web#caches) ( or `errand tui` ),
one row per cache and per place, removing the dead or unused entries of one place or of all.
`errand caches hold MACHINE DIR` lets a machine's agent purge, daily, a cache directory it reaches
( a cluster's login node, for its compute nodes ).

## Next

[Smart sync](./sync) · [Every run, live in the browser](./web) · [Where errand writes](./storage)
