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
  - icon: 🔄
    title: Built from what you declare
    details: "The env from its requirements, the image from its recipe: built on first use, updated when the declaration changes. What already exists is adopted, never rebuilt."
    link: /guide/upkeep
    linkText: Keeping them current
  - icon: 📦
    title: Files there and back
    details: "The project is synced before the run. What you ask for comes back after: a directory, or an output directory per run."
    link: /guide/output
    linkText: Results and records
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

## Three things you stop doing

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
