# Adopting a suite

A pytest suite, a Catch2 suite and a cargo one, none of them modified, put under errand by three
lines of `errand-project.py`. The project is
[`examples/02-existing-suite`](https://github.com/hleclerc/errand/tree/main/examples/02-existing-suite):

```bash
cd examples/02-existing-suite
```

```
errand-project.py        three runners, and nothing else
tests/test_api.py        ordinary pytest, still runs under `pytest`
cpp/test_geometry.cpp    ordinary Catch2, still runs on its own
cpp/Makefile             whatever you already build with
rust/                    ordinary cargo
```

It declares no environment, on purpose: declaring one would have running it build a micromamba
environment on your machine. Environments are [the first tutorial](/tutorials/environments).

## The three lines

```python
# errand-project.py
import errand

errand.configure( src = [ "src" ] )

errand.runners.replace( errand.Pytest( dirs = [ "tests" ] ) )
errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )
errand.runners.replace( errand.Cargo( manifest = "rust/Cargo.toml" ) )
```

pytest, Catch2 and cargo are runners already, active with no configuration. These lines only say
where to look and how to build. Not a line of the tests changes.

## Running it

```bash
errand run '**::*'                        # all three suites
errand run "tests/test_api.py::*"         # the python ones
errand run cpp/test_geometry.cpp::area    # one Catch2 case, by name
errand run 'tests/**::*' -m "not slow"    # pytest's own filter, after the target
errand run pytest tests/                  # the pytest command itself, recorded as one run
errand list '**::*'                       # what is there, and which runner took it
```

The `::` is what sends a target to the suites' runners; without it, `pytest` is just a command. To
make a bare `errand run` mean all three, add to `errand-project.py`:

```python
errand.default_run = [ "**::*" ]
```

With environments declared, the same targets run in several of them at once:
`errand run --grid=, --env local,old '**::*'`.

## Numbers from a Catch2 benchmark

`cpp/test_geometry.cpp` holds a Catch2 benchmark. It measured something, and the measurement went to
the terminal and was lost. Under errand it lands in `result.yaml`, per machine and per date:

```bash
errand run 'cpp/test_geometry.cpp::area is cheap'
cat errand-outputs/runs/cpp/test_geometry.cpp/area_is_cheap/latest/result.yaml   # area_ns: …
```

## Letting errand write the lines

Move the file aside and have errand suggest one from the bare directory:

```bash
mv errand-project.py errand-project.bak
errand init      # errand-project.py again, the runner lines in comments, and an errand-envs.py
```

What it found is written **in comments**, with a `default_run` to start from: nothing is active
until you uncomment it. The `errand.configure( src = … )` line is not in it: where your package
lives is not something a directory can tell, so it is yours to add.

## Building, and finding the binary

errand compiles nothing itself. It runs the command you already build with, once, and then expects
the binaries where you say they land:

```python
errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )
# or
errand.runners.replace( errand.Catch2( dir = "cpp", build = "cmake --build build", binary = "build/{stem}" ) )
```

`build` runs once, during the preparation, in the place the binaries run. `binary` defaults to the source
without its extension, which is where the Makefile here puts it. cargo needs neither: the runner
compiles with `cargo test --no-run` during the preparation.

## What to notice

- **A file is one run of its tool.** pytest gets the file and the `::name` as a node id, the Catch2
  binary gets it as a test spec, and errand reads their reports back: counts, failed names.
- **Filters are the tools' own.** `-m "not slow"` for pytest, `::~[slow]` for Catch2.
- **A missing pytest is installed when the environment is errand's.** Into a venv, a micromamba
  environment or a container, errand installs it and says so. Into the system interpreter it
  declines and tells you what to run.
- **Nothing was converted.** `pytest tests/` and `./cpp/test_geometry` still work as before.

Each runner has its page: [Pytest](./pytest), [Catch2](./catch2), [Cargo](./cargo).
