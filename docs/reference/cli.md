# Command line

```
errand [options] <verb> [arguments]
```

One verb per action. `errand` alone prints the help and runs nothing; `errand <verb> --help` says
what that verb takes. The options that choose environments and paths are everybody's, and may stand
before the verb or after it — but before the target, for `run` and `list`, since what follows the
target is the target's: `errand --env gpu run t.py` and `errand run --env gpu t.py` are the same.

| verb | |
|---|---|
| `run [TARGET [ARGS…]]` | run a file, a command or entries, in one or several environments, and record what came of it |
| `list [TARGET]` | what the target designates, and the parameters each one takes — a dry run of it |
| `shell` | an interactive shell in an environment. Nothing is recorded |
| `envs` | the environments, their tags, their stacks and their state |
| `setup [NAME,…]` | bring environments up to date now, and do nothing else |
| `init` | write a starting `errand-project.py` and `errand-envs.py`, with suggestions in comments |
| `tui` | [the screen](/guide/tui) |
| `queue` | what the host has, and what is holding it |
| `wait` | return once nothing holds the machine and nothing is queued for it |
| `status` | how the [detached](/guide/detached) work is going; one shot, plain text |
| `watch` | the same, live, until everything has landed |
| `forget ID` | drop a submission from the list, keeping its results |
| `vm stop` | stop the [virtual machines](./layers#windows) kept warm between commands |

## Everybody's options

| flag | |
|---|---|
| `--env NAME[,NAME…]` | environment(s) by name. A comma is a matrix, which is why a name cannot hold one |
| `-t`, `--env-tags` | an [expression](./expressions) over environment tags |
| `--<tag> VALUE` | one flag per tag name used anywhere in the `errand-*.py` files. A comma is a matrix |
| `--root PATH` | the project root. Default: found by walking up from the cwd for an `errand-*.py` |
| `-h`, `--help` | the help; after a verb, that verb's |
| `-V`, `--version` | which errand this is |

An option that belongs to another verb is an error rather than ignored: `errand shell --batch`
says `--batch` is `run`'s.

## `run` and `list`

The first word after errand's options is the target, read from the command line alone:

- `path::name` (globs on both sides) goes to an **entry runner** — errand's own entries, pytest,
  Catch2, cargo. Which one takes a file is decided by its contents; two claiming it equally is an
  error, and `-r NAME` settles it.
- a bare `x` goes to a **file runner**: a `.py` is run by the place's Python, anything else is
  executed as it is — a file of the project, or a command on the place's `PATH` (`make`, `cmake`,
  `pytest`). A glob without `::` runs each matching file that can be run, one run each. A directory
  without `::` is an error: `dir/**::*` is the entries under it.

Several targets are separated by commas — see [Running it](/guide/running#the-target). With no
target, `run` runs `errand.default_run`, the targets the project declares in `errand-project.py`
(from the project root), keeping only what is [`bulk`](/guide/declaring-work#the-four-traits); with
none declared it prints this help.

| flag | |
|---|---|
| `TARGET` | `path::name` or a file or command, comma-separated outside braces; `*` `?` `[…]` `{a,b}` on both sides, `**` on the path |
| `-r`, `--runner NAME` | the runner that takes every target, by its name in `errand.runners`, claiming nothing |
| `-k`, `--kind` | `test`, `bench` (every entry whose numbers are kept: `bench` and `track`) or `experiment` (`exp` is accepted). Repeatable |
| `-e`, `--entry-tags` | an [expression](./expressions) over the tags written on an entry |
| after the target | the target's own arguments: its `sys.argv`, or its command line, passed as written, `--env` and `--` included. A parameter an errand entry declares is read out of them ( `--n=5`, `--n 5` ), and there a comma is a [matrix](/guide/matrices) ( `\,` is a comma, `,,` an empty value ). Anything else is not gridded |

`run` only:

| flag | |
|---|---|
| `-j N`, `--jobs N` | N entries at a time, one process each. `auto` means as many as the machine has cores. Default 1 |
| `--batch` | launch and give the shell back — [detached](/guide/detached) |
| `-o` | a visible output directory for each run, under `runs/` ( `errand.configure( out = … )` ), exported as `$ERRAND_OUT_DIR` and brought back |
| `--out PATTERN` | the same under another tree, or a pattern: `"results/{env}/{when}"`, with `{path}` `{name}` `{when}` `{place}` `{env}` `{params}` |
| `--no-setup` | skip the freshness check for this run |
| `--no-queue` | this run does not wait, and does not hold |
| `--pull DIR` | on another machine: bring DIR ( relative to the project root ) back afterwards. Repeatable |
| `-x`, `--exclusive` | the machine to itself — what a measurement wants |
| `--cpus N` | cores it needs |
| `--ram 8G` | memory it needs |
| `--gpus N` | cards it needs |
| `--time T` | how long it may take, for a batch system ( slurm's way: `30`, `2:00:00`, `1-12` ) |
| `-m`, `--mem 24G` | memory *ceiling* of the command ( `systemd-run`, where there is one ) |
| `-n`, `--label NAME` | its name in `errand queue` |
| `-l`, `--log FILE` | its output goes there too |
| `-q` | no banners |
| `--at FILE:LINE` | run exactly the entry at that call site. This is how errand's own child processes are started; you will not normally type it |

Every run is recorded, privately, in errand's state directory ( `.errand/runs/…` ) — the history,
the screen, `status` and `--batch` read it there. A visible directory is made only with `-o` or
`--out`; see [Output](/guide/output).

```bash
errand run --env gpu python -c "import torch; print( torch.cuda.is_available() )"
errand run make -j16
errand run -x ./bench --n 1e7
errand run -l build.log -n nightly ./all
```

See [Any command, under the queue](/guide/machine#any-command-under-the-queue).

## `shell`

An interactive shell — yours when the place has it, `sh` otherwise — in the environment named, or
the default one: through its layers, over ssh, inside its container, in an allocation. It takes no
command: `errand run --env X cmd args` runs one.

| flag | |
|---|---|
| `--pull DIR` | on another machine: bring DIR ( relative to the project root ) back afterwards. Repeatable |
| `--no-setup` | do not bring the environment up to date first |

```bash
errand shell --env gpu
```

## `setup` and `init`

| flag | |
|---|---|
| `setup NAME,…` | the same as `--env NAME,…`; with neither, the default environment |
| `--force` | `setup`: rebuild from scratch. `init`: replace an existing `errand-project.py` |
| `--dry-run` | `setup`: say what it would run, and run nothing |

`init` writes an `errand-project.py` holding, in comments, the runner lines that would fit what the
directory holds and a `default_run` suggestion, and a commented `errand-envs.py`. Nothing in them is
active until you uncomment it; `run` itself never guesses. It never overwrites without `--force`. See
[Keeping environments current](/guide/upkeep).

## Recipes

```bash
errand run                         # errand.default_run, default environment
errand list "bench/solvers.py::*"  # what would run, and with which parameters
errand run -k bench --env gpu,cluster --fp 32,64 --batch '**::*'
errand watch
errand run -j 4 bench/solvers.py::cost --n=1000,5000
errand run -e 'slow & !gpu' -t 'cuda & !remote' '**::*'
errand run --env cluster nvidia-smi
errand run -o --env gpu train.py --epochs 3
errand queue
errand setup --dry-run
```

## Exit status

Non-zero when anything failed — including a candidate file that could not be imported, which
[costs its own row and takes the return code with it](/guide/running#a-file-that-will-not-import).
A [skip](/guide/configuration#what-only-this-machine-can-supply) is its own status and is not a
failure, but it is never silent either.
