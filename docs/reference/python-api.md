# Python API

Every public name is in `errand.__all__`. A file of work needs these:

```python
from errand import entry, test, bench, track, experiment, Param, Args
from errand import has_tag, tag, out_dir
from errand import step, view
from errand import need, have, skip, Skipped
```

A project file needs `import errand`, then:

| | |
|---|---|
| declaring | `configure`, `envs`, `Env`, `default_env`, `default_run`, `runners`, `providers`, `value` |
| layers | `Vars` `Venv` `Micromamba` `Conda` `Uv` `Nix` `Guix` `Module` `Apptainer` `Docker` `Podman` `Ssh` `Slurm` `Mpi` `Preload` `Windows` `WindowsBox` `Missing` |
| runners | `Runner` `Level` `Outcome` `RunContext` `Errand` `Pytest` `Catch2` `Cargo` `Python` `Executable` |
| the command line | `main` |

::: tip The import surface is cheap
Finding entries means importing **every** candidate file, so `import errand` loads only the
standard library. Everything else is reached lazily, on first use.
:::

## Declaring work

::: warning Being reworked
errand's own entries are becoming a protocol any program can follow; see
[Writing entries](/guide/declaring-work).
:::

### entry

```python
entry( name, tags = None, /, **kw ) -> Args | False
```

`name` and `tags` are positional-only; `tags = [ … ]` is accepted as a keyword too. Every other
keyword is a **parameter** ( a `Param` ), or `ranks`: MPI processes, each running the body,
overridden by `--ranks` ( see [Several processes](/guide/mpi) ). Anything else is a `TypeError`
that says which, and where what it meant went: `exclusive`, `cpus`, `ram`, `gpus` are the
command's ( `-x`, `--cpus`… ), `bulk` is `errand.default_run`.

```python
if p := entry( "solve", n = Param( 1000 ), ranks = 4 ):
    ...
```

Returns `False` while the file is read to find its entries, and while another entry of the file is
the one running. Returns an `Args` for the entry that is running.

### test, track, bench, experiment

```python
test( name, tags = None, /, **kw )
track( name, tags = None, /, **kw )
bench( name, tags = None, /, **kw )
experiment( name, tags = None, /, **kw )
```

`entry` under four names, so that the file says what the work is. They behave the same: which
ones run is the target's to say, and the machine to itself is `-x`.

### Param

```python
Param( default, *, help = "", choices = None )
```

The type comes from the default: `Param( 1000 )` reads its flag as an int. `help` shows in
`errand list`; `choices` is checked before anything runs. Several values make a grid only under
[`--grid`](/guide/matrices).

### Args

What the guard hands back:

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

Does the selected environment satisfy the [expression](./expressions)? Outside errand, a file run
by hand, it answers **yes to everything**: a file that silently disappears is worse than an import
that fails loudly.

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

The value of one tag of the selected environment, or `default`.

### out_dir

```python
out_dir( ) -> Path
```

This run's own directory, the one `p.out_dir` gives. Outside errand it answers `./out`.

## Saying where the run is

### step

```python
step( text: str = None, *, done: float = None, **values: float )
```

Where the run is now: `text` as a person reads it, `done` a fraction from 0 to 1, and named numbers,
one curve each. Written to the run's journal, `$ERRAND_STEPS`, ten times per second at most; outside
errand it does nothing. → [Where a run is: steps](/guide/steps)

### view

```python
view( path, title: str = None, content: str | bytes = None )
```

