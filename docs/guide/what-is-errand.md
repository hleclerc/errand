# What errand is

> **Run it there as if it were here.** Same command, same output in your terminal, Ctrl-C included,
> whether "there" is a container, a server over ssh, a Slurm allocation or a Windows VM. errand
> sets the place up, syncs the files both ways, and cleans up after itself.

An *errand* is a trip made on someone's behalf: go there, do the thing, come back with what it
produced.

## Who it is for

You write code that computes: research, simulation, HPC, machine learning. It runs on your laptop,
on a server or two at the lab, on a national cluster, and now and then on Windows to build a wheel.
Each place has its own way in (ssh, `module load`, `sbatch`, a container, a conda env), and you
know all of them by heart.

errand is for that work. It is not a production orchestrator (no Kubernetes, no Ansible), and it
is not a new test runner.

## Stop babysitting your runs

What errand takes off your hands:

- **The way in.** ssh, then the allocation, then the container, then the env: declared once as a
  [stack of layers](./environments), crossed by one flag, `--env cluster`.
- **Installing over there.** A layer declares what it needs (a Python version, a `requirements.txt`,
  a container recipe), and errand installs it where it runs on first use, then updates it when the
  declaration changes. Nothing to install by hand, errand included. → [Automatic installations](./upkeep)
- **Moving files.** Only what changed crosses, both ways; what a run made over there is never
  deleted; results and live views come back. → [Smart sync](./sync)
- **Fetching and computing twice.** `errand.download` and `@errand.memo` keep data and results in a
  cache that reaches every machine. → [Computed once](./caching)
- **Looking for results.** `errand run -O` opens the run's page in the browser: its console, progress,
  curves, images and HTML pages, live, wherever it runs. `errand web` lists every run of every machine
  with its parameters and results. → [Every run, live in the browser](./web)
- **Watching the connection.** Close the laptop: the work goes on, and `errand attach` picks it up.
  → [Let it run](./detached)
- **Paying the start again.** Connections, allocations, VMs and imports are kept warm for a while,
  so the next command starts faster. → [Agents](./agents)
- **Hunting what was left running.** `errand status` lists what runs on every machine you sent work
  to; Ctrl-C stops it through every layer; what a crashed agent left, the next one stops.
  → [What is running](./status)
- **Taking turns on a machine.** `-x` keeps the machine to itself for a timing; `--cpus`, `--gpus`
  take a share, and a card is assigned; a run can ask from its own code ( `errand.require` ).
  → [Sharing a machine](./machine)

## You stay in control

The usual objection is "I do this by hand, it works, and I don't want to lose control". errand
hides nothing:

- **What runs is your command.** What follows `errand run` is what you would have typed:
  `make check`, `python train.py`, `./bench`. errand does not need to know your language.
- **You can see every step.** `-v` prints every command errand starts, including the ssh, the
  `sbatch`, the `apptainer exec` and what it hands to an agent.
- **You can get in.** `errand shell --env cluster` is a real terminal in the allocation, in the
  container, in the env.
- **Nothing is rebuilt behind your back.** An environment that exists the first time errand meets
  it is adopted as it is. `errand setup --dry-run` shows what an update would run.
- **It is all plain files.** The places are Python, in `errand-envs.py`. The records are YAML and
  logs, in `errand-outputs/`. No database, no daemon to install, no account.
- **Nothing to install over there.** errand brings itself to the other machines, and needs nothing
  but a Python 3.8 or later, which it makes if the machine has none.
- **Stop means stop.** Ctrl-C reaches the work wherever it runs. What errand keeps warm stops on its
  own when unused, and `errand agents stop` stops it now.

## What it is not

**Not a scheduler.** `Slurm` is a layer that asks Slurm for an allocation on your behalf; Slurm
decides who gets the nodes. errand only shares out what it was given between your own commands.

**Not a build system.** errand compiles nothing itself. When a run needs a build, it runs the
command you already build with.

**Not a replacement for your test runner.** It can run a pytest, Catch2 or cargo suite, one run
of its tool per file, in every environment, and `pytest` keeps working as before. → [Running a suite](./runners/)

**Not a judge of what compares.** Numbers from a laptop and from a cluster are not comparable, and
errand will not stop you. It records where each one came from.

## The shape of a project

Nothing is required: `errand run make` works in an empty directory. Once you want to say *where*
things run, files at the project root say it. errand reads every `errand-*.py`:

```
errand-envs.py         the places: versioned when it names no machine   ← errand init
errand-project.py      settings, what a bare `errand run` runs          ← errand init
errand-vars.py         what only this machine knows (hosts, paths): never versioned
errand-outputs/        what errand did: runs, builds, bookkeeping
```

→ [Configuration](./configuration)

## Next

[Installing](./installing) · [Quickstart](./start) · [Four environments](/tutorials/environments)
