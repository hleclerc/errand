# errand

> **Run a piece of work — here, in that environment, in that container, on that machine — and bring
> back everything it produced, into a path you can predict.**

An *errand* is a trip you make on someone's behalf and come home from with the things. That is the
whole model. You say what to run and where it may run; `errand` makes sure that place is ready, goes
in — through ssh, a Slurm allocation, a container, whatever the way is — runs it, in several places
at once if you ask, and repatriates what it produced.

What you run is yours: a pytest suite, a Catch2 binary, a cargo project, a Makefile target, a script.
With no configuration `errand` looks at the directory and says what it found; `errand --init` writes
that down as an `errand-project.py`. Declaring work with errand's own `if track( … ):` guard is one
more way to give it something to run, not the way in.

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

Everything below, split by sub-theme and with the examples written up as tutorials, is on the
website: **<https://hleclerc.github.io/errand/>** — built from [`docs/`](docs/).

## Installing

```bash
pip install errand-run
```

The *distribution* is called `errand-run` — `errand` on PyPI is somebody else's project — but what
you type, and what you import, is `errand`.

It has **no dependencies, and it is not going to get any.** errand's job is to build the environment
the work runs in, so it has to be able to run before any environment exists: it writes YAML without
pyyaml, and draws [its screen](#the-screen) with the curses of the standard library, for that reason
alone. Python 3.10 or later, on a unix.

Working on errand itself:

```bash
make venv       # a virtual environment with errand installed in it, editable
make test       # the suite -- which is written with errand, and is the longest worked example
make            # everything else, including the release order
```

## Declaring work

*This section is about errand's own declaration, which is optional: a pytest, Catch2 or cargo
suite, or a plain command, needs none of it — see [Other languages](#other-languages).*

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

Setting them by hand every time would be tedious, so four ordinary functions set them for you:

```python
from errand import test, bench, track, experiment

if test( "addition" ):                       # bulk
    assert 1 + 1 == 2

if p := track( "accuracy", n = Param( 1000 ) ):   # keep
    p.results[ "error" ] = abs( solve( p.n ) - exact( p.n ) )

if p := bench( "solve", n = Param( 1000 ) ): # keep, exclusive
    p.results[ "seconds" ] = solve( p.n )

if p := experiment( "the shape of it" ):     # stable_path
    plot( ).savefig( p.out_dir / "shape.png" )
```

`track` is for **numbers you want to follow** — an error, a residual, a size, a score, a timing —
kept and compared date to date. A benchmark is not necessarily about speed. `bench` is `track`
measured alone, since the commonest numbers worth following are timings and a timing taken while
something else ran is not a timing.

They are four lines of Python over `entry`, and you can write a fifth of your own the same way.
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
errand --tui                      # one screen: tick what to run, watch it run
```

The positional pattern is a comma-separated list of `file[::name]` specs, both sides globbable. The
file part matches the full stem, and files are found anywhere in the tree with no directory or
project distinction; a bare file part with no `*` must resolve to exactly one file, or you get an
error listing the candidates. The pattern is the only way to narrow by location — there is no
`--directory`.

Finding candidate files is a text check, not an import: a file is a candidate if it **imports**
`errand`. So a source file that happens to share its entry's name (`Cell.py` next to `test_Cell.py`)
is never mistaken for one — and neither is a file that merely mentions errand in a comment, which
would otherwise be imported and executed on the strength of a word.

While a file is being read, **its own directory is on the import path**, so `test_primes.py` can
`import primes` from beside it. Work is declared next to the code it exercises; which directory you
happened to start `errand` from is not supposed to change what a file can import. The path is
borrowed for the import and put back afterwards.

A file that declares work is **not a module to import from**. Importing one from another declares
everything in it twice, and errand says so rather than running the copies; put what is shared in a
file that declares nothing.

A directory holding an `errand-*.py` of its own is **another project**, and is not walked into: its
entries would run with this project's `src`, providers and environments, which is to say wrongly.

A candidate that will not import — a missing dependency, an example nobody set up — **costs its own
row and nothing else.** Everything readable still runs; what could not be read is listed at the end,
and takes the return code with it. Tolerant, not silent.

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
# errand-envs.py
import errand

errand.envs[ "local" ] = errand.Env( [ errand.Micromamba( "myenv", python = "3.13", requirements = "requirements.txt" ) ],
                                     driver = "jax" )

errand.envs[ "gpu" ] = errand.Env( [ errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
                                                       pip = [ "jax[cuda13]" ] ) ],
                                   driver = "jax", cuda = True )

errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "/home/me/proj" ),
                                         errand.Slurm( partition = "gpu", gpus = 1, time = "2:00:00" ),
                                         errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
                                                           pip = [ "jax[cuda13]" ] ) ],
                                       driver = "jax", cuda = True )
```

| layer | what it does |
|---|---|
| `Micromamba( name, python =, channels =, packages =, requirements =, pip = )` | wraps with `micromamba -n <name> run`; a no-op if that environment is already active |
| `Conda( … )`, `Venv( python =, requirements =, pip = )`, `Uv( … )` | the same idea, other tools |
| `Nix( flake =, shell = )`, `Guix( manifest = )` | `nix develop -c …`, `guix shell -- …` |
| `Module( "gcc/13", "cuda/12" )` | Lmod / environment modules, the way a cluster picks a toolchain |
| `Apptainer( image, recipe =, flags =, mounts =, pip =, fakeroot =, scratch =, build_flags = )` | wraps with `apptainer exec`, using the container's own interpreter. The last three are about *building* it rather than entering it |
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
# errand-envs.py
import errand

CUDA = [ errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
                           flags = [ "--nvccli" ], pip = [ "jax[cuda13]" ] ) ]

errand.envs[ "gpu" ]     = errand.Env( CUDA,                                                    driver = "jax", cuda = True )
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "…" ) ] + CUDA, driver = "jax", cuda = True )
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
errand --setup --dry-run  # say what that would run, and run nothing
errand --no-setup       # skip the check for this run
```

**What is already there is adopted, not rebuilt.** The first time errand meets an environment there
is no record of what it was built from, so every layer looks out of date — and acting on that
reading would mean recreating, on somebody's first command, an environment that has been working
for months. So: present and never seen before is recorded as-is; only a declaration that has
*changed* since a record errand itself wrote is a reason to touch it, and `--setup=force` is how you
say the other thing. (`micromamba create -n x` on an existing `x` is not a no-op and not an update:
it resolves the named specs into it, and `python=3.13` over a 3.14 environment takes every package
installed for 3.14 out with it. An environment somebody is working in must never be the collateral
of a declaration being read for the first time.)

Building an image happens where the image is used: an `Ssh` layer in front means the sources are
rsynced over first — the recipe is a file *here*, the build happens *there* — and `apptainer build`
then runs on that host, with `fakeroot` and `scratch` as declared.

This is why the core has no third-party dependencies: it has to work before any environment exists.

### Being let into one

```bash
errand --env gpu -- python -m mypkg.toolchain   # that command, in that environment
errand --env cluster -- nvidia-smi              # on the other machine, through ssh
errand --driver torch -- python -c "import torch; print( torch.__version__ )"
```

Everything after a bare `--` is a command to run *in* the environment rather than arguments to
errand. The environments are already declared here, once, with the layers that lead to them — a
venv, a container, another machine — so being let into one is a smaller thing than a second tool
that would have to describe them all over again. A first word that names an interpreter is replaced
by the interpreter of the place; any other is a command in its own right and is kept.

## Tags

A tag says what an environment *is*. There is nothing to declare — a tag is a keyword argument on
`errand.Env`, and every name used becomes a flag:

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
# errand-envs.py
errand.envs[ "gpu" ] = errand.Env( CUDA + [ errand.Vars( lambda t: { "MYPROJ_FTYPE": f"FP{ t.get( 'fp', '64' ) }" } ) ],
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

```bash
errand -j 8           # eight entries at a time
errand -j auto        # as many as the machine has cores
errand                # one at a time: the default
```

`-j` runs **one process per entry**, because the isolation between entries is the module reload and
a reload only isolates within one interpreter. A serial run stays in this process, where it is
faster and its output arrives live; each parallel entry's output is held and printed whole, in
completion order, since interleaved lines from several entries at once are unreadable and, worse,
unattributable. What came of a child is read back from its result file rather than parsed out of its
chatter — the path was worked out before the child started, and the file is the record either way.

**An errand started from inside an errand inherits the claim** instead of waiting for it. The entry
that started it is holding one while it waits, so a child that queued would be waiting for something
its own parent cannot release until the child is done. Same rule as the batch systems: what has
already been granted is not asked for twice.

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
# errand-envs.py
import errand

errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "login.hpc", root = "/home/me/proj" ),   # NOT /tmp
                                         errand.Slurm( time = "2:00:00" ) ] )                        # the default partition
```

