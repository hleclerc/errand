# What errand is

> **errand runs your work in any environment — a conda or uv env, a container, another machine
> over ssh, a Slurm allocation, any stack of them — building and updating it from what it
> declares, and syncing your files there and back.**

An *errand* is a trip made on someone's behalf: go there, do the thing, come back with what it
produced. You say what to run and where it may run; errand makes sure that place is ready, goes in
— through ssh, a Slurm allocation, a container, whatever the way is — runs it, in several places at
once if you ask, and brings back what you asked for.

What you run is **yours**: what follows `errand run` is what you would have typed — `make check`,
`python train.py`, `./bench`, `pytest`. errand does not need to know what language it is in.

## Environments, built and kept current

This is the part that is hard to do by hand and tedious to do twice. An environment is a **stack of
layers**: micromamba, conda, uv, a venv, Nix or Guix, `module load`, a Docker, Podman or Apptainer
container, another machine over ssh, a Slurm or OAR allocation, a Windows virtual machine — in any
combination. Read it outside in: *that machine, an allocation on it, a container, your command.*

<Term scene="stack" caption="errand run --env cluster train.py: three layers, declared once, crossed by one flag." />

The shell script that does `ssh`, then `sbatch`, then `apptainer exec`, then rsyncs the results
back — and that nobody else can run — is replaced by three lines in a file. And each line is more
than a way in:

- **It is built from what it declares.** A layer says what it needs — a Python version, a
  `requirements.txt`, a channel list, a container recipe, a pip list — and the first run that needs
  it creates it, installs into it, builds the image.
- **It is kept current.** Before every run errand compares a fingerprint of the declaration with
  what it last built, and brings the place up to date when they have drifted: a new pip spec, an
  edited recipe. What already exists the first time errand meets it is adopted as it is — an
  environment somebody has been working in for months is never the collateral of a first command.
- **Files cross with the work.** Over `Ssh` the project is rsynced there before the command runs;
  `--pull DIR` brings a directory back afterwards, `-o` gives each run an output directory over
  there and fetches it, and `also` pushes the sibling checkouts the work needs.
- **Several at once.** `--env local,cluster` is two runs; a tag picks every environment that has
  it, and one environment can cover several values of a tag.

→ [Environments](./environments), [Keeping them current](./upkeep), [Tags](./tags),
[Running elsewhere](./remote)

## What you also get

Nothing to declare for any of it:

- **The machine to yourself when it matters.** A queue per host, outside the process, shared by
  every errand on the machine: `errand run -x ./bench` waits for what is running and holds
  everything else back. A timing taken while something else was running is not a timing.
  → [Sharing the machine](./machine)
- **Let it run.** `--batch` launches the work and gives the shell back; `errand status` and
  `errand watch` say how it is going. → [Detached runs](./detached)
- **A record of every run** — what ran, where, when, how it ended, what it said — kept in errand's
  own state, `.errand/`. With `-o`, a directory per run whose path is computed from the work, the
  place and the date, so that comparison between dates and machines falls out of the tree.
  → [Where the output goes](./output)
- **One screen for all of it**: `errand tui`. → [The screen](./tui)

## Suites, and errand's own entries

A plain `errand run tests/` is a directory, not a command. `errand run 'tests/**::*'` is: the `::`
hands the files to an **entry runner** — pytest, Catch2, cargo — which collects one entry per test
and records each. A suite keeps everything that makes it itself: `pytest tests/` still works exactly
as before, and a `@pytest.mark.slow` becomes an entry tag that `-e '!slow'` filters on.

For work that has no framework of its own — a number to follow, a picture to look at — errand has
a small declaration that sits beside the code, `if track( "cost" ):`. It is one more way to give
errand something to run, not the way in.

→ [Running it](./running), [Runners](./runners), [Writing entries](./declaring-work)

## What it is not

**It is not a build system.** errand compiles nothing itself. A runner that needs a build runs the
command you already build with, once, before any of its entries. Your compiler, your flags and your
layout stay yours.

**It is not a replacement for your test runner.** What a suite gains is everything that happens
*around* the run.

**It is not a scheduler.** Inside a Slurm, PBS, OAR or LSF allocation it does not queue at all —
the scheduler has already decided what this process may have. Outside one, `Slurm` is a layer that
*submits* to the scheduler for you.

**It does not decide what may be compared to what.** A matrix that spans a laptop and a cluster
partition will produce numbers that are not comparable, and errand will not stop you. It records
where each number came from; the judgement is yours.

## The shape of a project

Nothing is required: `errand run make` works in an empty directory, in the interpreter and on the
machine you started it from. Once you want to say *where* things run, files at the root say it —
errand reads every `errand-*.py`:

```
errand-envs.py         the environments — versioned when it names no machine   ← errand init
errand-project.py      runners, what a bare `errand run` runs, settings        ← errand init
errand-vars.py         what only this machine knows — never versioned
.errand/               errand's own record of what it did
runs/                  the output directories you asked for with -o
```

→ [Configuration](./configuration)

## Next

[Installing](./installing) · [Getting started](./start) · or look at the layers at work in
[Four environments](/tutorials/environments).
