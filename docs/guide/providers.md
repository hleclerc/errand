# Other languages, and suites you already have

An entry does not have to be a Python call site. Providers for C++ (Catch2), Rust (`cargo test`) and
pytest come with `errand`, and one line in [`errandfile.py`](./configuration) puts an existing suite
under it — with an output directory, summaries, environment matrices and remote repatriation, none
of which it had before:

```python
from errand import provider, Pytest, Catch2, Cargo

provider( Pytest( ) )
provider( Catch2( dir = "tests/cpp" ) )
provider( Cargo( ) )
```

```bash
errand                               # all three suites
errand test_api                      # the python ones
errand test_geometry::area           # one Catch2 case, by name
errand -e '!slow'                    # pytest marks are entry tags
errand --env local,old               # every suite, both python versions
```

## What adopting them buys

Each suite keeps its own runner, its own assertions and its own idea of what a test is. What it
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

A provider finds its own entries the way its ecosystem does — pytest's collection rules, the
`test_*.cpp` under a directory, cargo's targets. That is a guess about your layout, so it is a guess
you write down.

With no `errandfile.py` at all, `errand` guesses on its own and **tells you what it guessed** before
running anything:

```text
  no errandfile.py; guessed:  pytest (tests/)  ·  catch2 (cpp/)  ·  cargo (rust/)
```

Convenient for a first look, never silent, and the cure is to write the line. Every framework
locates its tests by assuming something about your layout, so there is no version of this that does
not guess. What `errandfile.py` changes is that the assumption is **visible, versioned, and
arguable**: `Pytest( dirs = [ "tests" ] )` says exactly what will be looked at, and takes arguments
to say something else.

## errand compiles nothing itself

A provider that needs a build runs the command you already build with, **once, before any of its
entries** — not once per file, and not once per parallel process, which under `-j` would have
several of them writing the same binary at the same time:

```python
provider( Catch2( dir = "cpp", build = "make -C cpp" ) )
provider( Catch2( dir = "cpp", build = "cmake --build build", binary = "build/{stem}" ) )
```

`binary` says where a source's executable lands, `{stem}` being the source's name; it defaults to
`<dir>/<stem>`. Leave `build` out if something else already built them.

Your compiler, your flags and your layout stay yours. Nothing about your build is errand's business,
and asking it to know would be asking it to have opinions it has no way to hold.

`cargo` needs none of this: `cargo test` builds what it runs, and `cargo metadata` lists the targets
without building anything at all.

## A missing tool is installed when the environment is errand's

A `Pytest` provider whose interpreter has no pytest installs it — into a venv, a micromamba
environment, a container — and says so.

Into the **system** interpreter it declines and tells you what to run: that one is shared with
everything else on the machine, and it is not errand's to change. `install = False` turns the
behaviour off entirely.

## Why the three behave differently

| provider | granularity | because |
|---|---|---|
| `Pytest` | one entry per test | it asks pytest for its own tests rather than reimplementing its collection rules — that is how a runner starts quietly disagreeing with the tool it wraps. Nothing is built, so collecting is cheap enough to do on the side that predicts the paths |
| `Catch2` | one entry per **file** | the cases of a compiled suite cannot be enumerated without building it, and collection has to work before anything is built. A `::name` in the pattern goes to the binary as its own filter, so naming one case still reaches one case |
| `Cargo` | one entry per test target | `cargo metadata` knows the targets without compiling any of them |

The per-file granularity of `Catch2` has a second reason: the list of entries has to be known on
*this* side of an [ssh hop](./remote), before anything is compiled, so that the paths to rsync back
can be computed in advance.

Full arguments in the [provider reference](/reference/providers).

## Writing one for something else

A three-method protocol — `files` / `collect` / `run`, plus an optional `prepare` for the build.
Still to ship: GoogleTest, doctest, ctest, JavaScript.

## Next

The [tutorial that adopts three suites at once](/tutorials/adopt-a-suite).