The root must be on a **shared filesystem**. A batch job runs on a compute node, and `/tmp` there
is not the `/tmp` you pushed to — the job lands somewhere that has never heard of your project, and
says so in terms of a failed `chdir` followed by an import error, neither of which points at the
cause. `errand` checks for that before submitting and tells you plainly.

## Where the output goes

**Two directories to find a case, then one flat list of its runs**, each cleared and recreated as it
starts. Only the run directory is cleared; everything above it accumulates.

```
runs/{file}/{name}/{when}-{place}[-{params}]/
runs/{file}/{name}/latest -> the newest of them

runs/solvers/cost/2026-09-25_18h04m11-gpu@gpu-box-method=newton,n=5000/
runs/solvers/cost/2026-09-25_18h11m02-local@laptop-method=cg,n=5000/
```

The file and the name are how you *look* for work — they are what you typed to run it — so they are
directories. Everything that tells two **runs** of that case apart is one directory name, in the
order you would say it out loud: when, where, and with what. A tree with a level per dimension reads
beautifully drawn in a README and badly when it is a `cd` away, and the level whose name was a hash
of the parameters could not be read at all. A matrix is more *names*, never more levels.

`{when}` is the moment the **command** started, to the second — one stamp for the whole invocation,
however many processes it turns into, which is what lets the `-j 8` children, the batch job the
scheduler starts tomorrow and the run over ssh all land in the directory that was predicted for them.
`{place}` is the environment and the machine — `default@gpu-box`, `cuda@gpu-box`. Both matter and
neither is enough: the same environment on two machines is two different sets of numbers, and the
same machine with two environments likewise, which is the whole reason you declared two. The
environment stands for its container rather than the other way round: an image is one of the things
an environment *is*, and the name is the one you chose. `{params}` is what was asked for, in words —
cut at a readable width with a short hash on the end when there is more of it than anyone would read.
`latest/` is a symlink, so every run can be stamped without costing you a stable path — leave a tab
open on `latest/shape.png` and reload it.

