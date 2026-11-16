# Writing entries

::: info What an entry says, and what the command says
An entry says what the work is: its name, its parameters, its tags, and `ranks` when the body is
written for MPI. What the run asks of the machine ( `--cpus`, `--gpus`, `-x` ) and which entries a
bare `errand run` runs ( `default_run` ) belong to the command
( [ADR 0011](https://github.com/hleclerc/errand/blob/main/docs/adr/0011-a-run-is-one-invocation-of-a-tool.md) ).
:::

You do not need entries to use errand: a command, a script or a pytest, Catch2 or cargo suite runs
as it is ( see [Running a suite](/guide/runners/) ). Entries are for work with no
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
errand run -x 'bench/**::*'                  # every benchmark under bench/, each with the machine to itself
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

Four names for one declaration, so that the file says what the work is:

| | it is for |
|---|---|
| `test` | something that must pass |
| `track` | numbers you want to follow: an error, a residual, a size, a count |
| `bench` | numbers that are timings, or anything a neighbour would disturb |
| `experiment` | something to look at: `latest/` is the path to open |

```python
from errand import test, bench, track, experiment, Param

if p := track( "accuracy", n = Param( 1000 ) ):
    p.results[ "error" ] = abs( solve( p.n ) - exact( p.n ) )
```

They behave the same. What differed between them is the command's to say:

- **Which ones run.** A target names them, by file and by name. Keep tests, benchmarks and
  experiments in files or directories of their own ( `tests/`, `bench/`, `experiments/` ), and
  [`errand.default_run`](/guide/configuration#default-run) names what a bare `errand run` runs.
- **The machine to itself.** A timing taken while something else ran is not a timing: `-x` asks
  for the machine alone, for every run of the command ( [Sharing a machine](/guide/machine) ).
- **Numbers kept.** Every recorded result is kept and comparable, whatever declared it.
- **`latest/`.** Every entry's directory has it, beside the stamped runs.

```bash
errand run 'tests/**::*'                 # the tests
errand run -x 'bench/**::*'              # the benchmarks, each alone on the machine
errand run -o experiments/gaps.py::gaps  # an experiment, its files kept: latest/ to open
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
- A keyword that is not a `Param` must be `tags` or `ranks`; anything else is a `TypeError`.
  That is what catches `n = 1000` written where `n = Param( 1000 )` was meant.
- Parameters show in `errand list`, and are printed before each run.

Several values of a parameter make a grid only under `--grid=SEP`: see
[Several runs: grids](/guide/matrices).

## Several processes: ranks

```python
if p := test( "distributed", ranks = 4 ):            # 4 MPI processes, each running the body
```

A body written for MPI cannot run on one process: `ranks` is the one thing an entry says of how it
runs. Each rank takes a core, the run is started under the place's MPI launcher, and a
[`Slurm`](/guide/layers/slurm) layer asks for as many tasks ( see [Several processes (MPI)](/guide/mpi) ).
`--ranks` on the command line overrides it. What the run asks of the machine otherwise is said on
the command line: `--cpus 4 --ram 8G`, `--gpus 1`, `-x` ( [Sharing a machine](/guide/machine) ).

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
