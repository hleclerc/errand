# Running a suite test by test

A pytest, Catch2 or cargo suite runs under errand as it is, one test at a time, with a record per
test and every environment errand knows. Nothing in the suite changes: `pytest tests/` and
`./cpp/test_geometry` still work exactly as before.

```bash
errand run '**::*'                       # every test of every suite under here
errand run "tests/test_api.py::*"        # the tests of that file
errand run cpp/test_geometry.cpp::area   # one Catch2 case, by name
errand run -e '!slow' '**::*'            # pytest marks are entry tags
errand run --grid=, --env local,old '**::*'   # every suite, in two environments
errand list "tests/test_api.py::*"       # what that names, and which runner took it
```

## `x::y`: a file, then the tests in it

`::` is what asks for tests. The left side is a path from the current directory, the right side a
test name; both are globs: `*`, `?`, `[…]`, `{a,b}`, and `**` for any depth of directories on the
path side. A directory with `::` means everything under it.

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
`errand list` says which runner took each test.

## Choosing tests by tag: `-e`

Every test carries tags, and `-e` filters on them with the
[expression language](/reference/expressions) `-t` uses on environments:

| runner | its tags |
|---|---|
| `Pytest` | the marks: `@pytest.mark.slow` is the tag `slow` |
| `Catch2` | the `[tags]` of the case, and `catch2` |
| `Cargo` | `cargo`, and the target's kind ( `lib`, `test`, … ) |
| errand's own | the `tags = [ … ]` of the [entry](/guide/declaring-work#tags-on-an-entry) |

```bash
errand run -e 'slow & !gpu' '**::*'
```

`-e` picks *what* runs; `-t` picks *where*. `-k test`, `-k bench`, `-k exp` pick
[errand's own entries](/guide/declaring-work) by kind.

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

| name | runner | takes | one entry per |
|---|---|---|---|
| `errand` | `Errand()` | a `.py` that imports errand | [`if test( … ):`](/guide/declaring-work) |
| `pytest` | [`Pytest()`](./pytest) | `test_*.py`, `*_test.py` | test |
| `catch2` | [`Catch2()`](./catch2) | `test_*.cpp` that mentions catch | test case, after a build |
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

A runner that needs a build runs the command you already build with, once, before any of its
tests, in the place they run:

```python
errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )
errand.runners.replace( errand.Catch2( dir = "cpp", build = "cmake --build build", binary = "build/{stem}" ) )
```

Once, not once per file, and not once per process under `-j`. Your compiler, your flags and your
layout stay yours. `cargo` needs none of this: `cargo test` builds what it runs.

## What adopting them buys

Each suite keeps its own tool, its own assertions and its own idea of what a test is. It gains what
happens around the run:

| | before | after |
|---|---|---|
| where it runs | wherever you typed it | any declared environment, several at once |
| output | scrollback | a directory per run, per place, per date |
| numbers | printed | `result.yaml`, summarized across dates and machines |
| on another machine | copy, ssh, remember to fetch | one flag, results brought back |

## The pages of this part

- [Adopting a suite](./adopting): three suites put under errand, on an example.
- [Pytest](./pytest), [Catch2](./catch2), [Cargo](./cargo): what each runner takes.
- [Scripts and executables](./scripts): a file run whole.
- [Writing a runner](./writing): for another framework.
- [Writing entries](/guide/declaring-work): errand's own way of declaring work.
