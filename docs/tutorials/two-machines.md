# 2 · Numbers over two machines

The goal: **numbers taken here and on another machine, in a form you can still compare a month from
now.** Timings are the obvious case; an error or a residual works the same way.

This one is not an example directory: do it in a project of your own. You need an ssh host you can
reach without a password. That is all.

## The work

```python
# bench/solvers.py
import time
from errand import bench, Param
from mypkg import solve, residual

if p := bench( "cost", n      = Param( 100_000, help = "number of unknowns" ),
                       method = Param( "newton", choices = [ "newton", "lbfgs" ] ) ):
    t = time.perf_counter( )
    x = solve( n = p.n, method = p.method )
    p.results[ "seconds" ]  = time.perf_counter( ) - t
    p.results[ "residual" ] = residual( x )
```

This uses errand's own entries. `bench` does three things: the numbers are kept, the entry takes
the machine to itself while it runs (these are timings), and a bare `errand run` does not fire it by
accident. For numbers that are not timings, `track` is the same without the exclusivity.
→ [Writing entries](/guide/declaring-work)

Check that errand sees it:

```bash
errand list bench/solvers.py::cost
```

## The places

```python
# errand-envs.py
import errand

errand.default_env = "here"

errand.envs[ "here" ] = errand.Env( [ errand.Venv( python = ".venv/bin/python", requirements = "requirements.txt" ) ],
                                    driver = "cpu" )

errand.envs[ "there" ] = errand.Env( [ errand.Ssh( host = errand.value( "ssh_host", "gpu-box" ),
                                                   root = errand.value( "ssh_root", "/home/me/proj" ) ),
                                       errand.Venv( python = ".venv/bin/python", requirements = "requirements.txt",
                                                    create = True ) ],
                                     driver = "cpu", remote = True )
```

The project's own settings (`errand.configure( out = …, src = [ "src" ] )` and the like) go in
`errand-project.py`, which is versioned. This file is yours.

Two things to notice:

**`Ssh` comes first**, and everything after it happens over there. The `Venv` layer is the same in
both environments: they differ by one layer, not by two configurations. → [Ssh](/guide/layers/ssh)

**The host name is not committed.** `errand.value( "ssh_host", "gpu-box" )` reads a value another
`errand-*.py` defined, with a default for whoever wrote the file:

```python
# errand-0-hosts.py -- not tracked; add it to .gitignore ( the 0 makes it load before errand-envs.py )
ssh_host = "bigbox.lab.example"
ssh_root = "/home/me/scratch/proj"
```

::: danger If you add Slurm later, the root must be shared
A batch job runs on a compute node, and `/tmp` there is not the `/tmp` you pushed to. errand checks
before submitting, but a home or a `/scratch` is the right choice from the start.
:::

## Get the places ready

```bash
errand envs             # what is declared, and the state of each
errand setup --dry-run  # what building them would run
errand setup            # build them, and nothing else
```

`errand envs` says `unknown` for `there`: only the other machine can say what it has. Ask it:

```bash
errand run --env there python -c "import sys; print( sys.version )"
```

Everything after errand's options is a command to run in the environment. The project is pushed,
the environment prepared if needed, the command run over there and its output shown here. Add `-v`
to see every command errand starts, here and over there.

## Take the number, in both places

```bash
errand run --grid=, -o --env here,there bench/solvers.py::cost --n=100000
```

```text
  -> there  ssh:bigbox.lab.example -> venv:.venv/bin/python
    sync push -> bigbox.lab.example:/home/me/scratch/proj
  ...
```

The comma makes a [grid](/guide/matrices): two runs, one per place, sharing one timestamp. The grid
is expanded here, so the paths to bring back are known before anything starts. Every run is
recorded here, in `errand-outputs/runs/`:

```text
errand-outputs/runs/bench/solvers.py/cost/
  2026-10-02_14h22m07-here@laptop-n=100000/result.yaml
  2026-10-02_14h22m07-there@bigbox-n=100000/result.yaml
  summary.yaml
```

```bash
cat errand-outputs/runs/bench/solvers.py/cost/summary.yaml
```

One row per run, with the extents across them. It is recomputed from the `result.yaml` files beside
it on every run, so it is always right. → [Results and records](/guide/output)

## Make it a sweep, and let go of it

```bash
errand run --grid=, --batch --env here,there bench/solvers.py::cost --n=100000,1000000 --method=newton,lbfgs
```

```text
  submitted 4c1e - here on this machine (local 41288), there on bigbox.lab.example (ssh 20114)
  errand status    errand watch
```

Eight runs, and your shell back. `--batch` is a detached process here, and a command started and
let go of over there. Nothing else about the runs changes. → [Let it run](/guide/detached)

```bash
errand watch
```

```text
4c1e  run --grid=, --env here,there bench/solvers.py::cost --n=100000,1000000 --method=newton,lbfgs   2026-10-02 14:30:12   6/8 [######  ]
    here: local 41288 on this machine - finished
    there: ssh 20114 on bigbox.lab.example - running
                                  here@laptop             there@bigbox
      cost  method=lbfgs, n=100000    ok seconds=18.9         ...
      cost  method=lbfgs, n=1000000   ...                     ...
      cost  method=newton, n=100000   ok seconds=12.4         ok seconds=7.1
      cost  method=newton, n=1000000  ok seconds=61.2         ok seconds=34.8
```

Illustrative output. The grid reads as a table: parameters down, places across. `errand watch`
reads the records and keeps nothing of its own: stop it, restart it, run two.

Close the terminal and come back tomorrow: `errand status` says what still runs, on every machine
work was sent to, and how each submission is doing. → [What is running](/guide/status)

## A month later

```bash
errand run --grid=, -o --env here,there bench/solvers.py::cost --n=100000
cat errand-outputs/runs/bench/solvers.py/cost/summary.yaml
```

Same command, new rows. The old runs are still there: only a run's own directory is cleared,
everything above it accumulates. Each run records its `date`, its `place`, its `host` and the
`commit` it was taken at, with `dirty: true` if the tree was not clean.

::: warning What errand will not decide for you
A grid that spans your laptop and a cluster partition produces numbers that are not comparable, and
errand will not stop you. It runs what you ask where you ask, and records where each number came
from. Deciding what may be compared is yours.
:::

## What you have now

- A number declared next to the code that produces it, and nowhere else.
- Two places that differ by one layer, each built from its own declaration.
- A path per run that you could have written down in advance, which is why the remote ones could be
  brought back.
- A queue that keeps a second terminal from spoiling the measurement, without your asking for one.

## Next

- [3 · A cluster, a Windows VM, and what is running](./cluster-and-vm): the same over Slurm, plus a
  Windows build.
- [Sharing the machine](/guide/machine): what `exclusive`, `cpus` and `gpus = 1` do.
- [Adopting a suite](/guide/runners/adopting): the same treatment for a pytest, Catch2 or cargo suite.
