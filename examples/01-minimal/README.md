# 01 — minimal

Two files, no configuration. `errand` runs in whatever interpreter you started it with.

```
primes.py         the code; it knows nothing about errand
test_primes.py    five entries: two tests, two benchmarks, one experiment
```

## Try it

```bash
cd examples/01-minimal

errand                            # the tests, and only the tests
errand -e '!slow'                 # skip the slow one
errand -k bench                   # the benchmarks
errand "test_primes::sieve"       # one entry by name
errand --help                     # what matched, with the parameters it takes
```

A comma is a matrix, here and everywhere else:

```bash
errand -k bench --n=100000,1000000,10000000
```

Three runs, three directories, and a summary at the entry's root with one row per size.

## What you get back

```
runs/
  test_primes__sieve/
    9f3c1a2b7e/                       <- n=100000
      thishost/
        2026-09-24/
          result.yaml                 <- status, duration, RAM, params, results, tags
        summary.yaml                  <- one row per date
      summary.yaml                    <- one row per place
    summary.yaml                      <- one row per parameter set: read this after a matrix
  test_primes__gaps/
    .../latest/gaps.svg               <- stable path, reload the tab
```

Nothing here is a special directory that `errand` knew about in advance. Every component is computed
from the entry, its parameters, where it ran and when — which is also how the same path can be
predicted before a run happens on another machine, and rsynced back afterwards. That is the next
example.

## Notice

- **No `if __name__ == "__main__":`.** The guard is the entry, and there can be five of them in one
  file. They are told apart by call site, so two entries may share a name.
- **The benchmark that also asserts.** `bench( "sieve beats trial division" )` records two numbers
  and then checks one against the other. There is no rule that a benchmark may not fail.
- **`errand` on its own never runs the benchmarks.** They are not `bulk`; you name them, or you ask
  for `-k bench`. The experiment likewise.
