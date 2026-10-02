# Tags

A tag says what an environment *is*. There is nothing to declare — a tag is a keyword argument on
`errand.Env`, and every name used becomes a flag:

```python
# errand-envs.py
errand.envs[ "gpu" ]     = errand.Env( CUDA, driver = "jax", cuda = True )
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( … ), errand.Slurm( … ) ] + CUDA, driver = "jax", cuda = True, fp = "64" )
```

```bash
errand --env cluster          # by name
errand --driver jax           # by tag, one flag per name
errand --fp 64 --cuda
errand -t 'jax & fp=64 & !remote'            # --env-tags, the expression form
```

## Saying nothing means every value

An environment that does not mention `fp` covers every precision, so `--fp 32,64` is **two runs in
it**. One that says `fp = "64"` is only ever selected for that one.

This is what makes a tag a *dimension* rather than a label. You declare one environment, and the
precision, the backend or the problem class you want to sweep crosses it.

## Tags only select

What an environment then does to the child process is a `Vars` layer, like everything else it does
— and that layer can read the selection back:

```python
# errand-envs.py
errand.envs[ "gpu" ] = errand.Env( CUDA + [ errand.Vars( lambda t: { "MYPROJ_FTYPE": f"FP{ t.get( 'fp', '64' ) }" } ) ],
                                   driver = "jax", cuda = True )
```

Without that, a dimension an environment merely *parametrizes* would have to be split into one
environment per value, with each value written twice: once to be matched by `--fp`, once to be
handed to the child. There would be a `local32` beside every `local` and a `gpu32` beside every
`gpu`.

One environment covering a range is the common case, and two covering one value each is the
exception.

The work itself reads an ordinary environment variable, and names no machine:

```python
# src/solver.py -- knows nothing about errand
FTYPE = os.environ.get( "MYPROJ_FTYPE", "FP64" )
```

## A tag can select several environments

…and that is the point. A comma is a matrix here exactly as it is on a parameter:

```bash
errand -k bench "solvers::*" --fp 32,64        # both precisions
errand -k bench "solvers::*" --env gpu,cluster # both machines
errand -t 'cuda=True'                          # every cuda environment there is
```

Each environment gets its own [output directory](./output), so results sit side by side and the
summaries compare them. Use `--env NAME` when you want exactly one and mean it.

## Inside the work

```python
from errand import has_tag, tag

if has_tag( "driver=torch" ):
    ...
width = tag( "fp", "64" )
```

`tag( name )` gives a tag's value; `has_tag( expr )` reads the full
[expression language](/reference/expressions) against the selected environment.

### Skipping a file that does not apply

At the top of a file, **before the import**:

```python
import sys
from errand import has_tag
if not has_tag( "driver=torch" ):
    sys.exit( 0 )

import torch          # only reached where torch is the point
```

Finding entries means importing every candidate file, so an `import torch` at the top of a file runs
even when the selected environment is a jax one — and on a machine where torch is broken, that takes
down the whole session rather than one file. Exiting before the import is what prevents it.
`errand` catches the exit and reports the file as skipped.

::: tip Run by hand, `has_tag` says yes
Outside `errand` — a file you ran yourself — `has_tag` answers yes to everything. A file that
silently disappears is worse than an import that fails loudly.
:::

## Entry tags are the other kind

`-e` picks *what* runs, over the tags you wrote on an [entry](./declaring-work#tags-on-an-entry).
`-t` picks *where*, over the tags on an environment. They take the same expressions and never mix:

```bash
errand -e 'slow & !gpu' -t 'cuda & !remote'
```

## Next

[Running elsewhere](./remote) — what `Ssh` actually does.
