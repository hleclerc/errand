---
layout: home

hero:
  name: "errand"
  text: "Run it somewhere, get everything back"
  tagline: "Declare a piece of work next to the code it exercises. errand works out where to run it, makes sure that place is ready, runs it — in several places at once if you ask — and repatriates what it produced, into a path you can predict."
  actions:
    - theme: brand
      text: "Get started"
      link: /guide/what-is-errand
    - theme: alt
      text: "Tutorials"
      link: /tutorials/
    - theme: alt
      text: "GitHub"
      link: https://github.com/hleclerc/errand

features:
  - icon: 🧭
    title: Where and how it runs
    details: "An environment is a stack of layers — micromamba, conda, uv, a venv, Nix, Guix, module load, Docker, Podman, Apptainer, ssh or Slurm — in any combination. Declared once, built from what they say they need, checked before every run."
    link: /guide/environments
    linkText: Environments
  - icon: 🔒
    title: Sharing the machine
    details: "Work says what it needs — a core, eight of them, a GPU, the whole machine — and errand holds a queue per host so two invocations, in two terminals, on two projects, do not trample each other. `errand -x -- ./bench` puts any command under it. A timing taken while something else was running is not a timing."
    link: /guide/machine
    linkText: The queue
  - icon: 📂
    title: What comes back
    details: "Every run gets an output directory whose path is computed, not invented — from the work, its parameters, its environment and its date. Numbers, files, logs and status land there, and comparison across dates and machines falls out of the tree."
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
    details: "errand --tui — two pages, because there are two questions: what do I run, and what came of it. Typing is the search; the function keys are the verbs. Drawn with the curses of the standard library."
    link: /guide/tui
    linkText: The screen
  - icon: 🧩
    title: Suites you already have
    details: "One provider line puts an existing pytest, Catch2 or cargo suite under errand — unmodified, with its own assertions and its own marks, which become entry tags."
    link: /guide/providers
    linkText: Other languages
  - icon: 🪶
    title: No dependencies, ever
    details: "errand's job is to build the environment the work runs in, so it has to run before any environment exists. It writes YAML without pyyaml and draws its screen with the standard library's curses, for that reason alone."
    link: /guide/installing
    linkText: Installing
---

## Hello, errand

Work is declared where the code is, with a guard that reads like `if __name__ == "__main__":` but
does more — several per file, each identified by its call site:

```python
# bench/solvers.py
from errand import bench, Param

if p := bench( "cost", n = Param( 1000, help = "nb of points" ),
                       method = Param( "newton", choices = [ "newton", "lbfgs" ] ) ):
    p.results[ "seconds" ] = solve( p.n, p.method )
    ( p.out_dir / "residual.png" ).write_bytes( plot( ) )
    assert p.results[ "seconds" ] < 60
```

Then ask for it — one run, or sixteen:

```bash
errand cost                                       # once, in the default environment
errand cost --n=1000,5000 --method=newton,lbfgs   # four runs, four directories
errand cost --env local,gpu --fp 32,64            # four more: two places, two precisions
errand --batch cost --env cluster                 # on the cluster, and give me the shell back
```

Every one of them lands somewhere you could have written down in advance:

```text
runs/solvers/cost/
  2026-09-25_18h04m11-gpu@gpu-box-method=newton,n=5000/result.yaml
  2026-09-25_18h04m11-local@laptop-method=newton,n=5000/result.yaml
  latest -> the newest of them
  summary.yaml            <- one row per run, and the extents: this is the comparison
```

## The three legs

errand stands on three, and you want all three. A runner that only *launches* leaves you to
remember where the numbers went; one that only *collects* cannot tell you that the machine was busy
when they were taken.

| | |
|---|---|
| [**Where and how it runs**](/guide/environments) | environments as layer stacks, built and kept current on their own, selected by name or by tag, and crossed into matrices |
| [**Sharing the machine**](/guide/machine) | a queue per host, outside the process, shared by every errand on the machine; cards assigned rather than counted; waiting kept outside the measurement |
| [**What comes back**](/guide/output) | a computed output directory per run, `result.yaml` in it, summaries above it, and a remote run's paths known *before* it starts — which is what lets them be rsynced back |

## Where to go next

- **Never used it** → [What errand is](/guide/what-is-errand), then [Your first entry](/tutorials/first-entry).
- **Have a project with a suite already** → [Adopt an existing suite](/tutorials/adopt-a-suite).
- **Want numbers off a cluster** → [Four environments](/tutorials/environments), then
  [A bench over two machines](/tutorials/two-machines).
- **Looking for a flag** → [the command-line reference](/reference/cli).

::: warning Status
Everything documented here works and is covered by errand's own suite — which is itself written with
errand. It is not released yet: the API may still move. Still to write: `errand init`, and providers
beyond the three that ship.
:::
