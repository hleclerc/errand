---
layout: home

hero:
  name: "errand"
  text: "Your work, in any environment"
  tagline: "A conda or uv env, a container, another machine over ssh, a Slurm allocation, any stack of them — errand builds and updates each place from what it declares, syncs your files there and back, and runs whatever you would have typed."
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
    details: "An environment is a stack of layers — micromamba, conda, uv, a venv, Nix, Guix, module load, Docker, Podman, Apptainer, ssh, Slurm, a Windows VM — in any combination. Apptainer inside Slurm inside ssh is three lines."
    link: /guide/environments
    linkText: Environments
  - icon: 🔄
    title: Built, installed and kept current
    details: "Each layer says what it needs — a Python version, a requirements.txt, a container recipe. errand builds it the first time, checks it before every run, and brings it up to date when the declaration changed. What already exists is adopted, never rebuilt behind your back."
    link: /guide/upkeep
    linkText: Keeping them current
  - icon: 📦
    title: Files there and back
    details: "Over ssh the project is rsynced before the command runs, and what you name comes back after: --pull a directory, -o an output directory per run, handed to the command as $ERRAND_OUT_DIR."
    link: /guide/remote
    linkText: Running elsewhere
  - icon: 🧩
    title: Whatever you would have typed
    details: "errand run make check, errand run train.py, errand run ./bench. And for a suite — pytest, Catch2, cargo — `path::test` runs its tests one by one, each recorded, marks and all."
    link: /guide/running
    linkText: Running it
  - icon: ✖️
    title: Several places at once
    details: "--env local,cluster is two runs; --fp 32,64 picks environments by tag, and an environment that does not say covers both. The same command, side by side."
    link: /guide/tags
    linkText: Tags
  - icon: 🔒
    title: The machine to yourself when it matters
    details: "A queue per host, outside the process: errand run -x ./bench waits for what is running and holds everything else back; --cpus and --gpus take a share, and a card is assigned, not merely counted."
    link: /guide/machine
    linkText: Sharing the machine
  - icon: 🛰️
    title: Detach anything
    details: "--batch launches the work and gives you the shell back — a detached session locally, a released ssh command, an sbatch on a cluster. errand status and errand watch say how it is going."
    link: /guide/detached
    linkText: Detached runs
  - icon: 🪶
    title: No dependencies, ever
    details: "errand's job is to build the environment the work runs in, so it has to run before any environment exists. It writes YAML without pyyaml and draws its screen with the standard library's curses."
    link: /guide/installing
    linkText: Installing
---

## One command, through every layer

Describe a place once, as a stack read from the outside in — *that machine, an allocation on it, a
container, your command*:

```python
# errand-envs.py
import errand

errand.envs[ "local" ]   = errand.Env( [ errand.Micromamba( "myproject", python = "3.13", requirements = "requirements.txt" ) ] )
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "~/errand/myproject" ),
                                         errand.Slurm( partition = "gpu", gpus = 1, time = "2:00:00" ),
                                         errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def" ) ],
                                       cuda = True )
```

Then go there:

```bash
errand run --env local pytest                    # micromamba env created and installed first
errand run --env cluster python train.py         # pushed, allocated, contained, run
errand run --env cluster --pull out make results # ...and out/ comes back
errand run --env local,cluster ./bench           # in both places
errand run --batch --env cluster train.py        # and give me the shell back
errand shell --env cluster                       # be let in, to look around
```

<Term scene="stack" caption="errand run --env cluster train.py. The ssh, the allocation and the container are the three layers declared above; setting them up, entering them and fetching the files back is errand's part." />

## What you run is yours

errand does not need to know your language: what follows `errand run` is what you would have typed,
read from the command line alone.

::: code-group

```bash [A command]
errand run --env cluster make check
errand run --env cluster ./run_experiment.sh --seed 3
errand run -x ./my_benchmark             # alone on this machine while it runs
errand run -o --env cluster ./simulate   # a directory per run, $ERRAND_OUT_DIR, brought back
```

```bash [pytest]
errand run --env local,cluster 'tests/**::*'   # one entry per test, in both places
errand run tests/test_api.py::test_ok          # one of them
errand run -e '!slow' 'tests/**::*'            # @pytest.mark.slow is an entry tag
```

```bash [C++ · Catch2]
errand run 'cpp/**::*'                     # built once, in the place, then each case
errand run cpp/test_geometry.cpp::area     # one Catch2 case, by name
errand run --env cluster 'cpp/**::*'       # compiled and run over there
```

```bash [Rust · cargo]
errand run 'src/**::*'          # one entry per test target
errand run --env cluster 'src/**::*'
```

```python [errand's own entries]
# bench/solvers.py -- for work with no framework of its own: errand run 'bench/solvers.py::*'
from errand import track, Param

if p := track( "cost", n = Param( 1000, help = "nb of points" ) ):
    p.results[ "residual" ] = solve( p.n )
```

:::

Every run is recorded — what ran, where, when, how it ended, what it said — in `.errand/`, which is
what `errand status`, `errand watch` and the screen read. Ask with `-o` and each run also gets a
directory you can open, at a path you could have written down in advance:

```text
runs/<file or command>/<case>/
  2026-09-25_18h04m11-cluster@gpu-box/result.yaml
  2026-09-25_18h04m11-local@laptop/result.yaml
  latest -> the newest of them
  summary.yaml            <- one row per run, and the extents across them
```

## Where to go next

- **Never used it** → [What errand is](/guide/what-is-errand), then [Getting started](/guide/start).
- **Want to see the layers work** → [Four environments](/tutorials/environments), then
  [A run over two machines](/tutorials/two-machines).
- **Have a pytest, Catch2 or cargo project** → [Adopt an existing suite](/tutorials/adopt-a-suite).
- **Looking for a flag** → [the command-line reference](/reference/cli).

::: warning Status
Everything documented here works and is covered by errand's own suite. It is not released yet: the
API may still move — in particular errand's own entries, which are being reworked into a protocol
any program can follow.
:::
