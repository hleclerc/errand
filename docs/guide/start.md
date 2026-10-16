# Getting started

errand asks nothing of your project first. Start from a command you already run, then say where
else you would like it to run.

## A command, here

```bash
cd my-project
errand run make check              # what you would have typed, after `errand run`
errand run train.py --lr 1e-3      # a .py: run by the python of the place
errand run -x ./bench              # the machine to itself while it runs
```

Nothing is guessed: the first word after errand's options is a `.py`, a file to execute, or a
command of the place — and everything after it is that command's own. Each run is recorded in
`.errand/` (what ran, how it ended, what it printed); `-o` gives it a directory of its own as well,
under `runs/`, handed to the command as `$ERRAND_OUT_DIR`.

## Then: somewhere else

```bash
errand init      # a commented errand-envs.py, and an errand-project.py with suggestions
```

Uncomment and adapt the stack of [layers](./environments) in `errand-envs.py` — where *you* run the
project:

```python
# errand-envs.py
import errand

errand.envs[ "local" ]   = errand.Env( [ errand.Micromamba( "myproject", python = "3.13",
                                                           requirements = "requirements.txt" ) ] )
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "~/errand/myproject" ),
                                         errand.Slurm( partition = "gpu", time = "00:30:00" ),
                                         errand.Apptainer( image = "containers/main.sif", recipe = "containers/main.def" ) ] )
```

```bash
errand envs                                  # what is declared, and in what state
errand run --env local make check            # the micromamba environment is made first
errand run --env cluster python train.py     # pushed, allocated, contained, run
errand run --env local,cluster ./bench       # in both places
errand shell --env cluster                   # be let in, to look
```

The environments are built the first time they are needed, checked against what you declared before
every run after that, and brought up to date when the declaration changes. Over ssh the project is
rsynced there first; `--pull DIR` and `-o` say what comes back.

<Term scene="stack" caption="What a single --env cluster crosses. Ssh, Slurm and Apptainer are declared once, as layers." />

## A suite, test by test

A suite can be run as a command — `errand run --env cluster pytest` — and that is often enough.
Written `path::name`, its tests become **entries**: one run each, recorded each, filtered by their
marks and tags.

::: code-group

```bash [pytest]
errand run 'tests/**::*'                 # every test under tests/
errand run tests/test_api.py::test_ok    # one of them
errand run -e '!slow' 'tests/**::*'      # @pytest.mark.slow is an entry tag
```

```bash [C++ · Catch2]
errand run 'cpp/**::*'                   # built once, in the place, then each case
errand run cpp/test_geometry.cpp::area   # one case, by name
```

```bash [Rust · cargo]
errand run 'src/**::*'                   # one entry per test target
```

```bash [errand's own entries]
errand run 'bench/**::*'                 # files that `if track( "cost" ):` -- see Writing entries
```

:::

Which runner takes a file is read from the file — a pytest test, a Catch2 source, a cargo target,
a file of errand's own entries — and the defaults need no line at all. When they do not fit, or to
say what a bare `errand run` means, `errand-project.py` says it:

```python
# errand-project.py
import errand

errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )   # how it is built
errand.runners[ "bench" ] = errand.Pytest( dirs = [ "tests/bench" ] )          # errand run -r bench …
errand.default_run = [ "tests/**::*", "cpp/**::*" ]                            # a bare `errand run`
```

`errand init` writes the lines that fit what it finds here — in comments, for you to keep or not.
The detail of each runner is in [Runners](./runners).

## Next

[Environments](./environments) for the layers, [Running it](./running) for targets and options, or
the [tutorials](/tutorials/).
