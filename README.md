# errand

> **Run a piece of work — here, in that environment, in that container, on that machine — and bring
> back everything it produced, into a path you can predict.**

An *errand* is a trip you make on someone's behalf and come home from with the things. That is the
whole model. You declare a piece of work next to the code it exercises; `errand` works out where to
run it, makes sure that place is ready, runs it — in several places at once if you ask — and
repatriates what it produced.

It stands on three legs, and you want all three:

**Where and how it runs.** An environment is a stack of layers: micromamba, conda, uv, a venv, Nix
or Guix, `module load`, a Docker, Podman or Apptainer container, another machine over ssh, a Slurm
or OAR allocation — in any combination. `errand` declares them, *builds* them from what they say
they need, checks before every run that they still match what was declared, and runs the same work
across a matrix of them in one go. Anything can be launched and left to finish on its own.

**Sharing the machine.** Work says what it needs — a core, eight of them, a GPU, the whole machine —
and `errand` holds a queue per host so that two invocations, in two terminals, on two projects, do
not trample each other. A timing taken while something else was running is not a timing.

**What comes back.** Every run gets an output directory whose path is computed, not invented — from
the work, its parameters, its environment and its date. Numbers, files, logs and status land there,
and comparison between dates, machines and parameter sets falls out of the directory tree.

Three worked examples, in order, in [`examples/`](examples/): [no configuration at
all](examples/01-minimal/), [four environments over three machines](examples/02-environments/), and
[an existing pytest / Catch2 / cargo project adopted in three
lines](examples/03-existing-suite/).

## Declaring work

An entry is a piece of work that produces something. You declare it next to the code it exercises,
with a guard that reads like `if __name__ == "__main__":` but does more — several per file, mixable
freely, each identified by its **call site** so that two can share a name:

```python
from errand import entry, Param

if p := entry( "solve", n = Param( 1000, help = "problem size" ) ):
    p.results[ "seconds" ] = solve( p.n )
    ( p.out_dir / "residual.png" ).write_bytes( plot( ) )
    assert p.results[ "seconds" ] < 60
```

`errand` imports the file once to find its entries, then re-imports it once per selected entry, so
every body runs isolated and every failure is caught on its own. The walrus form hands back the
resolved parameters, the output directory, and a `results` dict to drop numbers into. An entry can
assert, record numbers and write files to look at, all three at once.

Four traits say how it should be treated:

| trait | what it decides | default |
|---|---|---|
| `bulk` | picked up by a bare `errand`, with no pattern | `True` |
| `keep` | its numbers are kept and compared date to date | `False` |
| `exclusive` | it needs the machine to itself | `False` |
| `stable_path` | `latest/` is what you are meant to open | `False` |

Setting them by hand every time would be tedious, so three ordinary functions set them for you:

```python
from errand import test, bench, experiment

if test( "addition" ):                       # bulk
    assert 1 + 1 == 2

if p := bench( "solve", n = Param( 1000 ) ): # keep, exclusive
    p.results[ "seconds" ] = solve( p.n )

if p := experiment( "the shape of it" ):     # stable_path
    plot( ).savefig( p.out_dir / "shape.png" )
```

They are three lines of Python over `entry`, and you can write a fourth of your own the same way.
Override a trait on the spot when the preset is not quite right:

```python
if p := experiment( "the big one", exclusive = True ):   # a picture that needs the whole GPU
if p := bench( "cheap probe", exclusive = False ):       # a number that does not
```

`p.results` takes anything. Numeric values are summarized (min and max) at every level above the
run, which is what makes two dates or two machines comparable without you declaring anything.

## Running it

```bash
errand                            # everything bulk, in the default environment
errand solvers                    # every entry in solvers.py
errand solvers::solve             # just that one
errand "solvers::grad_*"          # fnmatch on the name; no `*` means exact
errand "solvers::a,shapes::b"     # several specs
errand -k bench                   # benchmarks only
errand -k exp "solvers::*"        # experiments only, in solvers.py
errand --help                     # the matched entries, with their parameters
```

The positional pattern is a comma-separated list of `file[::name]` specs, both sides globbable. The
file part matches the full stem, and files are found anywhere in the tree with no directory or
project distinction; a bare file part with no `*` must resolve to exactly one file, or you get an
error listing the candidates. The pattern is the only way to narrow by location — there is no
`--directory`.

