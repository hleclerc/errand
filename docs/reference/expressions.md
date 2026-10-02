# Tag expressions

One grammar, three readers:

| | over | |
|---|---|---|
| `-t`, `--env-tags` | [environment tags](/guide/tags) | which places run it |
| `-e`, `--entry-tags` | [entry tags](/guide/declaring-work#tags-on-an-entry) | which work runs |
| `has_tag( … )` | the selected environment, from inside a file | whether this file applies |

## The grammar

Literals, `&`, `|`, `!`, and `=` for a valued tag. **No parentheses** — an expression that needs
them is a sign the dimensions are wrong.

Precedence is the usual one: `!` binds tighter than `&`, which binds tighter than `|`. So

```
a & !b | c
```

reads as `(a & !b) | c`.

| | |
|---|---|
| `cuda` | the tag is present |
| `!cuda` | it is not |
| `fp=64` | it is present with that value |
| `a & b` | both |
| `a \| b` | either |
| *(empty)* | everything matches |

Whitespace around names and operators is ignored. An empty tag name — a stray `&` — is an error
naming the literal.

## Values

`=` compares as text, with the obvious courtesies:

| declared | matched by |
|---|---|
| `cuda = True` | `cuda`, `cuda=True`, `cuda=yes`, `cuda=1` |
| `cuda = False` | `cuda=False`, `cuda=no`, `cuda=0` — and `cuda` alone matches too, the tag being *present* |
| `fp = "64"` | `fp=64` |
| `fp = 64` | `fp=64` — the int and the string are the same here |

A tag used **without** `=` asks only whether it is there. That is why `cuda` matches
`cuda = False`: the environment did mention it. Say `cuda=True` when you mean the value.

## Examples

```bash
errand -t 'cuda'                      # every environment that mentions cuda
errand -t 'cuda=True'                 # every one where it is on
errand -t 'jax & fp=64 & !remote'     # here, in double, on jax
errand -t 'cuda | boxed'              # either kind of container
errand -e 'slow & !gpu'               # the slow entries that are not gpu ones
errand -e '!legacy' -k bench          # benchmarks, minus the old ones
```

```python
if not has_tag( "driver=torch" ):
    sys.exit( 0 )
import torch
```

## What an expression does not do

It **selects**; it does not configure. An environment that satisfies `fp=32` is chosen by it, and
what the child process then *sees* is a [`Vars` layer's](/guide/tags#tags-only-select) business.

And remember that **saying nothing means every value**: an environment that never mentions `fp` is
selected by `--fp 32` and by `--fp 64` alike, so `--fp 32,64` is two runs in it. An environment that
pins `fp = "64"` is only ever selected for that one.
