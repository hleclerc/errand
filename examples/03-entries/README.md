# 01 — minimal

Two files, no configuration. `errand` runs in whatever interpreter you started it with.

```
primes.py         the code; it knows nothing about errand
test_primes.py    five entries: two tests, two benchmarks, one experiment
```

## Try it

```bash
cd examples/03-entries

errand run -k test '**::*'             # the tests
errand run -k test -e '!slow' '**::*'  # skip the slow one
errand run -k bench '**::*'            # the benchmarks
errand run test_primes.py::sieve       # one entry by name
errand run '**::*'                     # every entry: tests, benchmarks, the experiment
errand list '**::*'                    # what matched, with the parameters it takes
```

`'**::*'` is every entry under here. There is no `errand-project.py`, so no `errand.default_run`, and
a bare `errand run` only prints the help.

A comma on a parameter is a matrix:

```bash
errand run -o -k bench '**::*' --n=100000,1000000,10000000
```

Three runs, three directories — `-o` makes them visible under `runs/` — and a summary at the entry's
root with one row per size.

## What you get back

```
runs/test_primes.py/sieve/
  2026-09-24_18h04m11-default@thishost-n=100000/
    result.yaml          <- status, duration, RAM, params, results, tags
  2026-09-24_18h04m11-default@thishost-n=1000000/
    result.yaml
  latest -> the newest of them
  summary.yaml           <- one row per run, and the extents: read this after a matrix

runs/test_primes.py/gaps/latest/gaps.svg     <- stable path, reload the tab ( errand run -o test_primes.py::gaps )
```

Without `-o`, the same tree is kept privately in `.errand/runs/`, which is what the screen and the
history read.

Nothing here is a special directory that `errand` knew about in advance. Every component is computed
from the entry, its parameters, where it ran and when — which is also how the same path can be
predicted before a run happens on another machine, and rsynced back afterwards. That is the next
example.

## The same thing, on a screen

```bash
errand tui
```

Enter on a case opens one window with every dimension in it: the cases, the parameters, how many at
once. Ticking two cases, or two values of `--n`, is the same matrix a comma would ask for — and the
window builds exactly that comma. Enter runs it, and each case's output arrives in the pane facing
it, read from the file that case is writing. `o` opens what a run produced.

## Notice

- **No `if __name__ == "__main__":`.** The guard is the entry, and there can be five of them in one
  file. They are told apart by call site, so two entries may share a name.
- **The benchmark that also asserts.** `bench( "sieve beats trial division" )` records two numbers
  and then checks one against the other. There is no rule that a benchmark may not fail.
- **A bare `errand run` never runs the benchmarks**, even where `errand.default_run` names their
  file. They are not `bulk`; you name them, or you ask for `-k bench`. The experiment likewise.
