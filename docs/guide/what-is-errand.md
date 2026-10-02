# What errand is

> **Run a piece of work — here, in that environment, in that container, on that machine — and bring
> back everything it produced, into a path you can predict.**

An *errand* is a trip you take on someone's behalf and come home from with the things. That is the
whole model. You declare a piece of work next to the code it exercises; `errand` works out where to
run it, makes sure that place is ready, runs it — in several places at once if you ask — and
repatriates what it produced.

## The three legs

It stands on three, and you want all three.

### Where and how it runs

An environment is a stack of layers: micromamba, conda, uv, a venv, Nix or Guix, `module load`, a
Docker, Podman or Apptainer container, another machine over ssh, a Slurm or OAR allocation — in any
combination. `errand` declares them, *builds* them from what they say they need, checks before
every run that they still match what was declared, and runs the same work across a matrix of them
in one go. Anything can be launched and left to finish on its own.

→ [Environments](./environments), [Keeping them current](./upkeep), [Tags](./tags)

### Sharing the machine

Work says what it needs — a core, eight of them, a GPU, the whole machine — and `errand` holds a
queue per host so that two invocations, in two terminals, on two projects, do not trample each
other. A timing taken while something else was running is not a timing.

→ [Sharing the machine](./machine)

### What comes back

Every run gets an output directory whose path is computed, not invented — from the work, its
parameters, its environment and its date. Numbers, files, logs and status land there, and comparison
between dates, machines and parameter sets falls out of the directory tree.

→ [Where the output goes](./output)

## What it is not

**It is not a build system.** errand compiles nothing itself. A provider that needs a build runs the
command you already build with, once, before any of its entries. Your compiler, your flags and your
layout stay yours.

**It is not a replacement for your test runner.** A `provider` line puts your existing pytest,
Catch2 or cargo suite under errand without touching it. `pytest tests/` still works exactly as
before; what the suite gains is everything that happens *around* the run.

**It is not a scheduler.** Inside a Slurm, PBS, OAR or LSF allocation it does not queue at all —
the scheduler has already decided what this process may have, and a second queue on top of it would
only wait for itself.

**It does not decide what may be compared to what.** A matrix that spans a laptop and a cluster
partition at once will produce numbers that are not comparable, and `errand` will not stop you. It
runs what you ask where you ask and records where each number came from; the judgement is yours.

## The shape of a project

Nothing is required. `errand` with no configuration at all finds your entries and runs them in the
interpreter you started it with:

```
primes.py              the code; knows nothing about errand
test_primes.py         the work: a couple of tests, a benchmark, an experiment
```

Once you want to say *where* things run, one file at the root says it:

```
errandfile.py          environments, providers, project settings
errand.local.py        what only this machine can supply — untracked
runs/                  the output tree, which errand writes and you read
```

→ [Configuration](./configuration)

## Next

[Installing](./installing) · [Declaring work](./declaring-work) · or jump straight into
[Your first entry](/tutorials/first-entry).
