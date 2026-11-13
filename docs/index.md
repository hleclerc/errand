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
    title: Any stack of layers
    details: "micromamba, uv, Apptainer, ssh, Slurm, a Windows VM… Apptainer in Slurm over ssh is three lines. Files go there and come back."
    link: /guide/environments
    linkText: Environments
  - icon: 🔄
    title: Automatic builds and installs
    details: "The conda env from its requirements, the Apptainer or Docker image from its recipe: built on first use, rebuilt when what it declares changes."
    link: /guide/upkeep
    linkText: Keeping them current
  - icon: ⚡
    title: Warm between commands
    details: "The first run leaves agents behind. The next one over ssh takes a second, not eight; on a cluster, it skips the queue."
    link: /guide/agents
    linkText: Fast, and nothing lost
  - icon: 💻
    title: Close the laptop
    details: "The work goes on over there. errand attach picks it up, results included. --batch gives the shell back at once."
    link: /guide/agents#close-the-laptop
    linkText: Close the laptop
  - icon: 🧩
    title: Name a target, errand finds the tool
    details: "A script, a binary, a command, a test... errand reads the content to pick the right tool (e.g. python, pytest, cargo, Catch2)"
    link: /guide/running
    linkText: Running it
  - icon: 🔒
    title: Resource management
    details: "-x for a timing nothing disturbs, --cpus and --gpus for a share. What is only kept warm gives way."
    link: /guide/machine
    linkText: Sharing the machine
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
errand run --grid=, --env local,cluster ./bench           # in both places
errand run --batch --env cluster train.py        # and give me the shell back
errand shell --env cluster                       # be let in, to look around
errand attach                                    # the laptop closed: pick the run up again
```

The second command to the cluster does not log in again: the [agents](/guide/agents) the first one
left are still there, and the layers are already entered.

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
errand run --grid=, --env local,cluster 'tests/**::*'   # one entry per test, in both places
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

Every run is recorded — what ran, where, when, how it ended, what it said — in `errand-outputs/`,
which is what `errand status`, `errand watch` and the screen read. Each run has a directory you can
open, at a path you could have written down in advance, and `-o` lets it write its own files there:

```text
errand-outputs/runs/<file or command>/<case>/
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
