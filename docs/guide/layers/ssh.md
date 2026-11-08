# Ssh: running elsewhere

```python
Ssh( host, root = None, python = "python3", options = [ ], also = [ ] )
```

**Must be the first layer** — `errand.Env()` refuses a stack where it is not. Everything after it
runs on `host`, resolved against `root`: the project root over there, this one's path by default.
errand serializes the rest of the stack to a shell string and runs it over ssh, with an rsync push
before and a targeted rsync pull after:

```python
# errand-envs.py
import errand

errand.envs[ "box" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "/home/me/proj" ),
                                     errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def" ) ],
                                   cuda = True, remote = True )
```

```bash
errand run -k bench --env box "bench/**::*"
```

```text
  → gpu-box:/home/me/proj  env=box  tags=cuda
  rsync push → gpu-box:/home/me/proj
  ...
  rsync pull ← gpu-box:/home/me/proj [.errand/runs/bench/solvers.py/cost]
```

| | |
|---|---|
| `host` | what ssh reaches: a name of your `~/.ssh/config`, `user@host` |
| `root` | where the project goes over there. Default: the same path as here |
| `python` | the interpreter to start over there when no later layer overrides it |
| `options` | passed to ssh **and** to rsync — a port, an identity, a jump host |
| `also` | sibling checkouts the work needs ( `[ "../loom" ]` ), pushed to the same relative place over there |

## The paths are computed before the run happens

This is the whole trick, and everything else follows from it.

The same rules applied to the same entries and parameters give the same answer on both sides, so
**nothing has to be declared at runtime**, and the rest of the remote tree — which holds unrelated
runs from other days — stays put. Only the directories this invocation was going to write are
pulled back: its record in `.errand/runs/`, and its visible directory under `runs/` when `-o` asked
for one. Anything else the command writes comes back with `--pull DIR`.

Matrices are expanded on **this** side, one plain run per combination, each value crossing already
split. The remote side never sees a matrix; it sees plain runs.

## Through an interactive shell

The remote command goes through an interactive shell, because ssh runs non-interactively and would
otherwise never read the rc file that puts micromamba, cargo or nvm on `PATH`.

That is not a convenience; it is the difference between `micromamba -n myenv run` working and not
working on the other side.

## options go to ssh and to rsync

```python
Ssh( host = "gpu-box", root = "/home/me/proj",
     options = [ "-p", "2222", "-i", "~/.ssh/bench", "-J", "jump.example" ] )
```

rsync has to get the same options as ssh, or it reaches a different machine than ssh does — a
`StrictHostKeyChecking` you have decided about included. One list, both tools.

## What gets pushed

The push is an rsync of the project, with the obvious things excluded: `.git`, `runs`, `build`,
`dist`, `__pycache__`, `*.pyc`, `*.so`, `*.o`, `node_modules`, `.venv`, `*.egg-info`,
`.mypy_cache`, `.pytest_cache`, and by their exact paths what the project's layers build there ( an
image with its `.new`, `.prev` and `.part` ). Anything else found only over there is deleted, and
`errand` prints what went.

`runs` is excluded in both directions on purpose: the remote tree's own history is not yours to
overwrite, and the only runs you want back are the ones you just asked for.

## Building over there

An [image is built where it is used](../upkeep#where-an-image-gets-built): the recipe is a file
*here*, it is rsynced over, and `apptainer build` runs on that host with `fakeroot` and `scratch` as
declared. Where that host has no internet, `build_on = errand.Ssh( ... )` builds it on a machine that
has some, and the image is copied over ( see [Apptainer](./containers#apptainer) ).

## Adding an allocation

[`Slurm`](./slurm) stacks between the machine and the container, because that is the order the words
go in: that machine, an allocation on it, the container inside it.

```python
# errand-envs.py
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "login.hpc", root = "/home/me/proj" ),
                                         errand.Slurm( time = "2:00:00" ),
                                         errand.Apptainer( image = "containers/cuda.sif" ) ],
                                       cuda = True, remote = True )
```

## Results are pulled, not pushed

A finished remote run sits there until something collects it, which is what asking does. What to
pull is what the remote side's [plan](../environments#preparing-then-running) names: it is written
over there before anything runs, and brought back first. For a waiting run, the pull is the last
step. For a [detached](../detached) one, `errand status` and `errand watch` are what collect it.

## What only this machine can supply

A host name you can reach, a partition you are allowed to submit to — none of it can be committed
and none of it can be invented. It goes in an untracked `errand-envs.py`, and the files read after it
ask for it with `errand.value`, which takes a default:

```python
# errand-project.py  ( ssh_host and ssh_root come from errand-envs.py, which is read first )
import errand

errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = errand.value( "ssh_host", "gpu-box" ),
                                                     root = errand.value( "ssh_root", "/home/me/proj" ) ) ], cuda = True )
```

See [What only this machine can supply](../configuration#what-only-this-machine-can-supply).
