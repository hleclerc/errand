# 3 · Adopt an existing suite

A pytest suite, a Catch2 suite and a cargo one, none of them modified. Three lines in
`errandfile.py` put all three under `errand`.

```bash
cd examples/03-existing-suite
```

```
errandfile.py            three providers, and nothing else
tests/test_api.py        ordinary pytest, still runs under `pytest`
cpp/test_geometry.cpp    ordinary Catch2, still runs on its own
cpp/Makefile             whatever you already build with
rust/                    ordinary cargo
```

There are no environments here on purpose: this example is about adopting suites, and declaring one
would have running it build a micromamba environment on your machine. Environments are
[tutorial 2](./environments).

## The three lines

```python
# errandfile.py
from errand import configure, provider, Pytest, Catch2, Cargo

configure( src = [ "src" ] )

provider( Pytest( dirs = [ "tests" ] ) )
provider( Catch2( dir = "cpp", build = "make -C cpp" ) )
provider( Cargo( manifest = "rust/Cargo.toml" ) )
```

That is the whole adoption. Nothing below it changes a single line of the existing tests.

## Try it

```bash
errand                               # all three suites
errand test_api                      # the python ones
errand test_geometry::area           # one Catch2 case, by name
errand -e '!slow'                    # pytest marks are entry tags
errand --env local,old               # every suite, both python versions
```

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
errand --batch -k bench --env local -e '!legacy'
errand --watch
```

and the numbers accumulate per machine and per date, next to the Python ones, in the same tree.

## Guessing, and writing the guess down

Run `errand` in a project with no `errandfile.py` at all and it will find these suites by itself —
and say so before running anything:

```text
  no errandfile.py; guessed:  pytest (tests/)  ·  catch2 (cpp/)  ·  cargo (rust/)   ( errand --init writes it down )
```

Every framework locates its tests by assuming something about your layout, so there is no version of
this that does not guess. What `errandfile.py` changes is that the assumption is **visible,
versioned, and arguable** — `Pytest( dirs = [ "tests" ] )` says exactly what will be looked at, and
takes arguments to say something else.

Try it. Move the file aside, look at what errand makes of the bare directory, then have it write the
file back:

```bash
mv errandfile.py errandfile.bak
errand -h                  # the guess, announced; nothing run
errand --init              # errandfile.py again, from what was found
```

The `configure( src = … )` line is not in what `--init` writes — it is not a thing a directory can
tell: it is yours to add.

## Compiling, and finding the binary

errand compiles nothing itself. It runs the command you already build with, once, and then expects
the binaries where you say they land:

```python
provider( Catch2( dir = "cpp", build = "make -C cpp" ) )
provider( Catch2( dir = "cpp", build = "cmake --build build", binary = "build/{stem}" ) )
```

`build` runs **once before any entry of that provider** — not once per file, and not once per
parallel process, which under `-j` would have several of them writing the same binary at the same
time. `binary` says where a source's executable ends up, `{stem}` being the source's name; it
defaults to `<dir>/<stem>`, which is where the Makefile here puts it. Leave `build` out entirely if
something else already built them.

Nothing about your build is errand's business. It does not know your compiler, your flags or your
layout, and asking it to would be asking it to have opinions it has no way to hold.

`cargo` needs none of this: `cargo test` builds what it runs, and `cargo metadata` lists the targets
without building anything at all.

## What to notice

- **The C++ provider is one entry per file, not per test case.** The list of entries has to be known
  on *this* side of an ssh hop, before anything is compiled, so that the paths to rsync back can be
  computed in advance. A `::name` in the pattern is passed through to the binary as its own filter,
  so `test_geometry::area` still reaches one case.
- **pytest marks become entry tags.** `-e '!slow'` filters them, with the same
  [expression language](/reference/expressions) that `-t` uses on environments.
- **A missing tool is installed when the environment is errand's to install into.** A `Pytest`
  provider whose interpreter has no pytest installs it — into a venv, a micromamba environment, a
  container — and says so. Into the *system* interpreter it declines and tells you what to run.
- **Nothing was converted.** `pytest tests/` and `./cpp/test_geometry` still work exactly as before.
  A provider runs the suite you already have; it does not replace it.

## Next

[4 · A bench over two machines](./two-machines).
