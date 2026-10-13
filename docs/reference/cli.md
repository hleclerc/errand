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
| `run [PATTERN]` | run entries, and record what came of them |
| `list [PATTERN]` | what the pattern matches, and the parameters each one takes — a dry run of it |
| `shell [-- COMMAND …]` | a shell in an environment, or COMMAND run in it. Nothing is recorded |
| `envs` | the environments, their tags, their stacks and their state |
| `setup [NAME,…]` | bring environments up to date now, and do nothing else |
| `init` | write an `errand-project.py` from what the directory holds |
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
| `--env NAME[,NAME…]` | environment(s) by name. A comma is a matrix |
| `-t`, `--env-tags` | an [expression](./expressions) over environment tags |
| `--<tag> VALUE` | one flag per tag name used anywhere in the `errand-*.py` files. A comma is a matrix |
| `--root PATH` | the project root. Default: found by walking up from the cwd for an `errand-*.py` |
| `--out PATH` | the output tree. Default: `errand.configure( out = … )`, itself `runs` |
| `-h`, `--help` | the help; after a verb, that verb's |
| `-V`, `--version` | which errand this is |

An option that belongs to another verb is an error rather than ignored: `errand shell --batch -- make`
says `--batch` is `run`'s.

## `run` and `list`

`PATTERN` is a comma-separated list of `path[::name]` targets: paths from the cwd, extension
included, globs on both sides — see [Running it](/guide/running#the-pattern). With no pattern,
everything [`bulk`](/guide/declaring-work#the-four-traits) under the cwd runs.

| flag | |
|---|---|
| `PATTERN` | `path[::name]`, comma-separated outside braces; `*` `?` `[…]` `{a,b}` on both sides, `**` on the path. A directory is everything under it |
| `-k`, `--kind` | `test`, `bench` (every entry whose numbers are kept: `bench` and `track`) or `experiment` (`exp` is accepted). Repeatable |
| `-e`, `--entry-tags` | an [expression](./expressions) over the tags written on an entry |
| after the target | the target's own arguments: its `sys.argv`, or its command line. Any parameter a matched entry declares is read out of them ( `--n=5`, `--n 5` ), the rest passes through, `--env` and `--` included. A comma is a [matrix](/guide/matrices) on either ( `\,` is a comma, `,,` an empty value ). With no target, there are none: `.` is the target for everything here |

`run` only:

| flag | |
|---|---|
| `-j N`, `--jobs N` | N entries at a time, one process each. `auto` means as many as the machine has cores. Default 1 |
| `--batch` | launch and give the shell back — [detached](/guide/detached) |
| `--no-setup` | skip the freshness check for this run |
| `--no-queue` | this run does not wait, and does not hold |
| `--at FILE:LINE` | run exactly the entry at that call site. This is how errand's own child processes are started; you will not normally type it |

With no `errand-*.py`, the directory is read the way `init` reads it, and what was guessed is
announced.

## `shell`

With no `-- COMMAND`, an interactive shell — yours when the place has it, `sh` otherwise — in the
environment named, or the default one: through its layers, over ssh, inside its container, in an
allocation. With `-- COMMAND` and an environment, COMMAND runs [in that
environment](/guide/upkeep#being-let-into-one). With `-- COMMAND` and **no** environment, it runs on
this machine, once the queue lets it.

| flag | |
|---|---|
| `--pull DIR` | on another machine: bring DIR ( relative to the project root ) back afterwards. Repeatable |
| `--no-setup` | do not bring the environment up to date first |
| `--no-queue` | do not wait for the machine |
| `-x`, `--claim-exclusive` | no environment: the machine to itself — what a measurement wants |
| `--claim-cpus N` | no environment: cores the command needs |
| `--claim-ram 8G` | no environment: memory the command needs |
| `-m`, `--claim-mem 24G` | no environment: memory *ceiling*. Default `8G`, `24G` when exclusive |
| `-n`, `--claim-label NAME` | no environment: its name in `errand queue` |
| `-l`, `--claim-log FILE` | no environment: stdout and stderr go there |
| `-q` | no environment: no banner |

```bash
errand shell --env gpu
errand shell --env cluster -- nvidia-smi
errand shell -- make -j16
errand shell -x -- ./bench --n 1e7
errand shell -l build.log -n nightly -- ./all
```

See [Any command, under the queue](/guide/machine#any-command-under-the-queue).

## `setup` and `init`

| flag | |
|---|---|
| `setup NAME,…` | the same as `--env NAME,…`; with neither, the default environment |
| `--force` | `setup`: rebuild from scratch. `init`: replace an existing `errand-project.py` |
| `--dry-run` | `setup`: say what it would run, and run nothing |

`init` writes an `errand-project.py` from what the directory holds — [what it looks
for](/guide/start#what-it-looks-for) — and a commented `errand-envs.py`, and makes `runs/`. It never
overwrites without `--force`. See [Keeping environments current](/guide/upkeep).

## Recipes

```bash
errand run                         # everything bulk, default environment
errand list "bench/solvers.py::*"  # what would run, and with which parameters
errand run -k bench --env gpu,cluster --fp 32,64 --batch
errand watch
errand run -j 4 bench/solvers.py::cost --n=1000,5000
errand run -e 'slow & !gpu' -t 'cuda & !remote'
errand shell --env cluster -- nvidia-smi
errand queue
errand setup --dry-run
```

## Exit status

Non-zero when anything failed — including a candidate file that could not be imported, which
[costs its own row and takes the return code with it](/guide/running#a-file-that-will-not-import).
A [skip](/guide/configuration#what-only-this-machine-can-supply) is its own status and is not a
failure, but it is never silent either.
