# Quickstart

errand asks nothing of your project first. Start from a command you already run, then say where
else it should run.

## 1. A command, here

```bash
cd my-project
errand run make check              # what you would have typed, after `errand run`
errand run train.py --lr 1e-3      # a .py: run by the python of the place
```

The first word after errand's options is a `.py`, a file to execute, or a command; everything after
it belongs to that command. Each run is recorded in `errand-outputs/runs/`: what ran, how it ended,
what it printed.

## 2. Declare a place

```bash
errand init      # writes a commented errand-envs.py
```

Uncomment and adapt it. Each environment is a stack of [layers](./environments), read from the
outside in: *that machine, an allocation on it, a container, your command*.

```python
# errand-envs.py
import errand

errand.envs[ "local" ]   = errand.Env( [ errand.Micromamba( "myproject", python = "3.13",
                                                           requirements = "requirements.txt" ) ] )
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "~/errand/myproject" ),
                                         errand.Slurm( partition = "gpu", gpus = 1, time = "1:00:00" ),
                                         errand.Apptainer( image = "containers/main.sif", recipe = "containers/main.def" ) ] )
```

```bash
errand envs              # what is declared, and in what state
errand setup --dry-run   # what getting them ready would run
```

## 3. Run it there

```bash
errand run --env local make check            # the micromamba env is created first
errand run --env cluster python train.py     # pushed, allocated, contained, run
errand shell --env cluster                   # get in and look around
```

Environments are built the first time they are needed, checked before every run, and updated when
the declaration changes. An environment that already exists is adopted, not rebuilt.

<Term scene="stack" caption="What --env cluster crosses: Ssh, Slurm and Apptainer, declared once." />

## 4. Get the results back

```bash
errand run --env cluster --pull out python train.py   # out/ comes back here afterwards
errand run --env cluster -o ./simulate                 # a directory per run, brought back
```

With `-o`, the command gets `$ERRAND_OUT_DIR`, a fresh directory for this run, made over there and
fetched into `errand-outputs/runs/` here. → [Results and records](./output)

## 5. Let it run, and find it again

```bash
errand run --batch --env cluster python train.py   # the shell comes back at once
errand status                                      # what runs, on every machine
errand attach                                      # follow a run again, results included
```

Close the laptop whenever you like: the work goes on over there. `errand status` lists what runs
on every machine you sent work to, and Ctrl-C on a followed run stops it through every layer.
→ [What is running](./status), [Let it run](./detached)

## Next

- [Environments](./environments) and the [layers](./layers/), one by one
- [Running](./running): targets, options, `errand shell`
- [Four environments](/tutorials/environments), a guided tour
- A pytest, Catch2 or cargo suite, test by test: [Running a suite](./runners/)
