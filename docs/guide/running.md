# Running a command

```bash
errand run python train.py --epochs 3       # here, in the default environment
errand run --env cluster python train.py    # the same, through the layers of `cluster`
errand run train.py --epochs 3              # a .py: run by the place's python
errand run --env box make -j16              # a command of the place
errand run --env box ./bench --n 1e7        # a file of the project, executed as it is
errand shell --env cluster                  # a shell there, to type into
```

The output arrives in your terminal as it is written, Ctrl-C stops the work wherever it runs, and the
exit code is the command's. What changes from typing it yourself is that errand set the place up
first, pushed the project there, and keeps a [record](./output) of the run.

## The target

The first word after errand's options is the **target**. What follows it belongs to the target.

- A **`.py` file** is run by the Python of the place: the container's, the micromamba environment's.
- **Any other file** of the project is executed as it is: `./bench`, a script with a shebang.
- **A command** is looked for on the place's `PATH`: `make`, `cmake`, `nvidia-smi`, `pytest`.
  `python` and `python3` as first word are replaced by the interpreter of the place
  ( [The interpreter](./layers/#the-interpreter) ).
- **Several files of one kind** in a row are several targets: `errand run scripts/*.py`, the glob
  expanded by the shell, runs each of them. The files that follow the first and have its suffix are
  targets too, up to the first word that is not one; a file meant as an argument goes after `--`.
- A comma separates targets ( `prep.py,train.py` ); `\,` is a comma that is only a comma.
- **No target** runs `errand.default_run`, the targets the project declares in `errand-project.py`.
  With none declared, errand prints the help and says so.

A target that designates nothing is an error, not an empty run: a file must exist, a command must be
on the place's `PATH`. That check happens in the environment, since only the place knows what it has.

Targets of the form `path::name` run tests and entries one by one: see
[Running a suite test by test](/guide/runners/).

## What follows the target is the target's

errand's options go **before** the target; everything after it, `--env` included, is handed to what
runs, as written:

```bash
errand run --env gpu python train.py --env prod   # train.py gets --env prod
errand run -- ./tool --help                       # after --, nothing is errand's
```

errand's options can stand before or after the verb: `errand --env gpu run …` and
`errand run --env gpu …` are the same command. An option written after the target that errand
would have read is the target's; an unknown option before it is an error, which says to move it.

The arguments are part of the run's name in its [record](./output), so `--size 4096` and
`--size 8192` are two runs. A comma in an argument is only a comma: to run a script over several
values, see [Several runs: grids](./matrices).

## Exit codes

The command's exit code is the run's status: `0` passes, anything else fails. **`77` is a skip**, as
in automake and meson, for a script that finds it does not apply here. With several targets or
several environments, errand returns non-zero when one of them failed. Ctrl-C returns `130`.

## Options

| option | |
|---|---|
| `--env NAME` | the [environment](./environments). Several, under `--grid` |
| `-t EXPR`, `--<tag> VALUE` | environments by [tag](./tags) |
| `--grid=SEP` | several values make [several runs](./matrices), split on SEP |
| `-o` | a [directory for the run's own files](./output#its-own-directory-o), handed as `$ERRAND_OUT_DIR` and brought back |
| `--out PATTERN` | the same, under another tree or a pattern of your own |
| `--pull DIR` | from another machine, bring this directory of the project back after the command. Repeatable |
| `--batch` | launch it and give the shell back ( [Let it run](./detached) ) |
| `--no-setup` | do not check that the environment is up to date ( [Keeping environments current](./upkeep) ) |
| `-x`, `--exclusive` | the machine to itself ( [Sharing a machine](./machine) ) |
| `--cpus N`, `--ram 8G`, `--gpus N` | what it needs, counted against the machine, or asked of Slurm |
| `--ranks N` | that many MPI processes ( [Several processes](./mpi) ) |
| `--time T` | how long it may take, for Slurm: `30`, `2:00:00`, `1-12` |
| `-m`, `--mem 8G` | a memory ceiling for the command, where systemd allows it |
| `--no-queue` | do not wait for the machine, and do not hold it |
| `-n`, `--label NAME` | its name in `errand queue` |
| `-l`, `--log FILE` | its output goes there too |
| `-q` | no banners |
| `-v`, `--verbose` | print every command errand starts, here and over there ( [When something breaks](./upkeep#when-something-breaks) ) |
| `--root DIR` | the project root, when it cannot be found from the current directory |

`-j`, `-k`, `-e` and `-r` are about tests and entries: see [Running a suite](/guide/runners/).
Every option, for every verb: [Command line](/reference/cli).

## Seeing what it does

```bash
errand -v run --env cluster python train.py
```

`-v` prints, on stderr, every process errand starts before it starts: the rsync, the ssh line, the
image build, the `sbatch`, the errand over there. Nothing errand does to reach the place is hidden.
→ [When something breaks](./upkeep#when-something-breaks)

## A shell in an environment: `errand shell`

```bash
errand shell --env cluster            # in the allocation, the container, the environment
errand shell --env gpu --pull plots   # bring plots/ back when the shell exits
errand shell --env win                # cmd.exe in the Windows machine
```

The same place a run would go to, through the same layers, with the project pushed and the
environment brought up to date first ( `--no-setup` skips that ). It is your own `$SHELL` when the
place has it, else `sh`. It is a real terminal: colours, line editing, full-screen programs, Ctrl-C
as a key, resizing.

`errand shell` takes no command: `errand run` runs one. Besides choosing the environment, its options
are `--pull`, `--no-setup` and `--grid` ( one shell after the other ).

## Next

[Results and records](./output): what a run leaves behind, and how it comes back.
