# Choosing among environments (tags)

::: tip Advanced
With a handful of environments, `--env NAME` is all you need. Tags are for projects with many of
them, or one environment that covers a whole dimension: a precision, a backend, a problem class.
:::

A tag says what an environment *is*. There is nothing to declare: a tag is a keyword argument of
`errand.Env`, and every tag name becomes a flag.

```python
# errand-envs.py
errand.envs[ "gpu" ]     = errand.Env( CUDA, driver = "jax", cuda = True )
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( … ), errand.Slurm( … ) ] + CUDA, driver = "jax", cuda = True, fp = "64" )
```

```bash
errand run --driver jax python bench.py          # every environment that can be driver=jax
errand run --fp 64 --cuda yes python bench.py   # a tag flag always takes a value
errand run -t 'driver=jax & fp=64 & !remote' python bench.py   # -t, --env-tags: an expression
errand envs                                      # the tags of each, in the second column
```

`-t` reads the [expression language](/reference/expressions). A tag flag or an expression selects
**every** environment that fits, not one: that is the point of them.

## Saying nothing means every value

An environment that does not mention `fp` covers every precision. `--fp 32` selects it, and runs in
it with `fp=32` among its tags. One that says `fp = "64"` is only selected for that value, and
`fp = "32|64"` for either; naming one with `--env cluster --fp 32` when it cannot have that value is
an error, not an override.

```bash
errand run --grid=, --fp 32,64 python bench.py   # two runs in each environment that covers both
```

That is what makes a tag a *dimension* rather than a label: you declare one environment, and the
values you want to sweep cross it. A tag value cannot hold the [`--grid`](./matrices) separator; a
comma without `--grid` is an error that says how to ask for several values.

## Tags only select

A tag does nothing to the process by itself. What an environment does to it is a
[`Vars`](./layers/vars) layer, like everything else, and that layer can read the selection back:

```python
# errand-envs.py
errand.envs[ "gpu" ] = errand.Env( CUDA + [ errand.Vars( lambda t: { "MYPROJ_FTYPE": f"FP{ t.get( 'fp', '64' ) }" } ) ],
                                   driver = "jax", cuda = True )
```

Without that, each value would need its own environment, written twice: once to be matched by
`--fp`, once to be handed to the child. There would be a `local32` beside every `local` and a
`gpu32` beside every `gpu`.

The work itself reads an ordinary variable, and names no machine:

```python
# src/solver.py -- knows nothing about errand
FTYPE = os.environ.get( "MYPROJ_FTYPE", "FP64" )
```

## Reading the tags from the work

```python
from errand import has_tag, tag

if has_tag( "driver=torch" ):
    ...
width = tag( "fp", "64" )
```

`tag( name, default )` gives a tag's value; `has_tag( expr )` matches an
[expression](/reference/expressions) against the selected environment. Outside errand — a file run
by hand — `has_tag` answers yes to everything, so a file never silently disappears.

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
even when the selected environment is a jax one, and on a machine where torch is broken it takes the
whole session down. Exiting before the import prevents it; errand reports the file as skipped.

## Environment tags and entry tags

`-t` picks *where*, over the tags of environments. `-e` picks *what*, over the tags written on
[entries](./declaring-work). They take the same expressions and never mix:

```bash
errand run -e 'slow & !gpu' -t 'cuda & !remote' 'tests/**::*'
```

## Next

[Running a command](./running).