Finding candidate files is a text check, not an import: a file is a candidate if it mentions
`errand`. So a source file that happens to share its entry's name (`Cell.py` next to `test_Cell.py`)
is never mistaken for one.

Entries carry free-form tags, and `--entry-tags` filters on them:

```python
if test( "the slow one", tags = [ "slow", "gpu" ] ):
    ...
```

```bash
errand -e 'slow & !gpu'          # --entry-tags
```

`-e` picks *what* runs, `-t` picks *where* (see [Tags](#tags)). They take the same expressions.

## Parameters and matrices

`Param( default )` declares a typed flag — the type comes from the default. Parameters show up in
`--help` and are echoed before each run:

```python
if p := bench( "cost", n = Param( 1000, help = "nb of points" ),
                       method = Param( "newton", choices = [ "newton", "lbfgs" ] ) ):
    p.results[ "cost" ] = run( p.n, p.method )
```

```bash
errand cost --n=5000 --method=lbfgs
errand cost --n=1000,5000 --method=newton,lbfgs    # 4 runs, 4 directories
```

**A comma means a matrix**, and it means the same thing everywhere — on a parameter, on a tag, on an
environment. Each value is an axis, the cartesian product is run, and every combination lands in its
own directory so the results sit side by side. This works on any entry, tests included: sweeping a
test across four environments is a perfectly good thing to want.

## Environments

An environment is a stack of **layers** describing how to get from "run this program" to the actual
subprocess, plus **tags** saying what it is. There is always a current interpreter; most layers are
a way to override it.

```python
env( "local", [ Micromamba( "myenv", python = "3.13", requirements = "requirements.txt" ) ],
     driver = "jax" )

env( "gpu", [ Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
                         pip = [ "jax[cuda13]" ] ) ],
     driver = "jax", cuda = True )

env( "cluster", [ Ssh( host = "gpu-box", root = "/home/me/proj" ),
                  Slurm( partition = "gpu", gpus = 1, time = "2:00:00" ),
                  Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
                             pip = [ "jax[cuda13]" ] ) ],
     driver = "jax", cuda = True )
```

| layer | what it does |
|---|---|
| `Micromamba( name, python =, channels =, packages =, requirements =, pip = )` | wraps with `micromamba -n <name> run`; a no-op if that environment is already active |
| `Conda( … )`, `Venv( python =, requirements =, pip = )`, `Uv( … )` | the same idea, other tools |
| `Nix( flake =, shell = )`, `Guix( manifest = )` | `nix develop -c …`, `guix shell -- …` |
| `Module( "gcc/13", "cuda/12" )` | Lmod / environment modules, the way a cluster picks a toolchain |
| `Apptainer( image, recipe =, flags =, mounts =, pip = )` | wraps with `apptainer exec`, using the container's own interpreter |
| `Docker( … )`, `Podman( … )` | likewise |
| `Ssh( host, root =, python =, options = )` | must be first; everything after it runs on that machine. `options` go to ssh *and* rsync — a port, an identity, a jump host |
| `Slurm( partition =, nodes =, gpus =, time =, … )` | goes through `srun`, or `sbatch` in [batch mode](#detached-runs) |
| `Oar( … )`, `Pbs( … )`, `Sge( … )`, `Lsf( … )` | the same, for the other batch systems |
| `Vars( { … } )` | environment variables for the child process |

Requirements belong to the layer that installs them — a `requirements.txt` for the conda
environment, a pip list for the container — because that is the thing that has to be rebuilt when
they change. Tags are keyword arguments, because they belong to the environment as a whole. Share
pieces with plain Python:

```python
CUDA = [ Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
                    flags = [ "--nvccli" ], pip = [ "jax[cuda13]" ] ) ]

env( "gpu",     CUDA,                                        driver = "jax", cuda = True )
env( "cluster", [ Ssh( host = "gpu-box", root = "…" ) ] + CUDA, driver = "jax", cuda = True )
```

### Kept current by themselves

A layer says what it needs — an interpreter version, a channel list, a `requirements.txt`, a `.def`
or `Dockerfile` recipe, a pip list. Before running anything, `errand` compares a fingerprint of
that against what was last built, and brings it up to date when they have drifted: a new pip spec,
an edited recipe, a changed requirements file. Creating an environment, installing into it and
rebuilding an image are one operation seen at three moments, and it happens on its own.

```bash
errand --envs           # what is declared, what state it is in, which is the default
errand --setup          # do it now, and nothing else
errand --setup=force    # from scratch
errand --no-setup       # skip the check for this run
```

This is why the core has no third-party dependencies: it has to work before any environment exists.

## Tags

A tag says what an environment *is*. There is nothing to declare — a tag is a keyword argument on
`env`, and every name used becomes a flag:

```bash
errand --env cluster          # by name
errand --driver jax           # by tag, one flag per name
errand --fp 64 --cuda
errand -t 'jax & fp=64 & !remote'            # --env-tags, the expression form
```

**Saying nothing means every value.** An environment that does not mention `fp` covers every
precision, so `--fp 32,64` is two runs in it; one that says `fp = "64"` is only ever selected for
that one.

Tags only *select*. What an environment then does to the child process is a `Vars` layer, like
everything else it does — and that layer can read the selection back:

```python
env( "gpu", CUDA + [ Vars( lambda t: { "MYPROJ_FTYPE": f"FP{ t.get( 'fp', '64' ) }" } ) ],
     driver = "jax", cuda = True )
```

Without that, a dimension an environment merely *parametrizes* would have to be split into one
environment per value, with each value written twice: once to be matched by `--fp`, once to be
handed to the child. One environment covering a range is the common case, and two covering one
value each is the exception.

**A tag can select several environments, and that is the point.** A comma is a matrix here exactly
as it is on a parameter:

```bash
errand -k bench "solvers::*" --fp 32,64        # both precisions
errand -k bench "solvers::*" --env gpu,cluster # both machines
errand -t 'cuda=True'                          # every cuda environment there is
```

Each environment gets its own output directory, so results sit side by side and the summaries
compare them. Use `--env NAME` when you want exactly one and mean it.

### Skipping a file that does not apply

At the top of a file, before the import:

```python
from errand import has_tag
if not has_tag( "driver=torch" ):
    sys.exit( 0 )
import torch
```

Finding entries means importing every candidate file, so an `import torch` at the top of a file runs
even when the selected environment is a jax one — and on a machine where torch is broken, that takes
down the whole session rather than one file. Exiting before the import is what prevents it. `errand`
catches the exit and reports the file as skipped. Run by hand, outside `errand`, `has_tag` answers
yes to everything: a file that silently disappears is worse than an import that fails loudly.

`tag( "fp" )` gives a tag's value.

### The expression language

One grammar, three readers: `-t` over environments, `-e` over entries, `has_tag` inside a file.
Literals, `&`, `|`, `!`, and `=` for a valued tag. No parentheses.

## Sharing the machine

An entry says what it needs, and nothing gets to ignore it:

```python
if p := bench( "solve" ):                            # exclusive: the machine to itself
if p := test( "wide", cpus = 4, ram = "8G" ):        # a share of it
if p := test( "on the card", gpus = 1 ):
```

`cpus`, `ram` and `gpus` are counted against what the host has; anything else you name is counted
against what you told `errand` the host has. `exclusive` is the blunt version, for when the answer
is "all of it and no neighbours".

An exclusive entry waits for what is already running and holds everything else back while it runs;
everything else proceeds as long as the machine has the room. The queue lives **outside the
process**, one per user per host, so it is shared by every `errand` on that machine — two terminals,
two projects, no interference.

```bash
errand --queue        # what the host has, and what is holding it
errand --no-queue     # this run does not wait, and does not hold
```

**A card is assigned, not merely counted.** An entry that asked for `gpus = 1` is told *which* one,
through `CUDA_VISIBLE_DEVICES` (and the `HIP`/`ROCR` spellings); two entries that both asked for one
get different cards. Counting alone would let them both pick the first and neither would measure
anything. An exclusive run gets all of them. Claims nest correctly: a process that was itself given
cards 2 and 5 sees them as 0 and 1, and hands 0 and 1 down.

A claim records who holds it and is **touched while the work lives**. One whose timestamp has gone
stale is reclaimed, and its owner, if it ever comes back, finds it gone. That is the only honest way
to tell a killed run from a long one: a benchmark that has been running for six hours is
indistinguishable from a corpse except by whether anything is still breathing. The same heartbeat
answers the same question for [detached runs](#detached-runs) — one mechanism, not two.

Waiting happens **outside the measurement**. How long the machine was busy is not part of how long
the work took, and counting it would make a benchmark's numbers depend on who else was around.

### When somebody else owns the machine

Inside a Slurm, PBS, OAR or LSF allocation, `errand` does not queue at all. The scheduler has
already decided what this process may have, and a second queue on top of it would only wait for
itself. What the work asks for is handed over instead: the `Slurm` layer turns the entries' `cpus`,
`ram`, `gpus` and `exclusive` into `--cpus-per-task`, `--mem`, `--gpus` and `--exclusive` on the
submission. A dispatched command carries several entries, so the allocation is the largest of them,
and exclusive if any one of them is.

What the environment states explicitly wins: whoever wrote `Slurm( cpus = 16 )` knew something about
that partition an entry cannot. **Everything is optional, `partition` included** — what is not
stated is not passed, and the cluster applies its own default, which stays correct when the cluster
is rearranged and a name copied out of somebody else's script does not.

```python
env( "cluster", [ Ssh( host = "login.hpc", root = "/home/me/proj" ),   # NOT /tmp
                  Slurm( time = "2:00:00" ) ] )                        # the default partition
```

The root must be on a **shared filesystem**. A batch job runs on a compute node, and `/tmp` there
is not the `/tmp` you pushed to — the job lands somewhere that has never heard of your project, and
says so in terms of a failed `chdir` followed by an import error, neither of which points at the
cause. `errand` checks for that before submitting and tells you plainly.

## Where the output goes

Every (entry, parameter set, place, date) gets its own leaf directory, cleared and recreated on each
run. Only the leaf is cleared; its ancestors accumulate.

```
runs/{file}__{name}/[params]/{place}/{date}/
runs/{file}__{name}/[params]/{place}/latest -> {date}
```

*This is the default layout; it is configurable.* `{place}` is the host's name, prefixed by the
container's when the run happened in one — `gpu-box`, `cuda.sif@gpu-box`. Both matter and neither is
enough: the same image on two machines is two different sets of numbers, and the same machine with
two images likewise. `latest/` is a symlink, so every run can be dated without costing you a stable
path — leave a tab open on `latest/shape.png` and reload it.

The leaf always holds `result.yaml`, plus `output.txt` if the body printed anything:

```yaml
name: cost
file: bench/solvers.py
line: 42
env: gpu
place: cuda.sif
host: gpu-box
commit: 4f2a1b9           # + dirty: true when the tree was not clean
errand: 0.1.0
status: PASS
duration_s: 12.406
ram_mb: 1840.2
params: { n: 5000, method: newton }
tags: { driver: jax, fp: "64" }
results: { seconds: 12.406, iterations: 31 }
output_file: output.txt
```

Write anything else you like into the same directory — an `.svg`, a `.vtu`, a folder of frames.

Above the leaf there is a summary at each level: per date within a place, per place within a
parameter set, and per parameter set at the entry's root, which is what you read after a matrix.
They are recomputed on every run by re-reading the neighbouring `result.yaml` files rather than kept
in a ledger, so they are always right and repair themselves.

## Running elsewhere

`Ssh` must be the first layer. It resolves the rest of the stack against the remote root, serializes
it to a shell string and runs it over ssh — rsync push before, targeted rsync pull after:

```
  → gpu-box:/home/me/proj  env=cluster  tags=driver:jax,cuda
  rsync push → gpu-box:/home/me/proj
  ...
  rsync pull ← gpu-box:/home/me/proj [runs/solvers__cost/a1b2c3d4e5]
```

The paths to pull are computed **before the remote run happens**: the same rules applied to the same
entries and parameters give the same answer on both sides, so nothing has to be declared at runtime,
and the rest of the remote tree — which holds unrelated runs from other days — stays put.

Matrices are expanded on this side, one plain run per combination, each value crossing already split.

The remote command goes through an interactive shell, because ssh runs non-interactively and would
otherwise never read the rc file that puts micromamba, cargo or nvm on `PATH`.

## Detached runs

`--batch` launches the work and gives you the shell back. It is a *mode*, not a layer: it means the
same thing in every context, and what changes is only how each one detaches.

```bash
errand --batch -k bench "solvers::*" --env gpu,cluster --fp 32,64
  submitted b7f3 · 8 runs · 4 on gpu-box (slurm 918273…918276), 4 local
```

| context | waiting | detached |
|---|---|---|
| local | subprocess | own session, survives the terminal |
| `Ssh` | ssh, output streamed | started over there and let go |
| `Slurm`, `Oar`, `Pbs`, … | `srun` | `sbatch` and friends |

A layer that can detach says so, and answers three questions about a handle afterwards: is it still
alive, what is its state, and how do I cancel it. That is the same shape as the pair a layer already
implements to build itself.

Nothing else changes. The queue that shares the machine is the same queue, so a detached exclusive
benchmark still gets the host to itself. The paths are the same paths — and since they were computed
before the run started, **the arrival of a `result.yaml` where one was expected is itself the
completion signal.** There is no protocol to speak between the two sides, no daemon, and no
agreement to get out of sync: the output tree is the state.

Results are pulled when you ask, not pushed. A finished remote run sits there until something
collects it, which is what the monitor does.

A handle is only as good as what issued it: a batch system's job id outlives a reboot, a bare pid
does not and gets reused. So a handle is never trusted on its own — it is paired with the heartbeat
the [queue](#sharing-the-machine) already keeps, and a run is alive when something is still
breathing for it, whatever the handle claims. The record of an invocation — which runs across which
machines belong to the same submission — is kept **locally**, since the side that expanded the
matrix is the only one that ever knew they went together.

## Keeping track

```bash
errand --status      # one shot, plain text, greppable
errand --watch       # the same, live and interactive
```

```
 errand · 2 running · 6 pending · 12 done                       gpu-box 6/8   local 2/16

 ▾ b7f3  solvers::*  --fp 32,64 --env gpu,cluster     12:04    8 runs   ▓▓▓▓▓▓░░  6/8
                     fp=32              fp=64
     gpu      n=1000  ✓  12.4 s          ✓  11.2 s
              n=5000  ✓  61.2 s          ⟳  4m12s
     cluster  n=1000  ✓  13.1 s          ⋯  pending   slurm 918275, prio 12
              n=5000  ✓  64.8 s          ⋯  pending   slurm 918276
 ▾ 21ac  shapes::viz                                  12:31    1 run    ▓░░░░░░░  0/1
     local            ⟳  0m08s
 ▸ 4e90  test_Cell::*                                 11:20    5 runs   ▓▓▓▓▓▓▓▓  5/5  ✓

 [enter] output dir   [l] logs   [c] cancel   [d] diff two cells   [/] filter   [q] quit
```

Grouped by invocation, because that is the unit you submitted and the unit you will compare. Inside
one, the matrix reads as a **table** — parameters down, environments and tags across — since that is
the shape it actually has, and a flat list of eight lines hides the one axis you were varying. Two
axes fit on screen; beyond that the extra ones become the row label.

Cells show elapsed time while running and the kept number once done, so a column that is slower than
its neighbour is visible without opening anything. `--watch` polls the output tree and the batch
systems; it holds no state of its own, so it can be started, killed and restarted at any point, and
several can watch at once.

A page in a browser would show this same table and answer the same question, so there is nothing to
choose between them: the terminal comes first because it is where the work is already happening, and
anything else is the same view over the same tree.

## Configuration

None is needed. `errand` with no configuration at all finds your entries and runs them in the
interpreter you started it with.

To declare environments, tags and the rest, put an **`errandfile.py`** at the root of the project —
the same idea as a Makefile or a Dockerfile. It is ordinary Python, loaded once by path and under a
private name, with no entry point to call and nothing to return:

```python
from errand import configure, env, provider, Micromamba, Apptainer, Ssh

configure( out = "runs", src = [ "core/src", "app/src" ] )

env( "local", [ Micromamba( "myenv", python = "3.13", requirements = "requirements.txt" ) ],
     driver = "jax" )
env( "gpu", [ Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def" ) ],
     driver = "jax", cuda = True )

provider( Catch2( dir = "tests/cpp" ) )
```

Calling it `errandfile.py` also works, and is a trap worth naming: a module of that name at the root of
a project **shadows the package** wherever the root is on `sys.path`, which is to say for
`python -m errand` and for any script started from there. `errand` says so out loud when it finds
one. The `errandfile.py` spelling has no such problem.

```python
configure(
    root   = None,     # repo root; found by walking up from the cwd for errandfile.py
    out    = "runs",   # where the output tree goes
    layout = None,     # override the path scheme
    src     = [ ],     # paths prepended to every child's PYTHONPATH
    exclude = [ ],     # directories discovery must not walk into
    default = None,    # the environment used when nothing is asked for
)
```

There is no mechanism for project-specific subcommands, because there does not need to be one:
something you want to run is an entry, and `bulk = False` keeps it out of the way until you name it.

```python
if entry( "docs", bulk = False ):
    build_docs( )
```

```bash
errand docs
```

### What only this machine can supply

Reaching an ssh host, or a queue you are allowed to submit to, depends on who is running. None of it
can be committed and none of it can be invented, so it goes in an untracked **`errand.local.py`**
beside the errandfile, and an entry asks for what it needs by name:

```python
from errand import test, need

if test( "it runs over there" ):
    host = need( "ssh_host", "a machine you can ssh to without a password", example = "gpu-box" )
```

When it is not there the entry is **skipped** — never passed — and the run ends with a block saying
what was missing and exactly what to write where:

```
  3 skipped:
    it runs over there  (test_ssh.py:18)  needs `ssh_host` -- a machine you can ssh to without a password
      errand.local.py does not exist yet. Create it (it is not tracked) with:
          ssh_host = 'gpu-box'
```

Reach for it only for what genuinely cannot be defaulted. `ssh localhost` is a real ssh, a real
rsync and a real round trip through a directory that is not the project's — only the hardware is
shared, and the hardware is rarely what is being tested. A suite that exercises the remote path on
anyone's machine is worth more than one that waits for a cluster.

A skip is its own status, in the output and in `result.yaml`. `skip( "reason" )` says it directly
for anything else that makes an entry inapplicable today. A suite that quietly tested nothing must
not be able to look like a suite that passed.

## Other languages

An entry does not have to be a Python call site. Providers for C++ (Catch2, GoogleTest, doctest),
Rust (`cargo test`, Criterion), JavaScript and plain executables come with `errand`, and one line
in `errandfile.py` puts an existing suite under it — with an output directory, summaries, environment
matrices and remote repatriation, none of which it had before:

```python
provider( Pytest( ) )
provider( Catch2( dir = "tests/cpp" ) )
provider( Cargo( ) )
```

A suite keeps everything that makes it itself, and its vocabulary is translated rather than
replaced: a `@pytest.mark.slow` is an entry tag, so `-e '!slow'` filters it with the same expression
language `-t` uses on environments; a Catch2 `[tag]` likewise; a framework's own benchmark numbers
land in `result.yaml` beside everyone else's.

A provider finds its own entries the way its ecosystem does — `pytest`'s collection rules, the
`test_*.cpp` under a directory, `cargo`'s targets. That is a guess about your layout, so it is a
guess you write down: a provider line in `errandfile.py` is the declaration of what will be looked for
and where, and it takes the arguments to say something else. With no `errandfile.py` at all, `errand`
guesses on its own and **tells you what it guessed** before running anything — convenient for a
first look, never silent, and the cure is to write the line.

Discovery over a large tree is not free, and will be cached against file mtimes. Later; it is an
optimization, not a design question.

Writing a provider for something else is a three-method protocol; see the wiki.

## Status

Design settled, nothing implemented yet. What is written above is what is being built.

One thing is deliberately left to you: a matrix that spans a laptop and a cluster partition at once
will produce numbers that are not comparable, and `errand` will not stop you. It runs what you ask
where you ask and records where each number came from; deciding what may be compared to what is
yours.

Not done yet: running several entries at once inside ONE invocation. The queue already keeps
separate invocations out of each other's way, which is the case that bites; entries within a single
run still go one after another, because isolating them from each other means a process apiece.

Known to be unresolved: what a summary should say *across* places. Min and max per row are enough to
read, but deciding that a machine got slower is a different question, and one that wants to know
something about noise.
