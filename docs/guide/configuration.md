# Configuration

None is needed. `errand run <target>` with no configuration runs a file, a command or the entries
named, in the interpreter you started it with. Configuration says where else to run, and what the
project's tests are.

```python
# errand-project.py: what the project does. Versioned.
import errand

errand.configure( src = [ "src" ] )
errand.runners.replace( errand.Catch2( dir = "tests/cpp", build = "make -C tests/cpp" ) )
errand.default_run = [ "tests/**::*" ]          # what a bare `errand run` runs
```

```python
# errand-envs.py: where you run it.
import errand

errand.envs[ "local" ] = errand.Env( [ errand.Micromamba( "myenv", python = "3.13", requirements = "requirements.txt" ) ] )
errand.envs[ "gpu" ]   = errand.Env( [ errand.Ssh( host = "gpu-box", root = "/scratch/me/proj" ),
                                       errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def" ) ],
                                     cuda = True )
errand.default_env = "local"
```

## The files

Every **`errand-*.py`** at the root of the project is read, `errand-vars.py` first, then the others
in name order. They are ordinary Python, loaded by path, with nothing to call and nothing to
return. Three names are the convention:

| file | holds | in git |
|---|---|---|
| `errand-project.py` | what the project does: runners, `default_run`, `configure` | yes |
| `errand-envs.py` | where you run it: the environments | no, unless it names no machine of yours |
| `errand-vars.py` | what only this machine knows: hosts, paths, partitions | never |

The root is the nearest directory, walking up from the current one, that holds an `errand-*.py`;
`--root` overrides it. These files are never taken for files of entries. They are modules of one
private package rooted at the project, so `from .helpers import X` reads `helpers.py` beside them.

A directory holding an `errand-*.py` of its own is **another project**, and discovery does not walk
into it: its entries would run with this project's settings, which is to say wrongly.

## Starting from errand init

```bash
errand init
```

It reads the directory and writes an `errand-project.py` holding, in comments, the runner lines
that fit the suites it found and a `default_run` to start from, and an `errand-envs.py` holding a
commented stack of layers to adapt. Nothing is active until you uncomment it. In a git checkout it
adds `errand-outputs/`, `errand-envs.py` and `errand-vars.py` to `.gitignore`.

It does nothing where an `errand-*.py` already exists; `errand init --force` rewrites
`errand-project.py` ( an existing `errand-envs.py` is kept either way ).

## configure

```python
errand.configure(
    outputs_directory = "errand-outputs",  # everything errand writes for the project
    builds_directory  = None,              # what errand builds, elsewhere: another disk, a shared directory
    build             = "build",           # where runners' builds go, one directory per environment
    src               = [ ],               # paths prepended to every child's PYTHONPATH
    exclude           = [ ],               # directories discovery must not walk into
    zones             = { },               # where a run writes in the project's copy over there
)
```

| | |
|---|---|
| `outputs_directory` | where errand writes: `runs/` ( the record of every run ), `builds/`, `state/`. See [Results and records](/guide/output). Relative to the project root, or absolute. `ERRAND_OUTPUTS_DIR` overrides it on one machine; over ssh, [`errand_outputs_directory`](/guide/layers/ssh) does |
| `builds_directory` | what errand builds ( Windows images ) and its records of it, elsewhere than `errand-outputs/builds/`. Relative to the root, or absolute: then the same path on every machine |
| `build` | where a runner's build goes, `build/<env>/`: the `{build_dir}` of [Catch2](/guide/runners/catch2) |
| `src` | your package layout, so a child process imports your code without an install |
| `exclude` | vendored code, fixtures, a copy of something that should not be imported |
| `zones` | the paths a run writes in the project's copy over ssh, each a kind: `{ "/results": "back" }` ( written there, brought back ), `{ "cache": "build" }` ( built there ), `{ "/data-cache": "cache" }` ( added to on both sides, never replaced nor deleted ). A push never sends into a `back` or `build` zone nor deletes in one; into a `cache` it sends only what the copy lacks. A leading `/` anchors a path at the root; without, a name matches anywhere. See [Ssh](/guide/layers/ssh) |

An unknown setting is a `TypeError` listing the ones that exist. The `out` and `state` of an older
errand are ignored with a warning: what they named is in `errand-outputs/` now.
[Where errand writes](/guide/storage) gathers every place errand writes to.

## default_run

```python
errand.default_run = [ "tests/**::*", "bench/solvers.py::*", "make" ]
```

What a bare `errand run` runs: targets written from the project root, as on the command line, and
everything they name. With none, `errand run` alone prints the help.

## envs, default_env and runners

```python
errand.envs[ "name" ] = errand.Env( [ layers… ], **tags )
errand.default_env = "name"
```

`errand.envs[ name ] = errand.Env( … )` declares an [environment](/guide/environments): a stack of
[layers](/guide/layers/), outermost first, and [tags](/guide/tags) as keyword arguments. `Ssh` must
be the first layer; `Windows` and `WindowsBox` are first or right after an `Ssh`. A name or a tag
value cannot hold a comma, which means several values on the command line.

The default environment is `errand.default_env`, else the first one declared, else the interpreter
errand runs with. Naming one that does not exist is an error.

`errand.runners` says what runs which file; `errand.runners.replace( … )` puts a configured runner
in place of a default one. See [Running a suite](/guide/runners/).

## What only this machine can supply

A host name, a remote root, a partition you may submit to: none of it can be committed, and none of
it can be invented. It goes in an untracked **`errand-vars.py`**, read before the other files:

```python
# errand-vars.py -- not tracked
ssh_host = "gpu-box"
ssh_root = "/home/me/scratch/errand"
slurm    = { "partition": "gpu", "time": "00:10:00" }
```

Every plain value a project file defines ( not its imports, functions or classes ) is readable by
the files read after it, and by entries.

### Project files read it with value

A project file is read once, before anything, and must do without what it does not find, so it
asks with a default:

```python
# errand-envs.py
import errand

errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = errand.value( "ssh_host", "gpu-box" ),
                                                     root = errand.value( "ssh_root", "/home/me/proj" ) ) ],
                                       cuda = True )
```

That keeps the host out of git while the declaration that uses it can be committed.

### An entry asks with need

```python
from errand import test, need

if test( "it runs over there" ):
    host = need( "ssh_host", "a machine you can ssh to without a password", example = "gpu-box" )
```

When it is not there the entry is **skipped**, never passed, and the run ends with a block saying
what was missing and what to write where:

```text
  3 skipped:
    it runs over there  (test_ssh.py:18)  needs `ssh_host` -- a machine you can ssh to without a password
      errand-vars.py does not exist yet. Create it (it is not tracked) with:
          ssh_host = 'gpu-box'
```

`have( key )` asks without skipping. `skip( "reason" )` skips for any other reason. A skip is its
own status, in the output and in `result.yaml`: a suite that tested nothing must not look like a
suite that passed. Use `need` only for what genuinely cannot be defaulted.

## Environments declared by a package

`errand.providers` is a list of functions that declare environments before the project does: each
takes the project root and fills `errand.envs`. An installed package can declare one under the
entry point group `errand.envs`. They run after `errand-vars.py`, so they can read its values, and
before the other files, which can redefine what they declared. An environment a provider declared
is never the default. One that cannot be reached from here is declared with
[`Missing`](/guide/layers/missing).
