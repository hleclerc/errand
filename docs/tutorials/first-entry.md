# 4 · errand's own entries

::: tip You may not need this tutorial
This one writes work in errand's own declaration, which is optional. With a pytest, Catch2 or
cargo project, start with [2 · Adopt an existing suite](./adopt-a-suite); with only a command, see
[Start from what you have](/guide/start). Come back when you have numbers to follow or a picture to
look at.
:::

Two files, no configuration. `errand` runs in whatever interpreter you started it with.

```bash
cd examples/03-entries
```

```
primes.py         the code; it knows nothing about errand
test_primes.py    five entries: two tests, two benchmarks, one experiment
```

## The code knows nothing about this

```python
# primes.py
def sieve( n ):
    """Primes below `n`, by Eratosthenes."""
    ...

def trial_division( n ):
    """The same thing, the slow way."""
    ...
```

No decorator, no import, no base class. That is the point: work is declared *beside* the code, not
inside it.

## The work

```python
# test_primes.py
import time
from errand import test, bench, experiment, Param
from primes import sieve, trial_division
```

That `from primes import …` works because **a file's own directory is on the import path while it is
being read**. Which directory you happened to start `errand` from does not change what a file can
import.

### It must pass

```python
if test( "small primes" ):
    assert sieve( 30 ) == [ 2, 3, 5, 7, 11, 13, 17, 19, 23, 29 ]

if test( "the two agree", tags = [ "slow" ] ):
    assert sieve( 20_000 ) == trial_division( 20_000 )
```

Five entries in one file, no `if __name__ == "__main__":` anywhere. The guard *is* the entry, and
they are told apart by **call site** — which is why two of them may share a name.

### Numbers to follow

```python
if p := bench( "sieve", n = Param( 100_000, help = "upper bound" ) ):
    t = time.perf_counter( )
    found = sieve( p.n )
    p.results[ "seconds" ] = time.perf_counter( ) - t
    p.results[ "primes" ]  = len( found )
```

`bench` [keeps its numbers](/guide/declaring-work#test-bench-track-experiment) and takes the machine to
itself while it runs — so nothing else errand launched is competing for the cache. The numbers are
timings here, but they need not be: `track` keeps numbers of any kind without the exclusivity.

And a benchmark that also asserts, because there is no rule against it:

```python
if p := bench( "sieve beats trial division", n = Param( 20_000 ) ):
    t = time.perf_counter( ); sieve( p.n )
    p.results[ "sieve_s" ] = time.perf_counter( ) - t

    t = time.perf_counter( ); trial_division( p.n )
    p.results[ "trial_s" ] = time.perf_counter( ) - t

    assert p.results[ "sieve_s" ] < p.results[ "trial_s" ]
```

### It must be looked at

```python
if p := experiment( "gaps", n = Param( 100_000 ) ):
    ps   = sieve( p.n )
    gaps = [ b - a for a, b in zip( ps, ps[ 1 : ] ) ]
    ( p.out_dir / "gaps.svg" ).write_text( … )

    print( f"{ len( ps ) } primes, largest gap { max( gaps ) }" )   # -> output.txt
    p.results[ "largest_gap" ] = max( gaps )
```

`p.out_dir` is this run's own directory, already created — in errand's private record,
`.errand/runs/`, or under `runs/` when the run was given `-o`. An experiment gets a stable `latest/`
symlink beside the stamped ones, so a tab left open on `latest/gaps.svg` keeps working.

## Try it

```bash
errand run -k test '**::*'             # the tests
errand run -k test -e '!slow' '**::*'  # skip the slow one
errand run -k bench '**::*'            # the benchmarks
errand run test_primes.py::sieve       # one entry by name
errand run '**::*'                     # every entry named: tests, benchmarks, the experiment
errand list '**::*'                    # what matched, with the parameters it takes
```

`'**::*'` is every entry of every file under here; `test_primes.py::*` would be those of that file.
A bare `errand run`, with no target, runs what the project declares in `errand.default_run` — and
this directory declares nothing, so it only prints the help.

**A bare `errand run` never runs the benchmarks**, even where `default_run` names their file: they
are not `bulk`, so you name them, or ask for `-k bench`. The experiment likewise. Numbers worth
keeping are not something you want produced by accident.

A comma on a parameter is a matrix:

```bash
errand run -o -k bench '**::*' --n=100000,1000000,10000000
```

Three runs, three directories — `-o` asks for them to be visible, under `runs/` — and a summary at
the entry's root with one row per size.

## What you get back

```text
runs/test_primes.py/sieve/
  2026-09-24_18h04m11-default@thishost-n=100000/
    result.yaml          <- status, duration, RAM, params, results, tags
  2026-09-24_18h04m11-default@thishost-n=1000000/
    result.yaml
  latest -> the newest of them
  summary.yaml           <- one row per run, and the extents: read this after a matrix

runs/test_primes.py/gaps/latest/gaps.svg     <- stable path, reload the tab ( errand run -o test_primes.py::gaps )
```

Without `-o`, the same tree is kept in `.errand/runs/` — the record the screen and the history read.

Nothing here is a special directory that `errand` knew about in advance. Every component is computed
from the entry, its parameters, where it ran and when — which is also how the same path can be
*predicted* before a run happens on another machine, and rsynced back afterwards. That is
[tutorial 2](./environments).

Open one:

```bash
cat runs/test_primes.py/sieve/latest/result.yaml
cat runs/test_primes.py/sieve/summary.yaml
```

## The same thing, on a screen

```bash
errand tui
```

Enter on a case opens one window with every dimension in it: the parameters, the environments, how
many at once. Ticking two values of `--n` is the same matrix a comma would ask for — and the window
builds exactly that comma, printed below the rule so you know what to write in a script.

Enter runs it, and each case's output arrives in the pane facing it, read from the file that case is
writing. `F8` hands what a run produced to the desktop, so `gaps.svg` is two keys away.

## What to notice

- **No `if __name__ == "__main__":`.** The guard is the entry, and there can be five in one file.
- **The benchmark that also asserts.** Two numbers recorded, then one checked against the other.
- **Nothing was configured.** No `errand-*.py` exists in this directory at all.

## Next

[1 · Four environments over three machines](./environments) — where the work stops being the
interesting part.