The leaf always holds `result.yaml`, plus `output.txt` if the body printed anything. `output.txt` is
written **as the run talks**, not at the end: it is the only place a case running over there, or
beside seven others under `-j`, says anything at all — so `tail -f` works on it, and so does the
screen, which is the same thing.

```yaml
name: cost
file: bench/solvers.py
line: 42
kind: bench
date: 2026-09-25T18:04:11+02:00     # the directory carries the day; this says when
env: gpu
place: gpu@gpu-box
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

The directory is dated to the **day** — that is what a path can carry and stay readable — so the
record carries the hour, with the offset it was written under. Two runs of the same case on the same
day land in the same directory, and `date` is what tells them apart.

Write anything else you like into the same directory — an `.svg`, a `.vtu`, a folder of frames.

Above the runs there is a `summary.yaml` at the case's root, one row per run and the extents across
them all, which is what you read after a matrix. It is recomputed on every run by re-reading the
neighbouring `result.yaml` files rather than kept in a ledger, so it is always right and repairs
itself.

## Running elsewhere

`Ssh` must be the first layer. It resolves the rest of the stack against the remote root, serializes
it to a shell string and runs it over ssh — rsync push before, targeted rsync pull after:

```
  → gpu-box:/home/me/proj  env=cluster  tags=driver:jax,cuda
  rsync push → gpu-box:/home/me/proj
  ...
  rsync pull ← gpu-box:/home/me/proj [runs/solvers/cost]
