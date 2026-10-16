---
status: accepted
date: 2026-10-16
---

# `run` launches everything, the output directory is asked for, entries become a protocol

errand turned out to be, before anything else, a way to run commands of all kinds in environments of
all kinds — built, installed into and kept current from what they declare, with files synced there
and back. The documentation sold three equal legs and opened on errand's own `entry` / `test` /
`bench` declarations, which most people will never write: they have pytest, a script, cmake. And
the command line had two ways to launch (`run` records, `shell -- cmd` does not), guessed which
runner took a file from its contents and the project's layout, and created a visible output
directory for every run whether anybody wanted one or not. This revises
[ADR 0001](./0001-verbs-path-targets-runners.md) on those points.

## Positioning

The hook is the environments: *errand runs your work in any environment — a conda or uv env, a
container, another machine over ssh, a Slurm allocation, any stack of them — building and updating
it from what it declares, and syncing your files there and back.* The queue, `--batch` and the
output tree are what you get on top, not legs of equal weight. errand's own entries are one way to
give it work, documented below everything else.

## One verb launches

`run` launches everything; `shell` is only the interactive shell of an environment (`shell -- cmd`
goes, there is no compatibility to keep). `run` takes over `shell`'s options: `-x`, `--cpus`,
`--ram`, `--gpus`, `-l`, `-n`, `-q`, `--pull`. Every `run` takes a claim in the queue, shared by
default.

What the first word after errand's options means is read **from the command line alone**:

- `x::y` (globs allowed on both sides) goes to an **entry runner**: pytest, Catch2, cargo, errand's
  own entries. Which one claims a file is decided by its contents, as `suitability` did; a tie is
  an error naming the contenders. The built-in entry runners are active with no configuration.
  `-r NAME` picks an instance and bypasses the claim — two instances over the same files, with
  different settings, is the reason it exists. With `::`, a file no entry runner claims is skipped
  silently: a glob there is a filter.
- anything else goes to a **file runner**: a `.py` is run by the environment's Python, anything
  else is executed as it is, resolved in the environment (`./bench`, `make`, `cmake`, `pytest`).
  `errand run pytest tests/` is the pytest command, not the pytest runner. A glob without `::` runs
  each matching file, one run each.

A runner prefix (`pytest:x.py`) was considered and rejected: a single `:` is kept free for a
possible `place:target` later. `--` is not needed and not documented, beyond being an escape.

`errand.runners` is a dict, name → instance; the built-in names are instances a project can replace
or remove. An instance's options (`exclusive`, `cpus`, `out`, …) are where the settings that used to
live on entries go. `errand run` alone runs `errand.default_run`, a list of targets the project
declares; with none it prints the help and the named runners.

## The grid

errand grids **places**: environments and tags (a comma is forbidden in an environment name and a
tag value), and several targets in the target word (`a.py,b.py`). The arguments of a target are its
runner's business: a runner may read a comma as an axis (errand's `Param`, a runner that knows
`-n` is a number), a plain command never has its words rewritten. This narrows ADR 0001's "a comma
is a grid everywhere", whose cost (`-Wl,-rpath`, `python -c "f(1,2)"`) fell on exactly the commands
errand now puts first.

## What is written

**Always**, a light private record — command, environment, place, date, status, duration, output,
results — which history, the screen, `status`, `watch` and `--batch` read. It lives in the state
directory, `.errand/` by default, set by `errand.configure( state = … )` and overridable per machine
by `ERRAND_STATE_DIR`.

**On request**, a visible output directory: `-o` / `--out [PATTERN]`, the computed path of ADR 0001
by default — `runs/{path}/{name}/{when}-{place}[-{params}]/`, and for a plain command
`runs/{first word}/{when}-{place}[-{args}]/` — exported as `ERRAND_OUT_DIR` and brought back. A
runner instance may turn it on for its entries. Creating a directory nobody asked for was wrong.

The guess of the directory (`detect.py`) leaves `run`: `errand init` writes a starting
`errand-envs.py` and suggests runner lines, in comments, for what it recognizes.

## Entries become a protocol (step 2)

Decided here, implemented after the above.

- **Results**: `ERRAND_RESULTS` is always exported, a file in the private record; any program
  writes flat `key: value` lines to it, merged under `results:`. pytest and Catch2 runners
  translate their own measures into it; `p.results[ … ]` is one more way to write it.
- **Needs** per entry: in the framework's own vocabulary (a pytest mark, a Catch2 tag, an argument
  of `entry`), and in the runner instance by entry pattern; the configuration wins.
- **Skip**: exit code 77 where there is no native skip; native skips are translated.
- **Traits**: `bulk` becomes `default_run`, `exclusive` a need, `keep` goes (every recorded result
  is comparable), `stable_path` comes with `-o` (`latest/`). `-k` goes: filter by `-r`, by target,
  or by entry tags (`-e`).
- **The Python API** keeps `entry`, `Param`, `need`, `skip`; `test`, `bench`, `track`,
  `experiment` become plain aliases of needs. Whether it stays in errand is decided after use.
