---
status: accepted
date: 2026-10-13
---

# Verbs, path targets, runners ranked by suitability, a comma grid everywhere

The command line was one command with flags for everything (`--envs`, `--setup`, `--queue`,
`--status`, `--init`, `--tui`, `-- cmd`), and a target was a file *stem* looked up anywhere in the
tree. It made errand hard to guess: what a word on the command line meant depended on which flags
were around it, and a stem did not say which file it meant. So we break it, with no compatibility
layer (errand is unreleased), and settle on the following.

**Verbs.** One verb per action: `run`, `shell`, `list`, `envs`, `setup`, `init`, `tui`, `queue`,
`wait`, `status`, `watch`, `forget`. A bare `errand` prints the help and runs nothing: an implicit
`run` would make a file called `list` or `setup.py` collide with a verb. Only `run` launches work;
`test`/`bench` are not verbs, the kind stays a filter (`-k`). `shell` is both the interactive shell
of an environment and, with `-- cmd`, one command in it (as `guix shell -- cmd` does). `shell`
records nothing; `run` records everything (output directory, `result.yaml`, queue claim, grid).

**Targets are paths.** `errand [options] run [options] <targets> <args…>`. A target is a path
relative to the cwd, extension included, then optionally `::` and an entry name. Both sides are
full globs (`**`, `{}`, `[]`) — consistency won over letting a parametrized pytest id
(`test_x[3]`) through unescaped. A path without a glob that does not exist is an error, and so is
a glob that matches nothing. With no target, `run` takes the bulk entries under the cwd.
Everything after the targets belongs to them (their `sys.argv`): errand is a runner, and arguments
after the thing to run are for the thing to run. An errand option written after the target is
passed on, not detected.

**One grid syntax: the comma.** A comma means several values of an axis, and the cartesian product
is run: targets (commas outside braces), environments, tags, declared parameters — list-typed ones
included — and raw arguments. `\,` is a literal comma (it must be quoted for the shell); `,,` means
an empty element, not an escape. On a raw `--option=value` the axis is the value, as on a
declared parameter. The expanded grid is shown before launching. We considered `+`
and an unusual unicode separator: no separator spares the escaping (the shell eats the backslash
whatever follows it), a unicode one cannot be typed or guessed and does not survive a `LANG=C`
remote shell, an `sbatch` script or a Windows code page, and two separators would bring back the
question of which does what. The known cost: `-Wl,-rpath` or `--dims=1,2,3` passed raw must be
escaped, and the printed grid is what catches the omission.

**Runners replace providers.** `errand.runners` is a list, pre-filled with the built-in runners
(errand files, pytest, catch2, cargo, a python script, an executable, a shell script…), which the
project edits with plain list operations. A runner answers three questions:

- `suitability( file )`: one of `NONE < FALLBACK < LANGUAGE < FRAMEWORK < ERRAND`. The highest
  wins and a tie at the top is an error naming the contenders, so the order of the list never
  changes the result. Discrete levels rather than free floats, which would become a hidden order.
- `collect( file )`: one file or N entries. Only the runner knows whether its ecosystem can
  enumerate; one that cannot returns the whole file as a single entry, and `file::x` is handed to
  it as a filter or refused. A runner that must compile to enumerate (Catch2) compiles — in every
  selected environment, inside it, into a `{build_dir}` errand provides (`build/{env}/`, also
  exported as `ERRAND_BUILD_DIR`), so two environments never share a binary.
- `run( entry )`.

`ERRAND` and `FRAMEWORK` files are *discoverable*: a glob or a bare `run` picks them up.
`LANGUAGE` and `FALLBACK` files are taken only when named without a glob — otherwise
`run '**/*.py'` would execute every library module as a script.

**Parameters.** `Param` is a declared, typed reading of `sys.argv`; undeclared arguments are passed
through untouched. A file declaring entries does nothing when run by hand: one way to launch.

**Output.** `runs/{path relative to the root, extension kept}/{name}/{when}-{place}[-{params}]/`.
There is no `{name}` level for a whole-file entry, and raw arguments are part of `{params}`.

**Environments.** They stay `errand.envs[ name ] = …`, so an alias is one assignment. The name typed
is the place: an alias is never replaced by the first name it was declared under.
