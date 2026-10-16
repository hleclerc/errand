# Runners: other languages, and suites you already have

errand does not care what your tests are written in. An entry does not have to be a Python call
site, and most of what you run will not be. What runs a file is a **runner**, and the ones that
come with errand already know errand's own files, pytest, Catch2, cargo, python scripts, and
executables and commands — with a record, summaries, environment matrices and remote repatriation
for all of them, none of which they had before:

```bash
errand run '**::*'                      # every suite found under here
errand run "tests/test_api.py::*"       # the tests of that file
errand run cpp/test_geometry.cpp::area  # one Catch2 case, by name
errand run -e '!slow' '**::*'           # pytest marks are entry tags
errand run --env local,old '**::*'      # every suite, both python versions
errand run scripts/plot.py              # a script, recorded like the rest
```

## Which runner takes a file

**The command line says which kind of runner, never the directory.** A target with `::` goes to an
**entry runner** — `Errand`, `Pytest`, `Catch2`, `Cargo` — which lists what is in a file. A target
without one goes to a **file runner**: `Python` for a `.py`, run by the place's interpreter, and
`Executable` for anything else — a file of the project, or a command on the place's `PATH`. A
`.sh` is an executable like any other: it needs its execute bit and a shebang.

Between entry runners, each says how well it fits a file, on one scale:

| level | what it means | the runners that come with errand |
|---|---|---|
| `ERRAND` | a file declaring errand's own entries | `Errand`: a `.py` that imports errand |
| `FRAMEWORK` | a suite of a framework errand adopts | `Pytest`, `Catch2`, `Cargo` |

**The best fit wins, and the order never decides.** A `test_*.py` that imports errand is errand's,
not pytest's. Two runners at the same, highest level is an **error** that names them — never a coin
toss settled by which was added first — and `-r NAME` settles it for one command. With `::`, a file
no entry runner takes is skipped silently: a glob there is a filter. `errand list` says which runner
took each entry.

**One entry or several is the runner's to say**, since only it knows whether its ecosystem can list
what is in a file without running it: pytest and cargo can, a script cannot, and a compiled suite
can once it is built — which is why it is built during the preparation, where it runs. A file run
as a whole is one case, `runs/scripts/plot.py/` [with `-o`](./output), with no level named after it
a second time. A `::name` on it is handed to the file as its own filter when its runner takes one
(Catch2, cargo), and refused otherwise.

## The list is yours

`errand.runners` is a dict, name → runner, filled with the runners above under their own names
(`errand`, `pytest`, `catch2`, `cargo`, `python`, `executable`). A project edits it in
[`errand-project.py`](./configuration):

```python
# errand-project.py
import errand

errand.runners.replace( errand.Pytest( dirs = [ "tests" ] ) )            # in place of the default one
errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )
errand.runners[ "mine" ] = Mine( )                                        # one of your own
errand.runners[ "bench" ] = errand.Pytest( dirs = [ "bench" ], args = [ "-x" ] )   # -r bench picks it
del errand.runners[ "cargo" ]
```

`replace` puts a configured runner where the default one of its kind was. A second instance under
another name sits *beside* it: where both take a file they tie, and errand says so — which is what
`-r NAME` is for, two instances over the same files with different settings.

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

`errand run` never guesses: the built-in runners are active as they are, and nothing about the
directory changes what a command means. **`errand init`** reads the directory and writes what it
recognized into `errand-project.py`, **in comments** — a configured runner in place of a default
one, `Pytest( dirs = [ "tests" ] )` rather than every `test_*.py` anywhere, `Catch2` with the
`make -C cpp` that builds it — with a `default_run` to start from, and an `errand-envs.py` for the
environments. Uncomment what fits. The rules it follows are in
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

A python script, an executable or a command is one entry: the whole file, run in the place — the
environment's interpreter, through its layers, on its machine. Its output is the run's output, its
exit code its status (77 is a skip). With `-o` or `--out`, `ERRAND_OUT_DIR` is the directory
anything else it writes should go to, so that it lands beside `result.yaml`; without, it is not
set.

## Writing one for something else

`suitability` / `collect` / `run`, plus an optional `prepare` for the build, registered with
`errand.runners[ "name" ] = …` — see the
[reference](/reference/runners#writing-one). Still to ship: GoogleTest, doctest, ctest, JavaScript.

## Next

The [tutorial that adopts three suites at once](/tutorials/adopt-a-suite).
