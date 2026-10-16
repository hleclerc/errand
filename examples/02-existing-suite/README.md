# 03 — a project that already has a suite

A pytest suite, a Catch2 suite and a cargo one, none of them modified. pytest, Catch2 and cargo are
runners already; three lines in `errand-project.py` say where each one looks and how to build.

```
errand-project.py        three runners, and nothing else
tests/test_api.py        ordinary pytest, still runs under `pytest`
cpp/test_geometry.cpp    ordinary Catch2, still runs on its own
cpp/Makefile             whatever you already build with
rust/                    ordinary cargo
```

There are no environments here on purpose: this example is about adopting suites, and declaring one
would have running it build a micromamba environment on your machine. Environments are
[example 02](../01-environments/).

## Try it

```bash
cd examples/02-existing-suite

errand run '**::*'                      # all three suites
errand run "tests/test_api.py::*"       # the python ones
errand run cpp/test_geometry.cpp::area  # one Catch2 case, by name
errand run -e '!slow' '**::*'           # pytest marks are entry tags
errand run --env local,old '**::*'      # every suite, both python versions
errand run pytest tests/                # the pytest command itself, in the place, recorded
```

The `::` is what sends a target to the suites' runners; without it, `pytest` is just a command.

## What adopting them buys

Each suite keeps its own runner, its own assertions and its own idea of what a test is. What it
gains is everything that happens around the run:

| | before | after |
|---|---|---|
| where it runs | wherever you typed it | any declared environment, several at once |
| output | scrollback | a directory per run, per place, per date |
| numbers | printed | `result.yaml`, summarized across dates and machines |
| on another machine | copy, ssh, remember to fetch | one flag, results rsynced back |

The Catch2 benchmark in `cpp/test_geometry.cpp` is the clearest case: it already measured something,
and the measurement went to the terminal and died there. Now:

```bash
errand run --batch -k bench --env local -e '!legacy' '**::*'
errand watch
```

and the numbers accumulate per machine and per date, next to the Python ones, in the same tree.

## Guessing, and writing the guess down

`errand run` never guesses: with no `errand-*.py` at all, the built-in runners take these suites as
they are — pytest's files anywhere, Catch2 sources with no build to run first. `errand init` reads
the directory and writes what would fit into `errand-project.py`, **in comments**, with a
`default_run` to start from; nothing is active until you uncomment it.

Every framework locates its tests by assuming something about your layout, so there is no version of
this that does not guess. What `errand-project.py` changes is that the assumption is visible, versioned, and
arguable — `Pytest( dirs = [ "tests" ] )` says exactly what will be looked at, and takes arguments
to say something else.

## Compiling, and finding the binary

errand compiles nothing itself. It runs the command you already build with, once, and then expects
the binaries where you say they land:

```python
import errand
errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )
errand.runners.replace( errand.Catch2( dir = "cpp", build = "cmake --build build", binary = "build/{stem}" ) )
```

`build` runs **once before any entry of that runner** — not once per file, and not once per
parallel process, which under `-j` would have several of them writing the same binary at the same
time. `binary` says where a source's executable ends up, `{stem}` being the source's name; it
defaults to `<dir>/<stem>`, which is where the Makefile here puts it. Leave `build` out entirely if
something else already built them.

Nothing about your build is errand's business. It does not know your compiler, your flags or your
layout, and asking it to would be asking it to have opinions it has no way to hold.

`cargo` needs none of this: `cargo test` builds what it runs, and `cargo metadata` lists the targets
without building anything at all.

## Notice

- **The C++ runner is one entry per test case, after a build.** The build runs during the
  preparation, where the cases will run, and the binary is then asked for its own cases.
- **pytest marks become entry tags.** `-e '!slow'` filters them, with the same expression language
  that `-t` uses on environments.
- **Nothing was converted.** `pytest tests/` and `./cpp/test_geometry` still work exactly as before.
  A runner runs the suite you already have; it does not replace it.
