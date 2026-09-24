# 03 — a project that already has a suite

A pytest suite, a Catch2 suite and a cargo one, none of them modified. Three lines in `errandfile.py`
put all three under `errand`.

```
errandfile.py                  three providers, two environments
tests/test_api.py          ordinary pytest, still runs under `pytest`
cpp/test_geometry.cpp      ordinary Catch2, still runs on its own
rust/                      ordinary cargo
```

## Try it

```bash
cd examples/03-existing-suite

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
errand --batch -k bench --env local --env-tags '!legacy'
errand --watch
```

and the numbers accumulate per machine and per date, next to the Python ones, in the same tree.

## Guessing, and writing the guess down

Run `errand` in a project with no `errandfile.py` at all and it will find these suites by itself — and
say so before running anything:

```
  no errandfile.py; guessed:  pytest (tests/)  ·  catch2 (cpp/)  ·  cargo (rust/)
  write them down to stop guessing:  errand --write-config
```

Every framework locates its tests by assuming something about your layout, so there is no version of
this that does not guess. What `errandfile.py` changes is that the assumption is visible, versioned, and
arguable — `Pytest( dirs = [ "tests" ] )` says exactly what will be looked at, and takes arguments
to say something else.

## Notice

- **The C++ provider is one entry per file, not per test case.** The list of entries has to be known
  on *this* side of an ssh hop, before anything is compiled, so that the paths to rsync back can be
  computed in advance. A `::name` in the pattern is passed through to the binary as its own filter,
  so `test_geometry::area` still reaches one case.
- **pytest marks become entry tags.** `-e '!slow'` filters them, with the same expression language
  that `-t` uses on environments.
- **Nothing was converted.** `pytest tests/` and `./cpp/test_geometry` still work exactly as before.
  A provider runs the suite you already have; it does not replace it.