```

The paths to pull are computed **before the remote run happens**: the same rules applied to the same
entries and parameters give the same answer on both sides, so nothing has to be declared at runtime,
and the rest of the remote tree — which holds unrelated runs from other days — stays put.

Matrices are expanded on this side, one plain run per combination, each value crossing already split.

The remote command goes through an interactive shell, because ssh runs non-interactively and would
otherwise never read the rc file that puts micromamba, cargo or nvm on `PATH`.

## Detached runs

`--batch` launches the work and gives you the shell back. It is a *mode*, not a layer: it means the
same thing in every context, and what changes is only how each one lets go.

```bash
errand --batch -k bench --env gpu,cluster --fp 32,64
  submitted b7f3 - 8 run(s) - 4 on login.hpc (batch 918273), 4 on this machine (local 41288)
  errand --status    errand --watch
```

| context | waiting | detached |
|---|---|---|
| local | subprocess | a session of its own, which survives the terminal |
| `Ssh` | ssh, output streamed | started over there and released, output to a file |
| `Slurm`, … | `srun` | `sbatch`, which *is* the detachment: it returns as soon as the job is queued |

Nothing else about the run changes — same paths, same queue, same output. And because the paths were
worked out before anything started, **the arrival of a result file where one was expected is itself
the completion signal.** No protocol between the two sides, no daemon, nothing that can get out of
sync: the output tree is the state.

What is kept locally is only what the tree cannot say — which runs belong to one submission, and
what handle each place was given. The side that expanded the matrix is the only one that ever knew
those runs went together.

**Where a run happened is looked for when it cannot be known.** A run detached on this machine has a
predictable place and the record says so. A remote one does not — it carries the other machine's
name — and neither does a batch job, which carries the name of whichever compute node the scheduler
picked. The parameter directory *is* predictable in every case, being a hash of what was asked for,
so that is what gets searched, and the result naming this run's environment and parameters is the
one.

Results are pulled, not pushed. A finished remote run sits there until something collects it, which
is what asking does.

## Keeping track

```bash
errand --status        # one shot, plain text
errand --watch         # the same, live, until everything has landed
errand --forget b7f3   # drop a submission from the list, keeping its results
```

```
b7f3  -k bench --fp 32,64 --env gpu,cluster   2026-09-24 12:04   6/8 [######  ]
    gpu: local 41288 on this machine - finished
    cluster: batch 918273 on login.hpc - running
                        gpu@thishost            cluster@node15
      cost  fp=32, n=1000   ok seconds=12.4        ok seconds=13.1
      cost  fp=32, n=5000   ok seconds=61.2        ok seconds=64.8
      cost  fp=64, n=1000   ok seconds=11.2        ...
      cost  fp=64, n=5000   ...                    ...
```

Grouped by submission, because that is the unit you launched and the unit you will compare. Inside
one, the matrix reads as a **table** — parameters down, places across — since that is the shape it
has, and a flat list of eight lines hides the one axis you were varying. A cell shows the kept
number once there is one, so a column slower than its neighbour is visible without opening anything.

`--watch` holds no state of its own: it polls the tree and the batch systems, so it can be started,
killed and restarted at any point, and several can watch at once. A page in a browser would show
this same table and answer the same question; the terminal comes first because it is where the work
is already happening.

## The screen

```bash
errand --tui
```

**Two pages**, because there are two questions: *what do I run*, and *what came of it*. No focus to
keep track of: one rectangle is active, the arrows drive it, and clicking one selects it; the wheel
scrolls whatever is under the pointer and changes nothing else.

**`tab` walks the rectangles of the page; the function keys are the verbs.** What you type is the
search, on either page — so the letters are spoken for, and a verb belongs on a key nothing else can
claim. `F2` and `F3` are the page before and the page after: two pages, two keys side by side,
nothing to aim at, only a direction.

| | | | |
|---|---|---|---|
| `F1` | these keys | `F5` `F6` | run the last command again · the one under the cursor |
| `F2` `F3` | the page before · after | `F7` `F8` | interrupt what is running · open the file |
| `tab` | the next rectangle | `F9` | read the project again |
| `esc` | clear the search, then leave | `F12` | leave |

### cases — what do I run

```
 [cases]   runs                                      errand · myproject · idle
 find: shp gpu_
 ╭─ cases  3 found ──────────────────────╮╭─ solve ─────────────────────────────╮
 │   solve            bench/shapes.py:42 ││ bench/shapes.py:42                  │
 │   solve_coarse     bench/shapes.py:61 ││ kind: bench                         │
 │   shape_gradient   tests/geometry.py:9││ tags: gpu, slow                     │
 ╰───────────────────────────────────────╯│ needs: gpus=1                       │
                                          │                                     │
                                          │ --n   default 1000                  │
                                          │   how many points                   │
                                          │                                     │
                                          │ last run                            │
                                          │   PASS   gpu   gpu@gpu-box          │
                                          │   12.4s                             │
                                          │   seconds = 12.406                  │
                                          ╰─────────────────────────────────────╯
 type to search · enter runs it · space ticks · tab next box · F3 runs · F1 keys
```

**Typing is the search** — there is no key to press first, because finding one case among three
hundred is what this page is for. It is the matching an editor's *go to file* does, not an edit
distance: the letters have to appear **in order but not together**, so `tsq` finds
`tests/test_shapes.py::quick`. Then they are *scored* — together beats scattered, the start of a
word beats the middle of one, early beats late, short beats long — and the letters that matched are
shown in bold, so a row tells you why it is there.

Several words all have to be found, each possibly in a different place: `shp gpu` is "a case whose
name looks like shp **and** whose tags or file say gpu". Adding a word narrows; you never have to
rewrite what you typed.

**`esc` clears what you typed**, and only then leaves: a filter is the thing you most want gone, and
it should not be the hardest to get rid of. While a search is on, space is a word separator, so the
tick is `ctrl-space` — or a click straight on the box.

**The runs page is searched the same way**, over the commands: a history is only useful once one
line of it can be found. The two searches are separate, so the one you keep on `cases` is still
there when you come back from looking at `runs`.

With nothing typed, the cases are **a tree of directories and files**, because that is the shape
the work has: a project is a layout before it is a list, and the directory is how you remember where
a case lives. A directory holding one single thing does not cost a row of its own — its name joins
its child's, `bench/gpu/heavy.py` on one line, since a row you can only walk through tells you
nothing.
Facing them: everything about the one under the cursor, down to how it went the last time it ran —
read out of [the output tree](#where-the-output-goes), so it is there after a restart and after
somebody else ran it.

### runs — what came of it

```
 cases   [runs]                                   errand · myproject · running
 find: a command
 ╭─ runs ────────────────────────────────╮╭─ files ─────────────────────────────╮
 │ ▾ errand shapes --n 1e3,5e3       4/8 ││   shape.svg                 12.1 kB │
 │   ok    solve  n=1000  [local]        ││   result.yaml                 512 B │
 │   ok    solve  n=1000  [gpu]          ││   output.txt                 1.2 kB │
 │   ..    solve  n=5000  [local]        │╰─────────────────────────────────────╯
 │ ▸ errand -k bench --fp 32       6 ok  │╭─ output.txt ────────────────────────╮
 │ ▸ errand tests --n 10           1 ok  ││ iteration 41   residual 3.1e-07     │
 ╰───────────────────────────────────────╯│ iteration 42   residual 1.9e-07     │
                                          ╰─────────────────────────────────────╯
```

**Runs and history are one list**, because they are one thing: a command, and what it produced.
Today's is at the top and still moving, yesterday's is three rows down, and both read the same way —
both are read out of the output tree rather than remembered. Fold one open to see its cases; `F6`
runs it again, and `F5` runs the last one again from either page.

Facing them: the files a run wrote, and below, the one under the cursor. Text is shown as text —
`output.txt` follows the run as it is written — and anything else says what it is and how big.
Enter or `F8` hands it to the desktop (`xdg-open`, `open`), so an experiment's `.svg` is two keys
from the case that produced it.

### asking where

Enter on a case asks the only question left: where, with which tags, with which parameters — not
*which case*, which was the list you pressed enter in.

```
 ╭─ run: solve ──────────────────────────────────────────────────────────────────╮
 │ › --env    [x] local   [x] gpu                      two ticks is two runs     │
 │   --fp     [x] 32      [x] 64                    only the ones that say so    │
 │   --n      1000,5000                                     how many points      │
 │   -j       1                                             how many at once     │
 │   --batch  [ ] detach                                 outlives this window    │
 │   ─────────────────────────────────────────────────────────────────────────   │
 │   errand shapes::solve --env local,gpu --fp 32,64 --n 1000,5000               │
 ╰───────────────────────────────────────────────────────────────────────────────╯
   space ticks · ←→ picks · type into a field · enter runs · esc gives up
```

**Every line has the same three columns**: the flag on the left, the field in the middle, what it
means on the right, faded. A thing spread over two lines is a thing you have to assemble before you
can read it, and there is width to spare. A field shows what you **typed** in bold, or what happens
anyway in grey, with a cursor blinking in it — which is the only way of saying *type here* that
nobody has to be taught. Chips are ticked with space, walked with `←→`, and clicked.

**Ticking two of anything is a matrix.** Two environments, two values of a tag and two of a
parameter are eight runs — for exactly the reason a comma is, and the window builds exactly that
comma. Below the rule, in its own colour, is that command: not a prompt, and nobody is being asked
to type it — it is what is about to happen, said once, so that the day you want it in a script you
already know what to write. The keys stay on the screen's own bottom line, where they always are.

**Each case's output is read from the file that case is writing**, never from a share of one pipe.
The paths are worked out before the run starts, so the name is known in advance — which is why it
reads the same under `-j 8`, for a run on another machine, and for a job submitted yesterday. Tick
`detach`, close the window, open it tomorrow: the state was never in the screen.

A file that declares work and will not import costs its own row, marked `!`, with the traceback
facing it. Half a project installed is an ordinary state of affairs; an empty screen is a poor way
of saying so.

| | |
|---|---|
| `F1`…`F12` | one per thing to do — see the table above |
| `tab` | the next rectangle of this page |
| typing | the search, on either page |
| arrows, click, wheel | move · choose and activate · scroll what is under the pointer |
| space | tick a case, or fold — `ctrl-space` while a search is on |
| enter | cases: ask where · runs: its files · files: open it |
| `esc` | clear the search, then leave |
| `F9`, `F1`, `F12` | read the project again · the keys · leave |

A run started from the screen belongs to the screen, so leaving is refused while one is going —
`detach` is how work is meant to outlive a window.

## Configuration

None is needed. `errand` with no configuration at all finds your entries and runs them in the
interpreter you started it with.

To declare what the project does, and where it runs, put **`errand-*.py`** files at the root of the
project. `errand` reads every one of them, in name order; what you call them beyond the prefix is up
to you, and two names are the convention:

| | |
|---|---|
| `errand-project.py` | what the **project** does: providers, compilation flags, `errand.configure`. Versioned |
| `errand-envs.py` | where **you**, on **your machine**, run it: the environments. Not versioned — `errand --init` adds it to `.gitignore` |

They are ordinary Python, loaded once by path and under a private name, with no entry point to call
and nothing to return. `errand.envs` holds the environments by name, and the first one declared is
the default unless `errand.default_env` names another:

```python
# errand-project.py
import errand

errand.configure( out = "runs", src = [ "core/src", "app/src" ] )
errand.provider( errand.Catch2( dir = "tests/cpp" ) )
```

```python
# errand-envs.py
import errand

errand.envs[ "local" ] = errand.Env( [ errand.Micromamba( "myenv", python = "3.13", requirements = "requirements.txt" ) ],
                                     driver = "jax" )
errand.envs[ "gpu" ]   = errand.Env( [ errand.Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def" ) ],
                                     driver = "jax", cuda = True )

errand.default_env = "local"
```

The root of the project is the nearest directory, walking up from the current one, that holds an
`errand-*.py`; `--root` overrides it. None of these files is ever taken for a file of entries.

```python
# errand-project.py
import errand

errand.configure(
    out     = "runs",   # where the output tree goes
    src     = [ ],      # paths prepended to every child's PYTHONPATH
    exclude = [ ],      # directories discovery must not walk into
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
can be committed and none of it can be invented, so it goes in an untracked **`errand-envs.py`**
beside the other project files, and an entry asks for what it needs by name:

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
      errand-envs.py does not exist yet. Create it (it is not tracked) with:
          ssh_host = 'gpu-box'
```

Reach for it only for what genuinely cannot be defaulted. `ssh localhost` is a real ssh, a real
rsync and a real round trip through a directory that is not the project's — only the hardware is
shared, and the hardware is rarely what is being tested. A suite that exercises the remote path on
anyone's machine is worth more than one that waits for a cluster.

A skip is its own status, in the output and in `result.yaml`. `skip( "reason" )` says it directly
for anything else that makes an entry inapplicable today. A suite that quietly tested nothing must
not be able to look like a suite that passed.

**The project files may read it too**, with `value` rather than `need`: an entry has the option of not
running, a project file has not — it is read once, before anything, and what it does not find it
must do without. That is what lets a host name, a remote root or a scratch directory stay out of
git while the declaration that uses them is committed, with a default that works here:

```python
# errand-project.py  ( ssh_host and ssh_root are defined in errand-envs.py, which is read first )
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = errand.value( "ssh_host", "gpu-box" ),
                                                     root = errand.value( "ssh_root", "/home/me/proj" ) ) ], cuda = True )
