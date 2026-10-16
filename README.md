# errand

> **errand runs your work in any environment — a conda or uv env, a container, another machine
> over ssh, a Slurm allocation, any stack of them — building and updating it from what it
> declares, and syncing your files there and back.**

An *errand* is a trip made on someone's behalf: go there, do the thing, come back with what it
produced.

```python
# errand-envs.py
import errand

errand.envs[ "local" ]   = errand.Env( [ errand.Micromamba( "proj", python = "3.13", requirements = "requirements.txt" ) ] )
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "~/proj" ),
                                         errand.Slurm( gpus = 1, time = "2:00:00" ),
                                         errand.Apptainer( image = "cuda.sif", recipe = "cuda.def" ) ] )
```

```bash
errand run --env local pytest                       # created and installed on first use
errand run --env cluster python train.py --lr 1e-3  # rsync, srun, apptainer, and back
errand run --env cluster --pull out make results    # ...and out/ comes back here
errand run --env local,cluster ./bench              # in both places, one after the other
errand shell --env cluster                          # be let in, to look around
```

The site has everything, split by theme, with tutorials: **<https://hleclerc.github.io/errand/>**
(built from [`docs/`](docs/)).

## Installing

```bash
pip install errand-run
```

The *distribution* is `errand-run` — `errand` on PyPI is somebody else's project — but what you type
and what you import is `errand`. It has **no dependencies, and is not going to get any**: its job is
to build the environment the work runs in, so it has to run before any environment exists.

## Environments are stacks of layers

Read outside in: *that machine, an allocation on it, a container, your command.*

| layer | |
|---|---|
| `Micromamba`, `Conda`, `Uv`, `Venv` | an interpreter and its packages: `python =`, `requirements =`, `packages =`, `pip =` |
| `Nix`, `Guix`, `Module` | a flake or a manifest; `module load` the way a cluster picks a toolchain |
| `Apptainer`, `Docker`, `Podman` | a container, built from its `recipe` when it is missing or changed |
| `Ssh` | another machine: the project is rsynced there before, what was asked for comes back after |
| `Slurm`, `Oar`, `Pbs`, `Sge`, `Lsf` | an allocation, sized from what the work asks for |
| `Windows` | a Windows VM under QEMU that errand installs and boots — MSVC included |
| `Vars` | environment variables for the child |

**Kept current by themselves.** Before every run, errand compares what each layer declares — a
Python version, a `requirements.txt`, a container recipe, a pip list — with what it last built, and
brings it up to date when they have drifted. An environment that already exists the first time
errand sees it is adopted as it is, never rebuilt on somebody's first command.

```bash
errand envs              # what is declared, and in what state
errand setup --dry-run   # what bringing it up to date would run
```

**Files go there and come back.** Over `Ssh` the project is pushed with rsync before the command
runs; `--pull DIR` brings a directory back afterwards, and `also = [ "../lib" ]` pushes a sibling
checkout the work needs. Ask for an output directory with `-o` and it is made over there, handed to
the command as `$ERRAND_OUT_DIR`, and fetched back here.

**Several places at once.** A comma is several environments, and environments carry tags:

```bash
errand run --env local,cluster ./bench
errand run -t cuda ./bench             # every environment tagged cuda
errand run --fp 32,64 ./bench          # an environment that does not say fp covers both
```

## What you get on top

- **The machine to yourself when it matters.** errand keeps a queue per host, outside the process:
  `errand run -x ./bench` waits for what is running and holds everything else back; `--cpus 8`,
  `--gpus 1` take a share, and a card is assigned, not merely counted. Inside a Slurm allocation
  errand does not queue — the scheduler already decided.
- **Let it run.** `errand run --batch …` gives the shell back — a detached session here, a released
  ssh command there, an `sbatch` on a cluster — and `errand status` / `errand watch` say how it goes.
- **A record of every run**, in `.errand/`: what ran, where, when, how it ended, what it printed.
  With `-o`, a directory per run under `runs/`, whose path is computed from the work, the place and
  the date, so that two machines or two days sit side by side.
- **One screen for all of it**: `errand tui`, drawn with the standard library's curses.

## Files, suites and entries

What follows `errand run` is read from the command line alone, never guessed:

```bash
errand run train.py --lr 1e-3          # a .py: run by the python of the place
errand run ./bench                     # anything else: executed as it is
errand run make check                  # ...or a command of the place
errand run 'tests/**::*'               # x::y: the entries of a suite -- pytest, Catch2, cargo
errand run tests/test_api.py::test_ok  # one of them
errand run -r bench 'tests/**::*'      # through a runner of the project's own
```

`x::y` goes to the runner that recognises the file — pytest, Catch2, cargo, or errand's own entries
— which collects one entry per test, records each, and translates its vocabulary: a
`@pytest.mark.slow` is a tag that `-e '!slow'` filters on. A project names its own runner
instances in `errand-project.py`, and says what a bare `errand run` means:

```python
# errand-project.py
import errand

errand.runners[ "bench" ] = errand.Pytest( dirs = [ "tests/bench" ] )
errand.runners.replace( errand.Catch2( dir = "cpp", build = "cmake --build build" ) )
errand.default_run = [ "tests/**::*", "cpp/**::*" ]
```

errand also has entries of its own, for work that has no framework — `if test( "name" ):` next to
the code, with typed parameters and numbers to follow. See
[Writing entries](https://hleclerc.github.io/errand/guide/declaring-work).

## Configuration

None is needed: `errand run <command>` works in an empty directory. A project's `errand-*.py` files
sit at its root and are ordinary Python; `errand init` writes a first pair.

| | |
|---|---|
| `errand-project.py` | what the project does: runners, `default_run`, `errand.configure( … )`. Versioned |
| `errand-envs.py` | where it runs: the environments. Versioned when it names no machine |
| `errand-vars.py` | what only your machine knows — hosts, paths — read first, never versioned |

## Examples

In [`examples/`](examples/): [environments over three machines](examples/01-environments/),
[an existing pytest / Catch2 / cargo project](examples/02-existing-suite/), and [errand's own
entries](examples/03-entries/).

## Status

Everything above works and is covered by errand's own suite. Not released: the API may still move.
How errand's own entries are expressed — needs, numbers to follow, skips — is being reworked into a
protocol any program can follow ([ADR 0003](docs/adr/0003-run-launches-everything-output-on-request.md)).
