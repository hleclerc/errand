# Python API

Everything a file of work needs comes from `errand` itself:

```python
from errand import entry, test, bench, track, experiment, Param
from errand import has_tag, tag, out_dir
from errand import need, have, skip
```

And everything a project file needs:

```python
import errand       # then errand.configure, errand.envs, errand.Env, errand.default_env,
                    # errand.provider, errand.value, and the layers and providers by name:
                    # Vars Venv Micromamba Conda Uv Nix Guix Module Apptainer Docker Podman
                    # Ssh Slurm  --  Provider Pytest Catch2 Cargo Outcome RunContext
```

::: tip The import surface is deliberately cheap
Finding entries means importing **every** candidate file, so the declaration surface imports only
the standard library. The command line, the environments and the layers are reached through a lazy
`__getattr__`, so an entry file never pays for them.
:::

## Declaring work

### entry

```python
entry( name, tags = None, /, **kw ) -> Args | False
```

`name` and `tags` are positional-only, and `tags = [ … ]` is accepted as a keyword too. Every other
keyword must be a **parameter** (a `Param`), a **trait**, or a **resource** — anything else is a
`TypeError` that says which.

```python
if p := entry( "solve", n = Param( 1000 ), keep = True, cpus = 4 ):
    ...
```

| traits | default | |
|---|---|---|
| `bulk` | `True` | picked up by a bare `errand`, with no pattern |
| `keep` | `False` | its numbers are kept and compared date to date |
| `exclusive` | `False` | it needs the machine to itself |
| `stable_path` | `False` | `latest/` is what you are meant to open |

| resources | |
|---|---|
| `cpus` | a count |
| `ram` | `"8G"`, `"512M"` |
| `gpus` | a count — and the cards are [assigned, not merely counted](/guide/machine#a-card-is-assigned-not-merely-counted) |

Returns `False` while the file is being read for collection, and while another entry in it is the
one being run. Returns an `Args` for the entry that is running, which is why the walrus reads the
way it does.

### test / bench / track / experiment

```python
test( name, tags = None, /, **kw )        # bulk
track( name, tags = None, /, **kw )       # keep, not bulk
bench( name, tags = None, /, **kw )       # keep, exclusive, not bulk
experiment( name, tags = None, /, **kw )  # stable_path, not bulk
```

`track` is for numbers you want to follow — any numbers; `bench` is `track` measured alone, for
timings and anything else a neighbour would disturb. Four lines of Python over `entry`, and you can
write a fifth the same way. Any trait can be
overridden on the spot:

```python
if p := bench( "cheap probe", exclusive = False ):
```

### Param

```python
Param( default, *, help = "", choices = None )
```

The **type comes from the default** — `Param( 1000 )` reads its flag as an int. `help` shows in
`errand --help` and in [the screen](/guide/tui); `choices` is checked before anything runs. Every
parameter takes a value on the command line, and a comma in that value is a
[matrix](/guide/matrices).

### Args — what the guard hands back

| | |
|---|---|
| `p.<name>` | each declared parameter, resolved |
| `p.out_dir` | `Path` to this run's own directory, already created |
| `p.results` | a dict; it ends up in `result.yaml`. Numeric values are summarized above the run |

## Reading the environment

### has_tag

```python
has_tag( expr: str ) -> bool
```

Does the selected environment satisfy the [expression](./expressions)? Outside errand — a file you
ran by hand — it answers **yes to everything**: a file that silently disappears is worse than an
import that fails loudly.

The use for it is at the top of a file, before an import that only makes sense somewhere:

```python
import sys
from errand import has_tag
if not has_tag( "driver=torch" ):
    sys.exit( 0 )
import torch
```

### tag

```python
tag( name: str, default = None )
```

The value of one tag of the selected environment.

### out_dir

```python
out_dir( ) -> Path
```

This run's own directory, the same one `p.out_dir` gives. Outside errand it answers `./out`, so an
ad-hoc run still has somewhere to put its files.

## What only this machine can supply

These read an untracked `errand-envs.py` beside the other project files — see
[Configuration](/guide/configuration#what-only-this-machine-can-supply).

### need

```python
need( key: str, what: str = "", *, example = None )
```

The value, or **`Skipped`** — which the runner turns into a `SKIP` status, with a block at the end of
the run saying what was missing and exactly what to write where. `what` is the human sentence;
`example` is what goes in that block as the line to add.

### have

```python
have( key: str ) -> bool
```

Is it there? Asks without raising.

### skip

```python
skip( reason, hint = None )
```

Says it directly, for anything else that makes an entry inapplicable today. A skip is its own
status, in the output and in `result.yaml`: a suite that quietly tested nothing must not be able to
look like a suite that passed.

### value

```python
errand.value( key: str, default = None )
```

For the **project files**, which have not got the option of not running — it is read once, before
anything, and what it does not find it must do without. So this one takes a default rather than
raising.

## Declaring a project

Lives in the project's `errand-*.py` files — [`errand-project.py`](/guide/configuration) for what the
project does, `errand-envs.py` for where it runs.

### configure

```python
errand.configure( out = "runs", src = [ ], exclude = [ ] )
```

| | |
|---|---|
| `out` | where the output tree goes |
| `src` | paths prepended to every child's `PYTHONPATH` |
| `exclude` | directories discovery must not walk into |

An unknown setting is a `TypeError` listing the ones that exist.

### envs and Env

```python
errand.envs[ name: str ] = errand.Env( stack = ( ), **tags )
errand.default_env = "name"          # optional; else the first one declared
```

Declares an [environment](/guide/environments): the key is its name. The stack is a list of
[layers](./layers), read outside in; `Ssh` must be the first of them, and `errand.Env` refuses a
stack where it is not. Keyword arguments are its [tags](/guide/tags). Only an `Env` can be stored.

`errand.default_env` is what is used when nothing is asked for. Naming an environment that does
not exist is an error.

### provider

```python
errand.provider( p ) -> p
```

Adopts a suite that already exists — see the [provider reference](./providers).
