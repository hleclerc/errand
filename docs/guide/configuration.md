# Configuration

None is needed. `errand` with no configuration at all finds your entries and runs them in the
interpreter you started it with.

You do not have to write the file from a blank page: **`errand --init`** reads the directory,
writes the `errandfile.py` that says what errand would otherwise guess (see
[Start from what you have](./start)), makes `runs/`, adds it to `.gitignore` if there is a git
here, and leaves a commented stack of layers ready to adapt. It never overwrites.

To declare environments, tags and the rest, put an **`errandfile.py`** at the root of the project —
the same idea as a Makefile or a Dockerfile. It is ordinary Python, loaded once by path and under a
private name, with no entry point to call and nothing to return:

```python
from errand import configure, env, provider, Micromamba, Apptainer, Catch2

configure( out = "runs", src = [ "core/src", "app/src" ] )

env( "local", [ Micromamba( "myenv", python = "3.13", requirements = "requirements.txt" ) ],
     driver = "jax" )
env( "gpu", [ Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def" ) ],
     driver = "jax", cuda = True )

provider( Catch2( dir = "tests/cpp" ) )
```

::: warning Do not call it `errand.py`
A module of that name at the root of a project **shadows the package** wherever the root is on
`sys.path`, which is to say for `python -m errand` and for any script started from there. `errand`
says so out loud when it finds one. The `errandfile.py` spelling has no such problem.
:::

The root is found by walking up from the current directory looking for an `errandfile.py`;
`--root` overrides it.

## configure

```python
configure(
    out     = "runs",   # where the output tree goes
    src     = [ ],      # paths prepended to every child's PYTHONPATH
    exclude = [ ],      # directories discovery must not walk into
    default = None,     # the environment used when nothing is asked for
)
```

| | |
|---|---|
| `out` | the one directory errand writes to. See [the output tree](./output) |
| `src` | your package layout, so a child process can import your code without an install |
| `exclude` | vendored code, fixtures, a copy of something that would be imported and should not be |
| `default` | the name of an [environment](./environments). With none, errand runs in the interpreter you started it with |

`--out` and `--root` override the first and the project root respectively, which is what the
children errand starts for itself use.

## env and provider

`env( name, [ layers… ], **tags )` declares an [environment](./environments); its keyword arguments
are its [tags](./tags). `Ssh` must be the first layer, and `env` refuses a stack where it is not.

`provider( … )` adopts a suite that already exists — see [Other languages](./providers).

## Subcommands: there are none, on purpose

There is no mechanism for project-specific subcommands, because there does not need to be one:
something you want to run is an entry, and `bulk = False` keeps it out of the way until you name it.

```python
if entry( "docs", bulk = False ):
    build_docs( )
```

```bash
errand docs
```

## What only this machine can supply

Reaching an ssh host, or a queue you are allowed to submit to, depends on who is running. None of it
can be committed and none of it can be invented, so it goes in an untracked **`errand.local.py`**
beside the errandfile:

```python
# errand.local.py -- not tracked
ssh_host = "gpu-box"
ssh_root = "/home/me/scratch/errand"
slurm    = { "partition": "gpu", "time": "00:10:00" }
```

### An entry asks with need

```python
from errand import test, need

if test( "it runs over there" ):
    host = need( "ssh_host", "a machine you can ssh to without a password", example = "gpu-box" )
```

When it is not there the entry is **skipped** — never passed — and the run ends with a block saying
what was missing and exactly what to write where:

```text
  3 skipped:
    it runs over there  (test_ssh.py:18)  needs `ssh_host` -- a machine you can ssh to without a password
      errand.local.py does not exist yet. Create it (it is not tracked) with:
          ssh_host = 'gpu-box'
```

`have( key )` asks without raising. `skip( "reason" )` says it directly, for anything else that
makes an entry inapplicable today.

::: tip A skip is not a pass
It is its own status, in the output and in `result.yaml`. A suite that quietly tested nothing must
not be able to look like a suite that passed.
:::

### The errandfile reads it with value

An entry has the option of not running; a project file has not — it is read once, before anything,
and what it does not find it must do without. So it asks with `value`, which takes a default:

```python
from errand.local import value

env( "cluster", [ Ssh( host = value( "ssh_host", "gpu-box" ),
                       root = value( "ssh_root", "/home/me/proj" ) ) ], cuda = True )
```

That is what lets a host name, a remote root or a scratch directory stay out of git while the
declaration that uses them is committed, with a default that works here.

### Reach for it sparingly

`ssh localhost` is a real ssh, a real rsync and a real round trip through a directory that is not
the project's — only the hardware is shared, and the hardware is rarely what is being tested. A
suite that exercises the remote path on anyone's machine is worth more than one that waits for a
cluster.

Use `need` only for what genuinely cannot be defaulted.

## Another project inside this one

A directory holding a config file of its own is **another project**, and discovery does not walk into
it: its entries would run with this project's `src`, providers and environments, which is to say
wrongly.

## Next

[Other languages](./providers) — putting a suite you already have under errand.
