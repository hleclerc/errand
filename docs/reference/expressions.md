# Tag expressions

```bash
errand run -t 'cuda & fp=64' train.py           # the environments with cuda, in double
errand run -e 'slow & !gpu' '**::*'             # the slow tests that are not gpu ones
```

One grammar, three readers:

| | reads | to decide |
|---|---|---|
| `-t`, `--env-tags` | [environment tags](/guide/tags) | which places run it |
| `-e`, `--entry-tags` | the tags of [errand's own entries](/guide/declaring-work#tags-on-an-entry) | which entries run |
| `has_tag( … )` | the selected environment, from inside a file | whether this file applies |

## The grammar

| | |
|---|---|
| `cuda` | the tag is present |
| `!cuda` | it is not |
| `fp=64` | it is present with that value |
| `a & b` | both |
| `a \| b` | either |
| *(empty)* | everything matches |

**No parentheses**: an expression that needs them is a sign the dimensions are wrong. `!` binds
tighter than `&`, which binds tighter than `|`, so `a & !b | c` reads as `(a & !b) | c`.

Whitespace around names and operators is ignored. A literal with no name, such as `=64` or a lone
`!`, is an error naming it. A stray `&` is ignored; a stray `|` adds an empty alternative, which
matches everything: `cuda |` selects every environment.

## Values

`=` compares as text, with the obvious courtesies:

| declared | matched by |
|---|---|
| `cuda = True` | `cuda`, `cuda=True`, `cuda=yes`, `cuda=1` |
| `cuda = False` | `cuda=False`, `cuda=no`, `cuda=0`, and `cuda` alone: the tag is *present* |
| `fp = "64"` | `fp=64` |
| `fp = 64` | `fp=64`: the int and the string are the same here |

A tag used **without** `=` asks only whether it is there. That is why `cuda` matches
`cuda = False`: the environment did mention it. Write `cuda=True` when you mean the value.

## Examples

```bash
errand run -t 'cuda'                   # every environment that mentions cuda
errand run -t 'cuda=True'              # every one where it is on
errand run -t 'jax & fp=64 & !remote'  # on jax, in double, not remote
errand run -t 'cuda | boxed'           # either kind
errand run -e '!legacy' 'bench/**::*'  # benchmarks, minus the old ones
```

```python
if not has_tag( "driver=torch" ):
    sys.exit( 0 )
import torch
```

## What an expression does not do

It **selects**; it does not configure. An environment that satisfies `fp=32` is chosen by it; what
the child process then *sees* is a [`Vars`](/guide/layers/vars) layer's business.

**Saying nothing means every value**: an environment that never mentions `fp` is selected by
`--fp 32` and by `--fp 64` alike, so `--grid=, --fp 32,64` is two runs in it. One that pins
`fp = "64"` is only ever selected for that value. See [Tags](/guide/tags).
