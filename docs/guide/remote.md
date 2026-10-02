# Running elsewhere

`Ssh` must be the **first** layer — `errand.Env()` refuses a stack where it is not. It resolves the rest of
the stack against the remote root, serializes it to a shell string and runs it over ssh, with an
rsync push before and a targeted rsync pull after:

```python
# errand-envs.py
import errand

errand.envs[ "box" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "/home/me/proj" ),
                                     errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def" ) ],
                                   cuda = True, remote = True )
```

```bash
errand -k bench --env box
```

```text
  → gpu-box:/home/me/proj  env=box  tags=cuda
  rsync push → gpu-box:/home/me/proj
  ...
  rsync pull ← gpu-box:/home/me/proj [runs/solvers/cost]
```

## The paths are computed before the run happens

This is the whole trick, and everything else follows from it.

The same rules applied to the same entries and parameters give the same answer on both sides, so
**nothing has to be declared at runtime**, and the rest of the remote tree — which holds unrelated
runs from other days — stays put. Only the directories this invocation was going to write are
pulled back.

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

rsync has to get the same options as ssh, or it reaches a different machine than ssh does. One list,
both tools.

`python` says which interpreter to start over there when no later layer overrides it (`python3` by
default).

## What gets pushed

The push is an rsync of the project, with the obvious things excluded: `.git`, `runs`, `build`,
`dist`, `__pycache__`, `*.pyc`, `*.so`, `*.o`, `node_modules`, `.venv`, `*.sif`, `*.egg-info`,
`.mypy_cache`, `.pytest_cache`.

`runs` is excluded in both directions on purpose: the remote tree's own history is not yours to
overwrite, and the only runs you want back are the ones you just asked for.

## Building over there

An [image is built where it is used](./upkeep#where-an-image-gets-built): the recipe is a file
*here*, it is rsynced over, and `apptainer build` runs on that host with `fakeroot` and `scratch` as
declared.

## Adding an allocation

`Slurm` stacks between the machine and the container, because that is the order the words go in:
that machine, an allocation on it, the container inside it.

```python
# errand-envs.py
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "login.hpc", root = "/home/me/proj" ),
                                         errand.Slurm( time = "2:00:00" ),
                                         errand.Apptainer( image = "containers/cuda.sif" ) ],
                                       cuda = True, remote = True )
```

What the entries ask for is handed to the scheduler rather than queued locally — see
[when somebody else owns the machine](./machine#when-somebody-else-owns-the-machine), including the
warning about `root` needing to be on a shared filesystem.

## Results are pulled, not pushed

A finished remote run sits there until something collects it, which is what asking does. For a
waiting run, the pull is the last step. For a [detached](./detached) one, `--status` and `--watch`
are what collect it.

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

See [What only this machine can supply](./configuration#what-only-this-machine-can-supply).

## Next

[Detached runs](./detached) — launching it and getting the shell back.
