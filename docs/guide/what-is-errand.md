# What errand is

> **Run a piece of work — here, in that environment, in that container, on that machine — and bring
> back everything it produced, into a path you can predict.**

An *errand* is a trip you take on someone's behalf and come home from with the things. That is the
whole model. You say what to run and where it may run; `errand` makes sure that place is ready, goes
in — through ssh, through a Slurm allocation, through a container, whatever the way is — runs it,
in several places at once if you ask, and repatriates what it produced.

What you run is **yours**. A pytest suite, a Catch2 binary, a cargo project, a Makefile target, a
script: `errand` starts it, and does not need to know what language it is in.

## The three legs

It stands on three, and you want all three.

### Where and how it runs

This is the part that is hard to do by hand and tedious to do twice. An environment is a **stack of
layers**: micromamba, conda, uv, a venv, Nix or Guix, `module load`, a Docker, Podman or Apptainer
container, another machine over ssh, a Slurm or OAR allocation — in any combination. Read it
outside in: *that machine, an allocation on it, a container, your command.*

<Term scene="stack" caption="errand train --env cluster: three layers, declared once, crossed by one flag." />

The shell script that does `ssh`, then `sbatch`, then `apptainer exec`, then rsyncs the results
back — and that nobody else can run — is replaced by three lines in a file. `errand` *builds* each
layer from what it says it needs, checks before every run that it still matches what was declared,
and runs the same work across a matrix of them in one go. Anything can be launched and left to
finish on its own.

→ [Environments](./environments), [Keeping them current](./upkeep), [Tags](./tags),
[Running elsewhere](./remote)

### Sharing the machine

Work says what it needs — a core, eight of them, a GPU, the whole machine — and `errand` holds a
queue per host so that two invocations, in two terminals, on two projects, do not trample each
other. A timing taken while something else was running is not a timing.

→ [Sharing the machine](./machine)

### What comes back

Every run gets an output directory whose path is computed, not invented — from the work, its
parameters, its environment and its date. Logs, files, status and any numbers worth following land
there, and comparison between dates, machines and parameter sets falls out of the directory tree.

→ [Where the output goes](./output)

## Your tools, as they are

`errand` runs what you already have. With no configuration it looks at the directory and says what
it found; `errand --init` writes that down as an `errand-project.py`.

| you have | errand uses |
|---|---|
| a `tests/` directory of pytest | `Pytest( )`: one entry per test, marks become entry tags |
| `test_*.cpp` using Catch2 | `Catch2( )`: one entry per file, built once with the command you build with |
| a `Cargo.toml` | `Cargo( )`: one entry per test target |
| anything else | `errand --env X -- <command>`, or an [entry](./declaring-work) that calls it |

→ [Start from what you have](./start), [Other languages](./providers)

## Optionally: errand's own entries

For work that has no framework of its own — a number to follow, a picture to look at, a step to run
on the cluster — errand has a small declaration that sits beside the code, `if track( "cost" ):`.
It is one more way to give errand something to run, **not** the way in: everything above works
without it, and a project can use both.

→ [Writing entries](./declaring-work)

## What it is not

**It is not a build system.** errand compiles nothing itself. A provider that needs a build runs the
command you already build with, once, before any of its entries. Your compiler, your flags and your
layout stay yours.

**It is not a replacement for your test runner.** `pytest tests/` still works exactly as before;
what the suite gains is everything that happens *around* the run.

**It is not a scheduler.** Inside a Slurm, PBS, OAR or LSF allocation it does not queue at all —
the scheduler has already decided what this process may have, and a second queue on top of it would
only wait for itself. Outside one, `Slurm` is a layer that *submits* to the scheduler for you.

**It does not decide what may be compared to what.** A matrix that spans a laptop and a cluster
partition at once will produce numbers that are not comparable, and `errand` will not stop you. It
runs what you ask where you ask and records where each number came from; the judgement is yours.

## The shape of a project

Nothing is required. `errand` with no configuration at all reads the directory, runs what it
finds in the interpreter you started it with, and says what it guessed:

```
tests/test_api.py      the work: a pytest suite, untouched
src/…                  the code
```

Once you want to say *where* things run, files at the root say it — errand reads every `errand-*.py`:

```
errand-project.py      providers, project settings                  ← errand --init
errand-envs.py         environments, and what only this machine can supply — untracked
runs/                  the output tree, which errand writes and you read
```

→ [Configuration](./configuration)

## Next

[Installing](./installing) · [Start from what you have](./start) · or look at the layers at work in
[Four environments](/tutorials/environments).
