# Ssh: running elsewhere

```python
Ssh( host, root = None, python = "python3", options = [ ], also = [ ],
     errand_outputs_directory = None, user = None, jump = None )
```

Everything after it runs on `host`. The project is pushed there before the command, and what the
command wrote is brought back after it. Both go through errand's agent over there, so that
machine needs ssh and a Python, nothing else.

```python
# errand-envs.py
import errand

errand.envs[ "box" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "/home/me/proj" ),
                                     errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def" ) ] )
```

```bash
errand run --env box -o python train.py
```

```text
box · 1 entry  box@gpu-box
▸ python  python · args=train.py
  │ epoch 1  loss 0.41
PASS python  12 min 03 s
```

The push before and the pull after are said at the bottom of the terminal while they last
( `↑ sync push → gpu-box:/home/me/proj · 3 s` ), then gone: what they came to — files, bytes,
seconds — is in the run's journal, `steps.jsonl` ( [Results and records](../output#on-the-terminal) ).

It **must be the first layer**: `errand.Env()` refuses a stack where it is not.

| | |
|---|---|
| `host` | what ssh reaches: a name from your `~/.ssh/config`, or `user@host` |
| `root` | where the project goes over there. Default: the same path as here |
| `python` | the interpreter to try first over there, when no later layer chooses one ( [below](#nothing-to-install-over-there) ) |
| `options` | passed to ssh: a port, an identity |
| `user` | the login over there, when `host` does not say it ( `User` in `~/.ssh/config` ) |
| `jump` | a gateway to go through, or a list of them in order ( `ProxyJump` in `~/.ssh/config` ): `"me@gate.example.org"`. See [below](#a-gateway-on-the-way) |
| `also` | sibling checkouts the work needs ( `[ "../loom" ]` ), pushed to the same relative place over there |
| `errand_outputs_directory` | where errand writes for the project over there: runs, builds, state. Say `/scratch/me/proj-out`; the project's copy then holds a symlink `errand-outputs` to it. See [Where errand writes](../storage) |

## Nothing to install over there

errand needs nothing installed on the other machine:

- **Its sources travel.** The package is copied to `~/.cache/errand/src/<version>-<checkout>/`, one
  copy per checkout here, and started from there. The errand that answers is the one that asked.
- **It finds a Python to start on.** When a later layer chooses the interpreter ( `Venv`,
  `Micromamba`, `Uv`, a container ), that one. Otherwise it looks where the command starts, after
  `Module`, `Nix` or `Vars`: the `python` named here, then `python3`, `python3.14` … down to 3.8.
- **Or it makes one for itself.** With none recent enough, it makes one for errand alone in
  `~/.cache/errand/python`: with `uv` if the machine has it, else micromamba, mamba or conda, else
  with a `uv` fetched from astral.sh into `~/.cache/errand/uv`. Nothing is put on the `PATH`, no shell
  profile is touched. A couple of seconds, once.

```text
  errand: no python >= 3.8 here: making one for errand alone, in /home/me/.cache/errand/python
  errand: neither uv nor micromamba nor conda: fetching uv into /home/me/.cache/errand/uv
```

Under a scheduler, the command starts on a compute node that may have no network. The search is then
made once on the machine ssh reaches, before submitting, and the job finds the result in
`~/.cache`, in the home directory the nodes share.

Everything errand made for itself is in `~/.cache/errand`: removing that directory undoes it.
`ERRAND_CACHE_DIR`, set in your shell profile over there, puts it elsewhere: see
[Where errand writes](../storage#the-per-user-directory-cache-errand).

## One connection, kept

The first command to reach a host starts an **agent** there, through one ssh. Every later command
goes through it, the pushes and pulls included, and nothing logs in again. Here, a **hub** keeps the
connection open between commands. Past the layers, a second agent runs with the environment's own
interpreter, inside the micromamba environment, the module, the container: the layers are entered
once, not once per command. All of them stop on their own after 15 minutes unused.

What the agents start writes its output to disk over there, so a dropped connection or a closed
laptop loses nothing: [`errand attach`](../detached#close-the-laptop) follows the work again.

→ [Agents and keeping warm](../agents)

## The paths are computed before the run happens

The same rules, applied to the same command, give the same paths on both sides. Over there,
before anything runs, the preparation writes a [plan](../environments#preparing-then-running) that
names the directories the command will write. Only those come back: the runs of this command in
`errand-outputs/runs/`, the directories asked for with `--pull`, and the `back`
[zones](#what-gets-pushed). The rest of the remote tree, which holds other runs from other days,
stays where it is.

A [grid](../matrices) is expanded over there too, one plain run per combination.

## Through an interactive shell

ssh runs commands non-interactively, and so never reads the rc file that puts micromamba, cargo or
nvm on the `PATH`. errand runs the remote command through an interactive shell ( `$SHELL -ic` ),
which reads it. That is the difference between `micromamba -n myenv run` working over there and not.

## options go to ssh

```python
Ssh( host = "gpu-box", root = "/home/me/proj",
     options = [ "-p", "2222", "-i", "~/.ssh/bench", "-J", "jump.example" ] )
```

A port, a jump host, a `StrictHostKeyChecking` you have decided about. They reach the agent over
there, which every push and pull goes through: nothing else logs in.

## A gateway on the way

A cluster is often reached through a gateway. `~/.ssh/config` can say so, but then an environment
file only works for whoever has the same entries. `user` and `jump` say it in the file itself:

```python
Ssh( host = "frontend", user = "me", jump = "me@gate.example.org", root = "/home/me/proj" )
```

is `ssh -J me@gate.example.org me@frontend`. `jump` takes a list for several gateways, gone through in
order. Names are resolved from the last gateway: `frontend` may be a name only the inside knows.

## What gets pushed

The push sends the project, without the obvious. `.git`, `__pycache__`, `*.pyc`, `.mypy_cache` and
`.pytest_cache` are no part of a copy. `errand-outputs` ( at any depth ), `build`, `dist`, `*.so`,
`*.o`, `node_modules`, `.venv` and `*.egg-info` are written over there and left alone. So is what
the project's layers build there, by its exact path ( an image with its `.new`, `.prev` and
`.part` ).

The copy over there is kept identical to the project here: anything found only over there is
deleted, and errand prints what went. A run that writes into the copy, outside `errand-outputs`,
loses it at the next push, unless that place is declared as a **zone**:

```python
errand.configure( zones = { "/results": "back" } )   # written over there, brought back here
```

A zone is left alone by the push. A `back` zone written as a path from the project root
( `/results` ) is also fetched after each command; written as a name ( `results`, anywhere in the
tree ) it is only left alone, as a `build` zone is. A runner whose tool writes somewhere of its own
says so the same way: [What a tool writes elsewhere](/guide/runners/#what-a-tool-writes-elsewhere).

### A cache zone

Downloaded data and results too costly to compute again belong to neither side. A **cache** zone
is added to on both sides, and nothing in it is ever replaced or deleted:

```python
errand.configure( zones = { "/data-cache": "cache" } )
```

- the push sends what the copy lacks: a node with no internet finds the data downloaded here;
- what a run downloads or writes there stays, and is no change outside the zones;
- after each command, what the copy has and this side lacks comes back ( a path from the root only,
  as for `back` ), so the next machine gets it too;
- a file with other contents on each side is a **conflict**: said at each sync, left as it is on
  both. Name files after what they hold ( a hash, a version, the parameters ) and there is none;
- a deletion is never carried: a file removed on one side comes back from the other. Remove it on
  both. errand never prunes a cache.

A run finds it with `errand.cache_dir( "/data-cache" )`, which it passes to whatever downloads or
memoizes. For a file at a URL, `errand.download( url )` does it all, in `errand-cache`, a cache zone
every project has: the file under its hash, and, on a node with no internet, asked of the host over
there, then of this side, which sends it. For a result too long to compute twice, `@errand.memo` keeps
it there by its inputs: computed on one machine, it reaches the others. The why: ADR 0012.

`errand-outputs` is excluded both ways on purpose: each side's records, plans and builds are its
own. The only runs you get back are the ones you just asked for.

## How the project crosses

The push is a **sync**, by manifest. Each side keeps a manifest of its files ( size, mtime, hash ).
The local side sends its own, the agent over there answers with what it lacks, and whole files
cross, compressed. The manifest of the copy is kept in the copy ( `.errand-copy` ). So two hosts
that share a file system ( a cluster's login and compute nodes ) share it too, with nothing to
declare. The agent walks the copy when it starts and when it goes, and trusts the manifest in
between. A change made over there outside a zone is reported, with when it was first seen, before
it is overwritten.

A changed file crosses whole: a large file that changes a little ( a checkpoint, a dataset appended
to ) is sent again in full. Keep such files in a zone ( `back`, `cache` ) or out of the project.

| on lmo, from a Mac | sync |
|---|---:|
| 2597 files, 407 MB, cold | 20.9 s |
| the same, nothing changed | 0.73 s |
| one file changed | 0.78 s |

## Building over there

An [image is built where it is used](../upkeep#where-an-image-gets-built): the recipe is a file
here, it is copied over, and `apptainer build` runs on that host with `fakeroot` and `scratch` as
declared. Where that host has no internet, `build_on = errand.Ssh( ... )` builds it on a machine that
has some, and copies the image over ( see [Apptainer](./containers#a-cluster-without-internet) ).

## Adding an allocation

[`Slurm`](./slurm) goes between the machine and the container, in the order you would say it: that
machine, an allocation on it, the container inside it.

```python
# errand-envs.py
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "login.hpc", root = "/home/me/proj" ),
                                         errand.Slurm( time = "2:00:00" ),
                                         errand.Apptainer( image = "containers/cuda.sif" ) ] )
```

## Results are pulled, not pushed

A finished remote run stays over there until something collects it. A command you wait for collects
its results as its last step. [`errand attach`](../detached#close-the-laptop) collects those of a
command whose connection was lost, and `errand status` or `errand watch` those of a
[`--batch`](../detached) submission.

A run comes back once it has written its `result.yaml`, which it writes last: one still under way
stays over there until the next collection, rather than coming back half written. A pull never
deletes here, by either transfer: a run you have that is gone over there stays. Nor does a push
delete over there the records of runs made there: a run tree a `--out` pattern put in the project
( `runs/…` ) is left alone by the push for every run it holds that is not here, and the push says so.

## What only this machine can supply

A host name you can reach, a partition you may submit to: none of it can be committed, none of it
can be invented. It goes in an untracked `errand-vars.py`, read first, and the files read after it
ask for it with `errand.value`, which takes a default:

```python
# errand-vars.py -- not tracked
ssh_host = "gpu-box"
ssh_root = "/home/me/proj"
```

```python
# errand-envs.py
import errand

errand.envs[ "box" ] = errand.Env( [ errand.Ssh( host = errand.value( "ssh_host", "gpu-box" ),
                                                 root = errand.value( "ssh_root", "/home/me/proj" ) ) ] )
```

See [What only this machine can supply](../configuration#what-only-this-machine-can-supply).
