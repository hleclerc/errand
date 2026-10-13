# Runners: other languages, and suites you already have

errand does not care what your tests are written in. An entry does not have to be a Python call
site, and most of what you run will not be. What runs a file is a **runner**, and the ones that
come with errand already know errand's own files, pytest, Catch2, cargo, python and shell scripts,
and executables — with an output directory, summaries, environment matrices and remote
repatriation for all of them, none of which they had before:

```bash
errand run                              # every suite found under here
errand run tests/test_api.py            # the python ones
errand run cpp/test_geometry.cpp::area  # one Catch2 case, by name
errand run -e '!slow'                   # pytest marks are entry tags
errand run --env local,old              # every suite, both python versions
errand run scripts/plot.py              # a script, recorded like the rest
```

## Which runner takes a file

Every runner says how well it fits a file, on one scale:

| level | what it means | the runners that come with errand |
|---|---|---|
| `ERRAND` | a file declaring errand's own entries | `Errand`: a `.py` that imports errand |
| `FRAMEWORK` | a suite of a framework errand adopts | `Pytest`, `Catch2`, `Cargo` |
| `LANGUAGE` | a language errand knows how to run | `Python`, `Shell` |
| `FALLBACK` | something that can be run at all | `Executable` |

**The best fit wins, and the order of the list never decides.** A `test_*.py` that imports errand
is errand's, not pytest's; a pytest file is pytest's before it is a python script; a python script
is python's before it is an executable. Two runners at the same, highest level is an **error** that
names them — never a coin toss settled by which was added first.

**Only what declares itself as work is found by looking.** `ERRAND` and `FRAMEWORK` files are picked
up by a glob, a directory, or a bare `errand run`. `LANGUAGE` and `FALLBACK` ones are taken only when
named, path in full: otherwise `errand run '**/*.py'` would execute every module of a library as a
script. `errand list` says which runner took each entry.

**One entry or several is the runner's to say**, since only it knows whether its ecosystem can list
what is in a file without running it: pytest and cargo can, a script cannot, and a compiled suite
can once it is built — which is why it is built during the preparation, where it runs. A file run as a whole is one case in the output tree,
`runs/scripts/plot.py/`, with no level named after it a second time. A `::name` on it is handed to
the file as its own filter when its runner takes one (Catch2, cargo), and refused otherwise.

## The list is yours

`errand.runners` is a plain list, filled with the runners above. A project edits it in
[`errand-project.py`](./configuration):

```python
# errand-project.py
import errand

errand.runners.replace( errand.Pytest( dirs = [ "tests" ] ) )            # in place of the default one
errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )
errand.runners.append( Mine( ) )                                          # one of your own
errand.runners[ : ] = [ r for r in errand.runners if r.name != "executable" ]
```

`replace` puts a configured runner where the default one of its kind was. `append` would put it
*beside* the default one, the two would tie over every file, and errand would say so.

## What adopting them buys

Each suite keeps its own tool, its own assertions and its own idea of what a test is. What it
gains is everything that happens *around* the run:

| | before | after |
|---|---|---|
| where it runs | wherever you typed it | any declared environment, several at once |
| output | scrollback | a directory per run, per place, per date |
| numbers | printed | `result.yaml`, summarized across dates and machines |
| on another machine | copy, ssh, remember to fetch | one flag, results rsynced back |

A Catch2 benchmark is the clearest case: it already measured something, and the measurement went to
the terminal and died there. Now the numbers accumulate per machine and per date, next to the
Python ones, in the same tree.

## A vocabulary translated, not replaced

A `@pytest.mark.slow` **is** an entry tag, so `-e '!slow'` filters it with the same
[expression language](/reference/expressions) `-t` uses on environments. A Catch2 `[tag]` likewise.
A framework's own benchmark numbers land in `result.yaml` beside everyone else's.

Nothing was converted. `pytest tests/` and `./cpp/test_geometry` still work exactly as before.

## Guessing, and writing the guess down

A runner finds its own entries the way its ecosystem does — pytest's collection rules, the
`test_*.cpp` under a directory, cargo's targets. That is a guess about your layout, so it is a guess
you write down.

With no `errand-*.py` at all, `errand` reads the directory and **tells you what it guessed**
before running anything:

```text
  no errand-*.py; guessed:  pytest (tests/)  ·  catch2 (cpp/)  ·  cargo (rust/)   ( errand init writes it down )
```

A guess is a configured runner put in place of a default one — `Pytest( dirs = [ "tests" ] )`
rather than every `test_*.py` anywhere, `Catch2` with the `make -C cpp` that builds it.
Convenient for a first look, never silent, and the cure is to write the line — which is what
`errand init` does, with `runs/` made beside it, and an `errand-envs.py` for the environments. The rules it follows are in
[Start from what you have](./start#what-it-looks-for). Every framework
locates its tests by assuming something about your layout, so there is no version of this that does
not guess. What `errand-project.py` changes is that the assumption is **visible, versioned, and
arguable**: `Pytest( dirs = [ "tests" ] )` says exactly what will be looked at, and takes arguments
to say something else.

## errand compiles nothing itself

A runner that needs a build runs the command you already build with, **once, before any of its
entries** — not once per file, and not once per parallel process, which under `-j` would have
several of them writing the same binary at the same time:

```python
# errand-project.py
errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )
# or
errand.runners.replace( errand.Catch2( dir = "cpp", build = "cmake --build build", binary = "build/{stem}" ) )
```

`binary` says where a source's executable lands, `{stem}` being the source's name; it defaults to
beside the source, without its extension. Leave `build` out if something else already built them.

Your compiler, your flags and your layout stay yours. Nothing about your build is errand's business,
and asking it to know would be asking it to have opinions it has no way to hold.

`cargo` needs none of this: `cargo test` builds what it runs, and `cargo metadata` lists the targets
without building anything at all.

## A missing tool is installed when the environment is errand's

A `Pytest` runner whose interpreter has no pytest installs it — into a venv, a micromamba
environment, a container — and says so.

Into the **system** interpreter it declines and tells you what to run: that one is shared with
everything else on the machine, and it is not errand's to change. `install = False` turns the
behaviour off entirely.

## Why the three suites behave differently

| runner | granularity | because |
|---|---|---|
| `Pytest` | one entry per test | it asks pytest for its own tests rather than reimplementing its collection rules — that is how a runner starts quietly disagreeing with the tool it wraps. Nothing is built, so collecting is cheap |
| `Catch2` | one entry per test case | built during the [preparation](./environments#preparing-then-running), in the place it runs, then asked for its own cases — the binary knows them and nothing else does. A build that fails costs its files' rows |
| `Cargo` | one entry per test target | `cargo metadata` knows the targets without compiling any of them; a `::name` goes to `cargo test` after `--` |

Full arguments in the [runner reference](/reference/runners).

## Scripts and executables

A python script, a shell script or an executable is one entry: the whole file, run in the place —
the environment's interpreter, through its layers, on its machine. Its output is the run's output,
its exit code its status, and `ERRAND_OUT_DIR` the directory anything else it writes should go to,
so that it lands beside `result.yaml`.

## Writing one for something else

`suitability` / `collect` / `run`, plus an optional `prepare` for the build — see the
[reference](/reference/runners#writing-one). Still to ship: GoogleTest, doctest, ctest, JavaScript.

## Next

The [tutorial that adopts three suites at once](/tutorials/adopt-a-suite).
