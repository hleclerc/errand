---
layout: home

hero:
  name: "errand"
  text: "Run it there as if it were here"
  tagline: "Same command, same output in your terminal, Ctrl-C included, whether “there” is a container, a server over ssh, a Slurm allocation or a Windows VM. errand sets the place up, syncs the files both ways, and cleans up after itself."
  actions:
    - theme: brand
      text: "Quickstart"
      link: /guide/start
    - theme: alt
      text: "What errand is"
      link: /guide/what-is-errand
    - theme: alt
      text: "GitHub"
      link: https://github.com/hleclerc/errand

features:
  - icon: 🧭
    title: Any stack of layers
    details: "A conda or uv env, Apptainer or Docker, a server over ssh, a Slurm allocation, a Windows VM. Apptainer in Slurm over ssh is three lines."
    link: /guide/environments
    linkText: Environments
  - icon: 📊
    title: Live in the browser
    details: "errand run -O opens the run's page: its console, progress, curves, images and HTML pages, live, wherever it runs. errand web: every run of every machine, with its parameters and results."
    link: /guide/web
    linkText: errand web
  - icon: 🛠️
    title: Automatic remote installations
    details: "Nothing to install over there, not even errand. The env from its requirements, the image from its recipe: installed where it runs on first use, updated when the declaration changes. What already exists is adopted, never rebuilt."
    link: /guide/upkeep
    linkText: Automatic installations
  - icon: 🔄
    title: Smart sync
    details: "Only what changed crosses, through the connection already open: 0.7 s when nothing did. What a run made over there is never deleted; results, live views and caches come back."
    link: /guide/sync
    linkText: Smart sync
  - icon: 🗄️
    title: Computed once, everywhere
    details: "errand.download fetches a file once, even for a node with no internet. @errand.memo keeps a result by its inputs. Both reach every machine; library caches are kept tidy."
    link: /guide/caching
    linkText: Data and results
  - icon: 🎛️
    title: A fair share of the machine
    details: "A run asks for cores, cards, a share of a card's memory, from the command line or from its own code. It waits its turn; a card is assigned, never just counted."
    link: /guide/machine
    linkText: Sharing a machine
  - icon: 🛰️
    title: Servers kept while used
    details: "errand serve starts a server on demand, never twice, gives its card back to a computation while it rests, and stops it when nobody uses it."
    link: /guide/serve
    linkText: errand serve
  - icon: 🧹
    title: Nothing left behind
    details: "errand status lists what runs on every machine you sent work to. Ctrl-C stops it through every layer. What an agent leaves when it dies, the next one stops."
    link: /guide/status
    linkText: What is running
  - icon: 💻
    title: Close the laptop
    details: "The connection drops, the work goes on over there and its results still come back. --batch gives the shell back at once."
    link: /guide/detached
    linkText: Let it run
  - icon: ⚡
    title: Warm between commands
    details: "Connections, allocations and imports are kept for a while, so the next command starts faster. They give way when someone needs the room."
    link: /guide/agents
    linkText: Agents
---

## What you would type by hand

<div class="by-hand-vs-errand">
<div class="side">
<div class="side-label">By hand</div>

```bash
scp -r ./ gpu-box:~/proj/
ssh gpu-box
  cd ~/proj
  salloc -p gpu --gres=gpu:1 -t 2:00:00
  srun apptainer exec --nv containers/cuda.sif \
    python train.py --lr 1e-3
  # ...the laptop sleeps, the ssh drops: is it still running?
exit
scp -r gpu-box:~/proj/out/ ./out/
# a week later: what did I leave running on gpu-box?
ssh gpu-box 'ps -u $USER; squeue -u $USER'
```

</div>
<div class="arrow" aria-hidden="true"></div>
<div class="side">
<div class="side-label">With errand</div>

```bash
errand run --env cluster --pull out \
  python train.py --lr 1e-3
```

</div>
</div>

The place is declared once, in a file you version:

```python
# errand-envs.py
import errand

errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "~/proj" ),
                                         errand.Slurm( partition = "gpu", gpus = 1, time = "2:00:00" ),
                                         errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def" ) ] )
```

<Term scene="stack" caption="errand run --env cluster train.py. The ssh, the allocation and the container are the three layers declared above." />

## What you stop doing

**Doing the dance.** `errand run --env cluster python train.py` pushes the project, gets an
allocation, enters the container, runs, and brings `out/` back with `--pull out`. The output is in
your terminal as it happens.

**Wondering what is still running.** `errand status` reads every machine you sent work to and
lists what runs there, what waits in a queue, and what is kept warm:

```text
running   ( on mac, gpu-box: this machine, and every machine work was sent to from it )
  proj
    gpu-box      3f2a9c1e  run train.py  --env cluster  12 min  running
  other-proj: 1 waiting on gpu-box
  gpu-box: windows vm 80103674 ready, 8 cpus 16G
```

**Babysitting the connection.** Close the laptop: the work goes on over there, and its results
still come back ( [`errand attach`](/guide/detached#close-the-laptop) when you want to follow it again ).

**Computing it twice.** `@errand.memo` keeps a result by its inputs and `errand.download` a file by
its hash, in a cache the sync carries both ways: computed on the GPU server, it is here after the
command, and on the cluster after the next push. → [Computed once](/guide/caching)

**Fetching a figure to look at it.** `errand run -O` opens the run's page in the browser, and it is
live: the console, the progress bar, the curves, the images and HTML pages the run redraws, as they
are written on the cluster. `errand web` lists every run of every machine as a tree, with a table of
their parameters and results. → [Live in the browser](/guide/web)

## You stay in control

- What runs is **the command you would have typed**. errand does not need to know your language.
- `-v` prints **every command errand starts**: the ssh, the `sbatch`, the `apptainer exec`.
- `errand shell --env cluster` **lets you in**, in the allocation, in the container.
- An environment that already exists is **adopted as it is**, never rebuilt behind your back.
- Everything is **plain files**: `errand-envs.py` is Python, records are in `errand-outputs/`.
- **Nothing to install** on the other machines.

→ [What errand is](/guide/what-is-errand) · [Quickstart](/guide/start) ·
[Tutorials](/tutorials/)

errand also runs pytest, Catch2 and cargo suites, one run of the tool per file, in every environment:
[Running a suite](/guide/runners/).

::: warning Status
Everything documented here works and is covered by errand's own suite. It is not released as
stable: the API may still move.
:::
