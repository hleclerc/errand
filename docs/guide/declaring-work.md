# Writing entries

::: warning Being reworked
errand's own entries are being reworked into a protocol any program can follow: results written to
a file, needs in each framework's own vocabulary, exit code 77 for a skip
( [ADR 0003](https://github.com/hleclerc/errand/blob/main/docs/adr/0003-run-launches-everything-output-on-request.md) ).
`entry`, `Param`, `need` and `skip` stay; the traits below are the part most likely to change.
:::

You do not need entries to use errand: a command, a script or a pytest, Catch2 or cargo suite runs
as it is ( see [Running a suite test by test](/guide/runners/) ). Entries are for work with no
framework of its own: a number to follow, a picture to look at, a step to run on a cluster.

```python
# test_primes.py
import time
from errand import test, bench, experiment, Param
from primes import sieve

if test( "small primes" ):
    assert sieve( 30 ) == [ 2, 3, 5, 7, 11, 13, 17, 19, 23, 29 ]

if p := bench( "sieve", n = Param( 100_000, help = "upper bound" ) ):
    t = time.perf_counter( )
    found = sieve( p.n )
    p.results[ "seconds" ] = time.perf_counter( ) - t
    p.results[ "primes" ]  = len( found )

if p := experiment( "gaps", n = Param( 100_000 ) ):
    ps = sieve( p.n )
    ( p.out_dir / "gaps.txt" ).write_text( str( [ b - a for a, b in zip( ps, ps[ 1 : ] ) ] ) )
```

```bash
errand run test_primes.py::sieve              # one entry, by name
errand run test_primes.py::sieve --n=1000000  # with another value of its parameter
errand run -k bench '**::*'                   # every benchmark under here
errand list '**::*'                           # what is there, with the parameters each takes
```

The whole example, with a benchmark that also asserts, is
[`examples/03-entries`](https://github.com/hleclerc/errand/tree/main/examples/03-entries).
`primes.py` knows nothing about errand: work is declared beside the code, not inside it.

## The guard is the entry

`if test( … ):` reads like `if __name__ == "__main__":`, but a file can hold as many as it likes.
errand imports the file once to find them, then once more per entry it runs: the guard of that entry
is true, every other one false. Each body runs on its own, and each failure is caught on its own.
Entries are told apart by **call site**, so two may share a name.

The walrus form hands back what the run needs:

| | |
|---|---|
| `p.<name>` | each declared [parameter](#parameters-param), resolved: the default, or what the command line asked for |
| `p.out_dir` | this run's own directory, already created. Write anything you like into it |
| `p.results` | a dict for numbers and strings; it ends up in `result.yaml` |

Numeric results are summarized ( min and max ) at every level above the run, which is what makes
two dates or two machines comparable without declaring anything. An entry can assert, record numbers
and write files, all at once. Outside errand, a file run by hand, `out_dir()` answers `./out`.

## test, bench, track, experiment

| | it is for | `-k` | a bare `errand run` |
|---|---|---|---|
| `test` | something that must pass | `test` | runs it |
| `track` | numbers you want to follow: an error, a residual, a size, a count | `bench` | skips it |
| `bench` | `track`, measured **alone**: timings, or anything a neighbour would disturb | `bench` | skips it |
| `experiment` | something to look at: `latest/` is the path to open | `exp` | skips it |

```python
from errand import test, bench, track, experiment, Param

if p := track( "accuracy", n = Param( 1000 ) ):
    p.results[ "error" ] = abs( solve( p.n ) - exact( p.n ) )
```

A bare `errand run`, the targets of [`errand.default_run`](/guide/configuration#default-run), runs
only the tests among errand's entries: numbers worth keeping are not produced by accident. Name the
others, or ask for them with `-k bench` / `-k exp`. A target that names them, `'**::*'` included,
runs them.

`bench` takes the machine to itself because the commonest numbers worth following are timings, and
a timing taken while something else ran is not a timing. When the numbers are not timings, use
`track`.

## The four traits

The four functions are four lines of Python over `entry`, each setting traits:

| trait | what it decides | `entry` default | set by |
|---|---|---|---|
| `bulk` | picked up by a bare `errand run` | `True` | `test` |
| `keep` | its numbers are kept and compared date to date | `False` | `track`, `bench` |
| `exclusive` | it needs the machine to itself | `False` | `bench` |
| `stable_path` | `latest/` is what you are meant to open | `False` | `experiment` |

Override one on the spot, or write a fifth function the same way:

```python
if p := experiment( "the big one", exclusive = True ):   # a picture that needs the whole GPU
if p := bench( "cheap probe", exclusive = False ):       # a number that does not
if entry( "docs", bulk = False ):                       # a task, run when named: errand run tasks.py::docs
```

## Parameters: Param

`Param( default )` declares a typed flag. The type comes from the default: `Param( 1000 )` is an
int, `Param( "newton" )` a string, `Param( 0.5 )` a float.

```python
if p := bench( "cost", n = Param( 1000, help = "nb of points" ),
                       method = Param( "newton", choices = [ "newton", "lbfgs" ] ) ):
    p.results[ "cost" ] = run( p.n, p.method )
```

```bash
errand run bench/solvers.py::cost --n=5000 --method=lbfgs
errand run --grid=, bench/solvers.py::cost --n=1000,5000    # two runs: see Several runs
```

- Parameters go **after** the target, as `--n=5000` or `--n 5000`; `max_iter` is `--max-iter`.
- A value that cannot be read as the default's type is an error naming the flag, before anything
  runs. `choices` is checked the same way.
- Every parameter takes a value. A yes/no is better written `Param( "no", choices = [ "no", "yes" ] )`
  than as a bool.
- A keyword that is not a `Param` must be a trait or a resource; anything else is a `TypeError`.
  That is what catches `n = 1000` written where `n = Param( 1000 )` was meant.
- Parameters show in `errand list`, and are printed before each run.

Several values of a parameter make a grid only under `--grid=SEP`: see
[Several runs: grids](/guide/matrices).

## Resources

An entry says what it needs, and [the queue](/guide/machine) holds it to that:

```python
if p := test( "wide", cpus = 4, ram = "8G" ):        # a share of the machine
if p := test( "on the card", gpus = 1 ):
if p := test( "distributed", ranks = 4 ):            # 4 MPI processes, each running the body
```

`cpus`, `ram` and `gpus` are counted against what the host has; with `ranks`, they are per rank
( see [Several processes (MPI)](/guide/mpi) ). A [`Slurm`](/guide/layers/slurm) layer hands them to
the scheduler. `--cpus`, `--ram`, `--gpus`, `--ranks` on the command line override them.

## Tags on an entry

```python
if test( "the slow one", tags = [ "slow", "gpu" ] ):
    ...
```

```bash
errand run -e 'slow & !gpu' '**::*'
```

`-e` filters entries with the [expression language](/reference/expressions); `-t` picks
environments with the same one ( see [Tags](/guide/tags) ). An entry tag is a word written on the
work, an environment tag says what a place is: they never mix.

## Two rules about files

**A file that declares work is not a module to import from.** Importing one from another declares
everything in it twice, and errand says so rather than running the copies. Put what is shared in a
file that declares nothing.

**Its own directory is on the import path while it is read**, so `test_primes.py` can
`import primes` from beside it, whichever directory you started errand from.

## What a run leaves

```text
errand-outputs/runs/test_primes.py/sieve/
  2026-09-24_18h04m11-default@thishost-n=100000/
    result.yaml          status, duration, RAM, params, results, tags
    output.txt           what it printed
  latest -> the newest of them
  summary.yaml           one row per run, and the extents
```

See [Results and records](/guide/output).
