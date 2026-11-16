# Running a suite

A pytest, Catch2 or cargo suite runs under errand as it is, in every environment errand knows. A
file is one run of its tool, which does the selecting itself, and the run's record holds what the
tool reported. Nothing in the suite changes: `pytest tests/` and `./cpp/test_geometry` still work
exactly as before.

```bash
errand run '**::*'                       # every test of every suite under here
errand run "tests/test_api.py::*"        # the tests of that file
errand run cpp/test_geometry.cpp::area   # one Catch2 case, by name
errand run 'tests/**::*' -m "not slow"   # pytest's own filter, after the target
errand run --grid=, --env local,old '**::*'   # every suite, in two environments
errand list "tests/test_api.py::*"       # what that names, and which runner took it
```

## `x::y`: a file, then the tests in it

`::` is what asks for tests. The left side is a path from the current directory, a glob: `*`, `?`,
`[…]`, `{a,b}`, and `**` for any depth of directories. A directory with `::` means everything under
it. The right side is handed to the file's tool, in its own words: a pytest node id or pattern, a
Catch2 test spec, a `cargo test` filter. `::*` asks for everything.

```bash
errand run 'tests/**::*'                             # every test under tests/
errand run '**/test_*.py::grad_*'                    # the gradient tests, wherever they are
errand run 'tests/{ot,shapes}/test_*.py::{basic,quick}'
errand run 'tests/**::*',bench/fft.py                # a comma separates targets
```

A path without a glob must exist, and a glob must match something: a typo is an error, never an
empty run that says "all good". Quote the globs, so the shell leaves them to errand.

## Which runner takes a file

With `::`, a file goes to the runner that fits it best: errand's own entries for a `.py` that
imports errand, else pytest, Catch2 or cargo; without `::`, the file is run whole, by the place's
Python for a `.py`, as an executable otherwise.

Two runners that fit a file equally well are an error that names them, never a coin toss: `-r NAME`
picks one for the command. With `::`, a file no runner takes is skipped: a glob there is a filter.
`errand list` says which runner took each file.

## Choosing tests by tag

A tool's tags are the tool's filter, written after the target: `-m "not slow"` for pytest,
`::[math]~[slow]` for Catch2. `-e` filters [errand's own entries](/guide/declaring-work#tags-on-an-entry)
with the [expression language](/reference/expressions) `-t` uses on environments, and is refused
with another runner's targets rather than ignored. `-e` picks *what* runs; `-t` picks *where*.

## Several at once: `-j`

`-j N` runs N runs at the same time, one process each: N files, or N points of a grid. A single run
has nothing to run beside it, so `-j N` goes to its tool when the runner says how: pytest-xdist's
`-n N` for pytest ( installed by the same rule as pytest ), `--test-threads N` for cargo. The run's
claim then asks for N cpus. A runner without a parallelism of its own ( Catch2, a script ) says so,
and runs alone.

```bash
errand run -j 8 tests/test_big.py      # one file, eight pytest-xdist workers
errand run -j 8 'tests/**::*'          # eight files at a time
```

## What a bare `errand run` runs: `default_run`

```python
# errand-project.py
errand.default_run = [ "tests/**::*", "cpp/**::*" ]
```

`errand run` alone runs these targets, written from the project root. Without `default_run`, it
prints the help: errand does not guess what "everything" means for your project.

`errand init` reads the directory and writes the runner lines and a `default_run` that fit it into
`errand-project.py`, in comments: nothing is active until you uncomment it, and `errand run` itself
never guesses.

## The list of runners

`errand.runners` is a dict, name → runner, filled with the ones errand comes with:

| name | runner | takes | one run per |
|---|---|---|---|
| `errand` | `Errand()` | a `.py` that imports errand | [`if test( … ):`](/guide/declaring-work) |
| `pytest` | [`Pytest()`](./pytest) | `test_*.py`, `*_test.py` | file: `pytest x.py[::sel]` |
| `catch2` | [`Catch2()`](./catch2) | `test_*.cpp` that mentions catch | source: its binary, after a build |
| `cargo` | [`Cargo()`](./cargo) | the source root of a test target of the nearest `Cargo.toml` | target |
| `python` | [`Python()`](./scripts) | a `.py`, named without `::` | file |
| `executable` | [`Executable()`](./scripts) | anything else named without `::`: a file, or a command on the place's `PATH` | file |

A project edits it in [`errand-project.py`](/guide/configuration):

```python
# errand-project.py
import errand

errand.runners.replace( errand.Pytest( dirs = [ "tests" ] ) )            # in place of the default one
errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )
errand.runners[ "bench" ] = errand.Pytest( dirs = [ "bench" ], args = [ "-x" ] )   # -r bench picks it
errand.runners[ "mine" ] = Mine( )                                        # one of your own
del errand.runners[ "cargo" ]
```

`replace` puts a configured runner where the default one of its kind was. A second instance under
another name sits beside it: where both take a file they tie, and `-r NAME` says which.

## errand compiles nothing itself

A runner that needs a build runs the command you already build with, once, during the preparation,
in the place its runs go:

```python
errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )
errand.runners.replace( errand.Catch2( dir = "cpp", build = "cmake --build build", binary = "build/{stem}" ) )
```

Once, not once per file, and not once per process under `-j`. Your compiler, your flags and your
layout stay yours. `cargo` needs no `build`: the runner compiles with `cargo test --no-run`, also
during the preparation. Both, on real projects: [Catch2 with CMake](./catch2#example-a-cmake-build-then-the-binaries),
[a cargo crate](./cargo#example).

## What a tool writes elsewhere

A run's own files go to its output directory ( `-o`, `$ERRAND_OUT_DIR` ), and the first choice is to
point the tool there: `--junitxml`, `--benchmark-storage`. Some tools write where they like:
coverage into `htmlcov/`, criterion into `target/criterion/`. On another machine, the next push
would take those for files that do not belong to the copy. The runner says where its tool writes,
as [zones](/guide/layers/ssh#what-gets-pushed):

```python
errand.runners.replace( errand.Pytest( args = [ "--cov=src", "--cov-report=html" ],
                                       zones = { "/htmlcov": "back" } ) )
errand.runners.replace( errand.Cargo( target_dir = None, zones = { "/target/criterion": "back" } ) )
```

- `back`: written over there, **brought back** here after every command, `-o` or not.
- `build`: written over there and left there, never overwritten by a push.

A runner's zones join the project's ( `errand.configure( zones = … )` ), which has the last word on
a path both name. `build/`, `target/` and the like are build zones already. A path may name the
environment: `{env}`, and `{build_dir}`, its build directory, `build/<env>` —
`Cargo( zones = { "/{build_dir}/target/criterion": "back" } )` brings back criterion's reports
from the environment's own target directory.

## What adopting them buys

Each suite keeps its own tool, its own assertions and its own idea of what a test is. It gains what
happens around the run:

| | before | after |
|---|---|---|
| where it runs | wherever you typed it | any declared environment, several at once |
| output | scrollback | a directory per run, per place, per date |
| verdict | printed | the tool's report read back: counts, failed names, in `result.yaml` |
| on another machine | copy, ssh, remember to fetch | one flag, results brought back |

## The pages of this part

- [Adopting a suite](./adopting): three suites put under errand, on an example.
- [Pytest](./pytest), [Catch2](./catch2), [Cargo](./cargo): what each runner takes.
- [Scripts and executables](./scripts): a file run whole.
- [Writing a runner](./writing): for another framework.
- [Writing entries](/guide/declaring-work): errand's own way of declaring work.