```

## Other languages

errand does not care what your tests are written in. An entry does not have to be a Python call
site. Providers for C++ (Catch2, GoogleTest, doctest),
Rust (`cargo test`, Criterion), JavaScript and plain executables come with `errand`, and one line
in `errand-project.py` puts an existing suite under it — with an output directory, summaries, environment
matrices and remote repatriation, none of which it had before:

```python
import errand
errand.provider( errand.Pytest( ) )
errand.provider( errand.Catch2( dir = "tests/cpp" ) )
errand.provider( errand.Cargo( ) )
```

A suite keeps everything that makes it itself, and its vocabulary is translated rather than
replaced: a `@pytest.mark.slow` is an entry tag, so `-e '!slow'` filters it with the same expression
language `-t` uses on environments; a Catch2 `[tag]` likewise; a framework's own benchmark numbers
land in `result.yaml` beside everyone else's.

A provider finds its own entries the way its ecosystem does — `pytest`'s collection rules, the
`test_*.cpp` under a directory, `cargo`'s targets. That is a guess about your layout, so it is a
guess you write down: a provider line in `errand-project.py` is the declaration of what will be looked for
and where, and it takes the arguments to say something else. With no `errand-*.py` at all, `errand`
reads the directory, guesses, and **tells you what it guessed** before running anything:

```text
  no errand-*.py; guessed:  pytest (tests/)  ·  catch2 (cpp/)  ·  cargo (rust/)   ( errand --init writes it down )
