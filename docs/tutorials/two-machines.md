# 4 · A bench over two machines

This one is not an example directory — it is the thing the other three were building towards, done
in a project of your own. The goal: **one number, taken here and on another machine, in a form you
can compare a month from now.**

You need an ssh host you can reach without a password. That is all.

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

`bench` means three things at once: the numbers are [kept](/guide/declaring-work#the-four-traits),
the entry takes the machine to itself while it runs, and a bare `errand` will not fire it by
accident.

Check that errand sees it before going any further:

```bash
errand --help "solvers::cost"
```

## The places

```python
# errandfile.py
from errand import configure, env, Venv, Ssh, Vars
from errand.local import value

configure( out = "runs", src = [ "src" ], default = "here" )

env( "here", [ Venv( python = ".venv/bin/python", requirements = "requirements.txt" ) ],
     driver = "cpu" )

env( "there", [ Ssh( host = value( "ssh_host", "gpu-box" ),
                     root = value( "ssh_root", "/home/me/proj" ) ),
                Venv( python = ".venv/bin/python", requirements = "requirements.txt",
                      create = True ) ],
     driver = "cpu", remote = True )
```

Two things to notice in that file:

**`Ssh` is first**, and everything after it happens over there. The `Venv` layer is the same
declaration in both environments — the difference between the two is one layer, not two
configurations.

**The host name is not committed.** `value( "ssh_host", "gpu-box" )` reads an untracked
`errand.local.py` and falls back to a default that works for whoever wrote the file:

```python
# errand.local.py -- not tracked; add it to .gitignore
ssh_host = "bigbox.lab.example"
ssh_root = "/home/me/scratch/proj"
```

::: danger If you add Slurm later, the root must be shared
A batch job runs on a compute node, and `/tmp` there is not the `/tmp` you pushed to. errand checks
for that before submitting, but a home or a `/scratch` is the right answer from the start.
:::

## Get the places ready

```bash
errand --envs                 # what is declared, and the state of each
errand --setup --dry-run      # exactly what building them would run
errand --setup                # do it, and nothing else
```

`--envs` will say `unknown` for `there`: only the other machine can say what it has. Reach it
directly to find out:

```bash
errand --env there -- python -c "import sys; print( sys.version )"
```

Everything after `--` is a command to run *in* the environment. It is pushed, run over there and
reported back — and the environment is prepared first, by the same rules as a run.

## Take the number, in both places

```bash
errand "solvers::cost" --env here,there --n=100000
```

```text
  → bigbox.lab.example:/home/me/scratch/proj  env=there  tags=driver:cpu,remote
  rsync push → bigbox.lab.example:/home/me/scratch/proj
  ...
  rsync pull ← bigbox.lab.example:/home/me/scratch/proj [runs/solvers/cost]
```

The comma is a [matrix](/guide/matrices); the two runs share one timestamp because they are one
command. The remote side never sees a matrix — it is expanded here, into plain runs, and the paths
to fetch back are worked out **before** anything starts.

```text
runs/solvers/cost/
  2026-10-02_14h22m07-here@laptop-n=100000/result.yaml
  2026-10-02_14h22m07-there@bigbox-n=100000/result.yaml
  summary.yaml
```

```bash
cat runs/solvers/cost/summary.yaml
```

One row per run, with the extents across them. That file is recomputed from the neighbouring
`result.yaml` files on every run, so it is always right.

## Make it a sweep, and let go of it

```bash
errand --batch "solvers::cost" --env here,there --n=100000,1000000 --method=newton,lbfgs
  submitted 4c1e - 8 run(s) - 4 on bigbox.lab.example, 4 on this machine
  errand --status    errand --watch
```

Eight runs, and the shell back. `--batch` means a detached session locally and a released ssh
command over there; nothing else about the run changes.

```bash
errand --watch
```

```text
4c1e  "solvers::cost" --env here,there --n=1e5,1e6 --method=newton,lbfgs   6/8 [######  ]
    here:  local 41288 on this machine - finished
    there: ssh 20114 on bigbox.lab.example - running
                                   here@laptop         there@bigbox
      cost  method=newton, n=100000    ok seconds=12.4     ok seconds=7.1
      cost  method=newton, n=1000000   ok seconds=61.2     ok seconds=34.8
      cost  method=lbfgs,  n=100000    ok seconds=18.9     ...
      cost  method=lbfgs,  n=1000000   ...                 ...
```

The matrix reads as a table — parameters down, places across — because that is the shape it has.
`--watch` holds no state of its own: kill it, restart it, run two of them.

Close the terminal and come back tomorrow: `errand --status` reads the tree, and
[the arrival of a result file where one was expected is the completion
signal](/guide/detached#the-output-tree-is-the-state). There is no daemon and nothing to get out of
sync.

## A month later

```bash
errand "solvers::cost" --env here,there --n=100000
cat runs/solvers/cost/summary.yaml
```

Same command, new rows. The old runs are still there — only the run directory is cleared and
recreated, everything above it accumulates — and each one records its `date`, its `place`, its
`host` and the `commit` it was taken at, `dirty: true` included if the tree was not clean.

::: warning What errand will not decide for you
A matrix that spans your laptop and a cluster partition at once will produce numbers that are not
comparable, and errand will not stop you. It runs what you ask where you ask and records where each
number came from; deciding what may be compared to what is yours.
:::

## What you have now

- A number declared next to the code that produces it, and nowhere else.
- Two places, differing by one layer, both built from their own declaration.
- A path per run that you could have written down in advance — which is exactly why the remote ones
  could be fetched.
- A queue that keeps a second terminal from spoiling the measurement, without your having asked for
  one.

## Where to go from here

- [Sharing the machine](/guide/machine) — what `exclusive`, `cpus` and `gpus = 1` actually do.
- [The screen](/guide/tui) — the same matrix, ticked rather than typed.
- [Other languages](/guide/providers) — the same treatment for a Catch2 or cargo suite.
