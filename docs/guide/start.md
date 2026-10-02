# Start from what you have

errand does not ask you to write anything in its language first. It asks what you already test
with, and where you would like that to run.

```bash
cd my-project
errand                 # looks at the directory, says what it found, runs it
errand --init          # writes that down as errandfile.py, and makes runs/
```

With no `errandfile.py`, errand reads the directory and **tells you what it guessed** before it runs
anything:

```text
  no errandfile.py; guessed:  pytest (tests/)  ·  catch2 (cpp/)  ·  cargo (rust/)   ( errand --init writes it down )
```

It is a guess about your layout — every framework finds its tests by assuming something — so it is
never silent, and the cure is to write it down. That is all `errand --init` does.

## Pick your tools

::: code-group

```text [pytest]
my-project/
  src/mylib/…
  tests/test_api.py          # plain pytest. Nothing about errand in it
```

```text [C++ · Catch2]
my-project/
  cpp/geometry.h
  cpp/test_geometry.cpp      # #include <catch2/…>
  cpp/Makefile              # what YOU build with
```

```text [Rust · cargo]
my-project/
  Cargo.toml                 # or rust/Cargo.toml
  src/lib.rs
```

```text [Any command]
my-project/
  Makefile                   # `make check`
  run_experiment.sh          # no framework at all
```

```text [errand's own entries]
my-project/
  solver.py
  bench/solver_bench.py      # `if track( "cost" ):` — see Declaring work
```

:::

::: code-group

```python [pytest]
# errandfile.py, as written by `errand --init`
from errand import configure, provider, Pytest

configure( out = "runs" )
provider( Pytest( dirs = [ 'tests' ] ) )
```

```python [C++ · Catch2]
# errandfile.py, as written by `errand --init`
from errand import configure, provider, Catch2

configure( out = "runs" )
provider( Catch2( dir = 'cpp', build = 'make -C cpp' ) )     # built once, before any file runs
```

```python [Rust · cargo]
# errandfile.py, as written by `errand --init`
from errand import configure, provider, Cargo

configure( out = "runs" )
provider( Cargo( manifest = 'Cargo.toml' ) )
```

```python [Any command]
# Nothing to declare for a command: `errand --env X -- cmd` needs only the environment.
# Declare the work if you want its output kept, queued and compared:
from errand import entry

if entry( "check", bulk = False ):
    import subprocess
    subprocess.run( [ "make", "check" ], check = True )
```

```python [errand's own entries]
# No errandfile needed at all: a file that imports errand is found by that alone.
from errand import track, Param

if p := track( "cost", n = Param( 1000 ) ):
    p.results[ "residual" ] = solve( p.n )
```

:::

Each suite keeps **its own runner, assertions and marks**: `pytest tests/` still works exactly as
before. A `@pytest.mark.slow` is an entry tag, a Catch2 `[tag]` likewise, and `-e '!slow'` filters
on them. The detail of each is in [Other languages](./providers).

## What it looks for

| it finds | when | writes |
|---|---|---|
| pytest | `tests/` or `test/` holds `test_*.py` / `*_test.py` that do not import errand, or such files sit at the root | `Pytest( dirs = [ … ] )` |
| Catch2 | `test_*.cpp` mentioning Catch within two directories of the root; a `Makefile` beside them becomes `build =` | `Catch2( dir = …, build = … )` |
| cargo | a `Cargo.toml` within two directories of the root | `Cargo( manifest = … )` |
| errand's own entries | any `.py` that imports `errand` — found by a text check, nothing to declare | nothing |

Nothing is run to find any of that: it lists directories and reads a few files. An empty directory
gets an `errandfile.py` too — with the three provider lines and a stack of layers in comments, ready
to be uncommented.

`errand --init` never overwrites: `--init=force` replaces an existing file.

## Then: where it runs

The same suite, unchanged, in more than one place — that is the point of the file you just wrote.
Add a stack of [layers](./environments) beside the provider line:

```python
from errand import env, Micromamba, Apptainer, Ssh, Slurm

env( "local",   [ Micromamba( "myproject", python = "3.13" ) ] )
env( "cluster", [ Ssh( host = "gpu-box", root = "~/errand/myproject" ),
                  Slurm( partition = "gpu", time = "00:30:00" ),
                  Apptainer( image = "containers/main.sif", recipe = "containers/main.def" ) ] )
```

```bash
errand --env local,cluster         # every suite, in both places
errand --env cluster -- nvidia-smi # be let in, to look
```

The environments are built the first time they are needed, checked against what you declared before
every run after that, and the files a run produced on `gpu-box` are rsynced back to a path that was
known before it started.

<Term scene="stack" caption="What a single --env cluster crosses. Ssh, Slurm and Apptainer are declared once, as layers." />

## Numbers to follow

A suite that already prints numbers — a Catch2 benchmark, pytest's duration — has them kept: each
run's `result.yaml` holds them, and the summaries above it show the extents across dates and
machines. For numbers that are not a suite's at all — an error, a residual, a size, a score, a
timing — see [`track` and `bench`](./declaring-work#test-bench-track-experiment).

## Next

[Declaring work](./declaring-work) for errand's own entries, [Environments](./environments) for the
layers, or the [tutorials](/tutorials/).