```

Convenient for a first look, never silent, and the cure is to write the line — which is what
`errand --init` does, making `runs/` and an `errand-envs.py` beside it. It never overwrites (`--init=force` does). Nothing
is run to guess: it lists directories and reads a few files.

Discovery over a large tree is not free, and will be cached against file mtimes. Later; it is an
optimization, not a design question.

**errand compiles nothing itself.** A provider that needs a build runs the command you already build
with, once, before any of its entries — not once per file, and not once per parallel process:

```python
import errand
errand.provider( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )
errand.provider( errand.Catch2( dir = "cpp", build = "cmake --build build", binary = "build/{stem}" ) )
```

`binary` says where a source's executable lands, defaulting to `<dir>/<stem>`. Leave `build` out if
something else already built them. Your compiler, your flags and your layout stay yours.

**A missing tool is installed when the environment is errand's to install into.** A `Pytest`
provider whose interpreter has no pytest installs it — into a venv, a micromamba environment, a
container — and says so. Into the *system* interpreter it declines and tells you what to run: that
one is shared with everything else on the machine, and it is not errand's to change.

`Pytest` asks pytest for its own tests rather than reimplementing its collection rules — that is how
a runner starts quietly disagreeing with the tool it wraps — so its entries are per test and its
marks are entry tags. `Catch2` is per *file*, because the cases of a compiled suite cannot be
enumerated without building it and `collect()` has to work before anything is built; the `::name`
goes to the binary as its own filter. `Cargo` asks `cargo metadata`, which knows the targets without
compiling any of them.

Writing a provider for something else is a three-method protocol; see the wiki.

## Status

Everything above works and is covered by errand's own suite, which is written with errand. Not
released: the API may still move.

Still to write: `errand init`, and providers beyond the three that ship (GoogleTest, doctest, ctest,
JavaScript).

One thing is deliberately left to you: a matrix that spans a laptop and a cluster partition at once
will produce numbers that are not comparable, and `errand` will not stop you. It runs what you ask
where you ask and records where each number came from; deciding what may be compared to what is
yours.

Known to be unresolved: what a summary should say *across* places. Min and max per row are enough to
read, but deciding that a machine got slower is a different question, and one that wants to know
something about noise.