`path`, relative to the run's directory, is a file worth watching as it evolves. With `content`,
errand writes it atomically. → [Where a run is: steps](/guide/steps#view-a-file-that-evolves)

## What only this machine can supply

These read the plain values of the project's `errand-*.py` files, conventionally an untracked
`errand-vars.py`: see [Configuration](/guide/configuration#what-only-this-machine-can-supply).

| | |
|---|---|
| `need( key, what = "", *, example = None )` | the value, or raises `Skipped`: the entry is a `SKIP`, and the run ends saying what to write where. `what` is the sentence, `example` the value to suggest |
| `have( key ) -> bool` | is it there? Never raises |
| `skip( reason, hint = None )` | raises `Skipped`: this entry does not apply today |
| `Skipped( reason, hint = None )` | the exception behind the two above |
| `errand.value( key, default = None )` | for project files: the value, or `default`. Never skips |

## Declaring a project

In the project's `errand-*.py` files; see [Configuration](/guide/configuration).

### configure

```python
errand.configure( outputs_directory = "errand-outputs", builds_directory = None, build = "build",
                  src = [ ], exclude = [ ], zones = { } )
```

| | |
|---|---|
| `outputs_directory` | where errand writes for the project: `runs/`, `builds/`, `state/`. Relative to the root, or absolute; `ERRAND_OUTPUTS_DIR` overrides it on one machine |
| `builds_directory` | what errand builds, elsewhere than `errand-outputs/builds/`. Relative to the root, or absolute |
| `build` | where runners' builds go, one directory per environment: `build/<env>/` |
| `src` | paths prepended to every child's `PYTHONPATH` |
| `exclude` | directories discovery must not walk into |
| `zones` | `{ path: "back" \| "build" }`: where a run writes in the project's copy over ssh |

An unknown setting is a `TypeError` listing the ones that exist.

### envs, Env, default_env

```python
errand.envs[ name ] = errand.Env( stack = ( ), prepare = None, tools = None, **tags )
errand.default_env = "name"          # optional: else the first one declared
```

Declares an [environment](/guide/environments); the key is its name. `stack` is a list of
[layers](/guide/layers/), outermost first: `Ssh` must be first, `Windows` and `WindowsBox` first or
right after an `Ssh`. `prepare`, when given, is the list the [preparation](/guide/environments#preparing-then-running)
goes through instead, on the same machine or on another one, whose build is then carried to the
run's copy. `tools` names what the runners start there,
where the usual name is wrong ( [Tools](/guide/environments#tools-an-environment-names) ). Keyword arguments are its [tags](/guide/tags). A name or a
tag value cannot hold a comma. Only an `Env` can be stored.

### default_run

```python
errand.default_run = [ "tests/**::*" ]
```

What a bare `errand run` runs: targets from the project root. With none, it prints the help.

### providers

```python
errand.providers.append( declare )       # declare( root: Path ) fills errand.envs
```

Functions that declare environments before the project's files ( after `errand-vars.py` ). An
installed package declares one under the entry point group `errand.envs`. An environment a provider
declared is never the default.

### runners

```python
errand.runners.replace( runner ) -> runner
errand.runners[ "name" ] = runner
del errand.runners[ "cargo" ]
```

A dict, name → runner, filled with the runners errand comes with. `replace` puts a configured runner
in place of the default one of its kind; another name adds one, which `-r NAME` picks. See
[Running a suite](/guide/runners/).

## Layers

Every argument is a keyword with a default unless shown otherwise.

| layer | signature | page |
|---|---|---|
| `Vars` | `Vars( values )`: a dict, or a function of the selected tags returning one | [Vars](/guide/layers/vars) |
| `Venv` | `Venv( python = "python", requirements = None, pip = [ ], create = False )` | [Venv and Uv](/guide/layers/venv) |
| `Uv` | `Uv( path = ".venv", python = None, requirements = None, pip = [ ] )` | [Venv and Uv](/guide/layers/venv) |
| `Micromamba` | `Micromamba( name, python = None, channels = [ "conda-forge" ], packages = [ ], requirements = None, pip = [ ], root_prefix = None, executable = None )` | [Micromamba](/guide/layers/micromamba) |
| `Conda` | the same arguments as `Micromamba`, through `conda` | [Micromamba](/guide/layers/micromamba) |
| `Nix` | `Nix( flake = ".", shell = None )` | [Nix and Guix](/guide/layers/nix-guix) |
| `Guix` | `Guix( manifest = None, packages = [ ] )` | [Nix and Guix](/guide/layers/nix-guix) |
| `Module` | `Module( names )`: a list, `[ "gcc/13", "openmpi" ]` | [Module](/guide/layers/module) |
| `Apptainer` | `Apptainer( image, recipe = None, flags = [ ], mounts = { }, pip = [ ], fakeroot = False, scratch = None, build_flags = [ ], build_on = None, install = None, run_from = None, exe = "apptainer" )` | [Containers](/guide/layers/containers) |
| `Docker` | `Docker( image, recipe = None, flags = [ ], mounts = { }, pip = [ ], engine = "docker", user = "caller" )` | [Containers](/guide/layers/containers) |
| `Podman` | `Docker` with `engine = "podman"`, `user = None` | [Containers](/guide/layers/containers) |
| `Ssh` | `Ssh( host, root = None, python = "python3", options = [ ], also = [ ], errand_outputs_directory = None, transfer = None, user = None, jump = None )` | [Ssh](/guide/layers/ssh) |
| `Slurm` | `Slurm( partition = None, nodes = None, cpus = None, gpus = None, time = None, account = None, nodelist = None, qos = None, watch = None, ntasks_per_node = None, mpi = None, extra = [ ], keep_alive = None, allocation = None )` | [Slurm](/guide/layers/slurm) |
| `Mpi` | `Mpi( launcher = "mpiexec", np = "-n", flags = [ ] )` | [MPI](/guide/layers/mpi) |
| `Preload` | `Preload( *modules, learn = True )` | [Preload](/guide/layers/preload) |
| `Windows` | `Windows( iso = None, key = None, index = 1, cpus = 4, ram = "8G", disk = "64G", msvc = True, python = "3.13.16", provision = [ ], fetch = [ ], also = [ ], keep = "5m", data = "32G", root = None )` | [Windows](/guide/layers/windows) |
| `WindowsBox` | `WindowsBox( python = None, msvc = False, provision = [ ], fetch = [ ], also = [ ], root = None )` | [WindowsBox](/guide/layers/windows-box) |
| `Missing` | `Missing( what, hint = None )` | [Missing](/guide/layers/missing) |

## Runners

| | |
|---|---|
| `Errand()` | errand's own entries: a `.py` that imports errand |
| `Pytest( dirs = None, patterns = ( "test_*.py", "*_test.py" ), args = ( ), python = None, install = "auto", spec = "pytest" )` | [Pytest](/guide/runners/pytest) |
| `Catch2( dir = None, pattern = "test_*.cpp", build = None, binary = None, args = ( ) )` | [Catch2](/guide/runners/catch2) |
| `Cargo( manifest = None, args = ( ), release = False )` | [Cargo](/guide/runners/cargo) |
| `Python()`, `Executable()` | a file or a command run whole: [Scripts and executables](/guide/runners/scripts) |
| `Runner`, `Level`, `Outcome`, `RunContext` | for a runner of your own: [Writing a runner](/guide/runners/writing) |

## main

```python
errand.main( argv = None ) -> int
```

The command line, from Python: `errand.main( [ "run", "--env", "gpu", "train.py" ] )` returns the
exit code. `argv = None` reads `sys.argv`.
