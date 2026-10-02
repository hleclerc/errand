---
layout: home

hero:
  name: "errand"
  text: "Run it somewhere, get everything back"
  tagline: "Say once how to reach the places your code can run — a conda environment, a container, another machine over ssh, a Slurm allocation, any stack of them. errand builds them, goes in, runs your command or your tests there, and brings back what they produced into a path you can predict."
  actions:
    - theme: brand
      text: "Get started"
      link: /guide/start
    - theme: alt
      text: "Tutorials"
      link: /tutorials/
    - theme: alt
      text: "GitHub"
      link: https://github.com/hleclerc/errand

features:
  - icon: 🧭
    title: Layers, so you never write the ssh-slurm-apptainer script again
    details: "An environment is a stack of layers — micromamba, conda, uv, a venv, Nix, Guix, module load, Docker, Podman, Apptainer, ssh or Slurm — in any combination. Apptainer inside Slurm inside ssh is three lines, built from what they say they need, checked before every run, with the results brought back."
    link: /guide/environments
    linkText: Environments
  - icon: 🧩
    title: Your tools, as they are
    details: "pytest, Catch2, cargo, a Makefile target or any command: errand runs what you already have, unmodified, in any of those places. With no configuration it looks at the directory and says what it found; `errand --init` writes that down."
    link: /guide/start
    linkText: Start from what you have
  - icon: 🔒
    title: Sharing the machine
    details: "Work says what it needs — a core, eight of them, a GPU, the whole machine — and errand holds a queue per host so two invocations, in two terminals, on two projects, do not trample each other. `errand -x -- ./bench` puts any command under it. A timing taken while something else was running is not a timing."
    link: /guide/machine
    linkText: The queue
  - icon: 📂
    title: What comes back
    details: "Every run gets an output directory whose path is computed, not invented — from the work, its parameters, its environment and its date. Logs, files, status and any numbers you want to follow land there, and comparison across dates and machines falls out of the tree."
    link: /guide/output
    linkText: The output tree
  - icon: ✖️
    title: A comma is a matrix
    details: "On a parameter, on a tag, on an environment — it means the same thing everywhere. Each value is an axis, the cartesian product is run, and every combination lands in its own directory so the results sit side by side."
    link: /guide/matrices
    linkText: Matrices
  - icon: 🛰️
    title: Detach anything
    details: "--batch launches the work and gives you the shell back — a detached session locally, a released ssh command, an sbatch on a cluster. Same paths, same queue, same output. --status and --watch say how it is going."
    link: /guide/detached
    linkText: Detached runs
  - icon: 🖥️
    title: One screen for all of it
    details: "errand --tui — two pages, because there are two questions: what do I run, and what came of it. Tick three places, press enter, watch the three layer stacks fill the runs page. Drawn with the curses of the standard library."
    link: /guide/tui
    linkText: The screen
  - icon: 🪶
    title: No dependencies, ever
    details: "errand's job is to build the environment the work runs in, so it has to run before any environment exists. It writes YAML without pyyaml and draws its screen with the standard library's curses, for that reason alone."
    link: /guide/installing
    linkText: Installing
---

## One command, through every layer

Describe a place once, as a stack read from the outside in — *that machine, an allocation on it, a
container, your command*:

```python
# errandfile.py
from errand import env, Micromamba, Apptainer, Ssh, Slurm

env( "local",   [ Micromamba( "myproject", python = "3.13" ) ] )
env( "cluster", [ Ssh( host = "gpu-box", root = "~/errand/myproject" ),
                  Slurm( partition = "gpu", gpus = 1, time = "2:00:00" ),
                  Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def" ) ],
     cuda = True )
```

Then go there:

```bash
errand --env cluster -- nvidia-smi          # be let in: any command, through every layer
errand train --env cluster                  # run a piece of work there, results brought back
errand train --env local,cluster            # in both places, side by side
errand --batch train --env cluster          # and give me the shell back
```

<Term scene="stack" caption="errand train --env cluster. The ssh, the allocation and the container are the three layers declared above; setting them up, entering them and fetching the files back is errand's part." />

## Whatever you test with

errand does not need to know your language: it needs to know how to *start* your suite, and the
places to start it in. Pick yours.

::: code-group

```bash [pytest]
cd my-project                  # a tests/ directory, nothing about errand in it
errand --init                  # writes errandfile.py: provider( Pytest( dirs = [ 'tests' ] ) )
errand                         # the suite, here
errand --env local,cluster     # the same suite, in both places, side by side
errand -e '!slow'              # @pytest.mark.slow is an entry tag
```

```bash [C++ · Catch2]
cd my-project                  # cpp/test_*.cpp and a Makefile
errand --init                  # provider( Catch2( dir = 'cpp', build = 'make -C cpp' ) )
errand                         # built once, then each test file run
errand test_geometry::area     # one Catch2 case, by name
errand --env cluster           # compiled and run over there, results back here
```

```bash [Rust · cargo]
cd my-project                  # a Cargo.toml
errand --init                  # provider( Cargo( ) )
errand                         # one entry per test target
errand --env cluster           # cargo test, inside the cluster's container
```

```bash [Any command]
cd my-project                  # a script, a Makefile target, a notebook runner...
errand --env cluster -- make check
errand --env cluster -- ./run_experiment.sh --seed 3
errand -x -- ./my_benchmark    # alone on this machine while it runs, whatever else is queued
```

```python [errand's own entries]
# bench/solvers.py -- optional: for work with no framework of its own
from errand import track, Param

if p := track( "cost", n = Param( 1000, help = "nb of points" ) ):
    p.results[ "residual" ] = solve( p.n )
    ( p.out_dir / "residual.png" ).write_bytes( plot( ) )
```

:::

Every one of them lands somewhere you could have written down in advance:

```text
runs/<suite>/<case>/
  2026-09-25_18h04m11-cluster@gpu-box/result.yaml
  2026-09-25_18h04m11-local@laptop/result.yaml
  latest -> the newest of them
  summary.yaml            <- one row per run, and the extents: this is the comparison
```

## The three legs

errand stands on three, and you want all three. A runner that only *launches* leaves you to
remember where the results went; one that only *collects* cannot tell you that the machine was busy
when they were taken.

| | |
|---|---|
| [**Where and how it runs**](/guide/environments) | environments as layer stacks, built and kept current on their own, selected by name or by tag, and crossed into matrices |
| [**Sharing the machine**](/guide/machine) | a queue per host, outside the process, shared by every errand on the machine; cards assigned rather than counted; waiting kept outside the measurement |
| [**What comes back**](/guide/output) | a computed output directory per run, `result.yaml` in it, summaries above it, and a remote run's paths known *before* it starts — which is what lets them be rsynced back |

## Where to go next

- **Never used it** → [What errand is](/guide/what-is-errand), then [Start from what you have](/guide/start).
- **Want to see the layers work** → [Four environments](/tutorials/environments), then
  [A run over two machines](/tutorials/two-machines).
- **Have a pytest, Catch2 or cargo project** → [Adopt an existing suite](/tutorials/adopt-a-suite).
- **Looking for a flag** → [the command-line reference](/reference/cli).

::: warning Status
Everything documented here works and is covered by errand's own suite — which is itself written with
errand. It is not released yet: the API may still move. Still to write: providers beyond the three
that ship.
:::
