# Command line

```
errand [PATTERN] [options] [-- COMMAND …]
```

`PATTERN` is a comma-separated list of `file[::name]` specs, both sides globbable — see
[Running it](/guide/running#the-pattern). With no pattern, everything
[`bulk`](/guide/declaring-work#the-four-traits) runs.

## Selecting work

| flag | |
|---|---|
| `PATTERN` | `file[::name]`, comma-separated; fnmatch on both sides. The file part matches the full stem |
| `-k`, `--kind` | `test`, `bench` (every entry whose numbers are kept: `bench` and `track`) or `experiment` (`exp` is accepted). Repeatable |
| `-e`, `--entry-tags` | an [expression](./expressions) over the tags written on an entry |
| `-h`, `--help` | show what matched, and the parameters each one takes — a dry run of the pattern |
| `--<param>` | any parameter declared by a matched entry. A comma is a [matrix](/guide/matrices) |

## Starting a project

| flag | |
|---|---|
| `--init` | write an `errandfile.py` from what the directory holds — [what it looks for](/guide/start#what-it-looks-for) — and make `runs/`. Never overwrites |
| `--init=force` | replace an existing one |

With no `errandfile.py`, the same reading is done for the run itself, and announced.

## Choosing where

| flag | |
|---|---|
| `--env NAME[,NAME…]` | environment(s) by name. A comma is a matrix |
| `-t`, `--env-tags` | an [expression](./expressions) over environment tags |
| `--<tag> VALUE` | one flag per tag name used anywhere in `errandfile.py`. A comma is a matrix |
| `--envs` | list the environments, their tags, their stacks and their state — then stop |

## Preparing environments

| flag | |
|---|---|
| `--setup` | bring environments up to date now, and do nothing else |
| `--setup=force` | rebuild from scratch |
| `--no-setup` | skip the freshness check for this run |
| `--dry-run` | with `--setup`: say what it would run, and run nothing |

See [Keeping environments current](/guide/upkeep).

## Running

| flag | |
|---|---|
| `-j N`, `--jobs N` | N entries at a time, one process each. `auto` means as many as the machine has cores. Default 1 |
| `--batch` | launch and give the shell back — [detached](/guide/detached) |
| `--tui` | [the screen](/guide/tui) |
| `-- COMMAND …` | with `--env`: run COMMAND *in* that environment. Without: run it here, under the queue |

## The queue

| flag | |
|---|---|
| `--queue` | what the host has, and what is holding it — then stop |
| `--wait` | return once nothing holds the machine and nothing is queued for it — then stop |
| `--no-queue` | this run does not wait, and does not hold |

See [Sharing the machine](/guide/machine).

## Any command, under the queue

A bare `--` with **no** `--env` runs that command on this machine, once the queue lets it. With an
`--env` it runs [in that environment](/guide/upkeep#being-let-into-one) instead.

| flag | |
|---|---|
| `-x`, `--exclusive` | the machine to itself — what a measurement wants |
| `--cpus N` | cores the command needs |
| `--ram 8G` | memory the command needs |
| `-m`, `--mem 24G` | memory *ceiling*. Default `8G`, `24G` when exclusive |
| `-n`, `--label NAME` | its name in `errand --queue` |
| `-l`, `--log FILE` | stdout and stderr go there |
| `-q`, `--quiet` | no banner |

```bash
errand -- make -j16
errand -x -- ./bench --n 1e7
errand -l build.log -n nightly -- ./all
```

See [Any command, under the queue](/guide/machine#any-command-under-the-queue).

## Detached work

| flag | |
|---|---|
| `--status` | how the launched work is going; one shot, plain text |
| `--watch` | the same, live, until everything has landed |
| `--forget ID` | drop a submission from the list, keeping its results |

## Paths

| flag | |
|---|---|
| `--root PATH` | the project root. Default: found by walking up from the cwd for `errandfile.py` |
| `--out PATH` | the output tree. Default: `configure( out = … )`, itself `runs` |
| `--at FILE:LINE` | run exactly the entry at that call site. This is how errand's own child processes are started; you will not normally type it |

## Other

| flag | |
|---|---|
| `-V`, `--version` | which errand this is |

## Recipes

```bash
errand                                    # everything bulk, default environment
errand --help "solvers::*"                # what would run, and with which parameters
errand -k bench --env gpu,cluster --fp 32,64 --batch
errand --watch
errand "solvers::cost" --n=1000,5000 -j 4
errand -e 'slow & !gpu' -t 'cuda & !remote'
errand --env cluster -- nvidia-smi
errand --queue
errand --setup --dry-run
```

## Exit status

Non-zero when anything failed — including a candidate file that could not be imported, which
[costs its own row and takes the return code with it](/guide/running#a-file-that-will-not-import).
A [skip](/guide/configuration#what-only-this-machine-can-supply) is its own status and is not a
failure, but it is never silent either.
