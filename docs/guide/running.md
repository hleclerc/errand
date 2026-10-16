# Running it

```bash
errand run                                # what the project declares in errand.default_run
errand run train.py --epochs 3            # a script, by the place's python, with its arguments
errand run make -j16                      # a command of the place
errand run "bench/solvers.py::*"          # every entry in that file
errand run bench/solvers.py::solve        # just that one
errand run "bench/solvers.py::grad_*"     # a glob on the name; no glob means exact
errand run "**/test_*.py::{basic,quick}"  # any depth, and alternatives
errand run "bench/solvers.py::*,tests/**::*"  # several targets; dir/**::* is all of it
errand run -k bench '**::*'               # benchmarks only
errand run -k exp "bench/solvers.py::*"   # experiments only, in that file
errand list '**::*'                       # the matched entries, with their parameters
errand tui                                # one screen: tick what to run, watch it run
```

## The target

The first word after errand's options is the target: a comma-separated list, each read **from the
command line alone**, never from what the directory looks like.

- `path::name` goes to an **entry runner** — errand's own entries, [pytest, Catch2,
  cargo](./runners). Which one takes a file is decided by its contents; two taking it equally is an
  error that names them, and `-r NAME` settles it.
- A bare `x` goes to a **file runner**: a `.py` is run by the place's Python, anything else is
  executed as it is — a file of the project (`./bench`, a script with a shebang), or a command on
  the place's `PATH` (`make`, `cmake`, `pytest`). `errand run pytest tests/` is the pytest command,
  not the pytest runner. A file of errand entries named this way is run as a script, which is said:
  its entries are `file.py::*`.
- The **path** is read from the directory you are in, extension included: what the shell completes
  and what pytest prints. A directory alone is an error: `dir/**::*` is the entries under it, and
  `'**::*'` everything here.
- Both sides are **globs**, the same on both sides: `*` and `?` inside a name, `[…]` a class,
  `{a,b}` alternatives, and `**` any depth of directories on the path side. No glob means exact. A
  glob without `::` runs each matching file that can be run, one run each.
- A comma outside braces separates targets; `\,` is a comma that is only a comma.
- Several **files** in a row are several targets: `errand run tests/test_*.py`, the glob left to the
  shell, is `tests/test_a.py,tests/test_b.py`. The files that follow a file target and have its
  extension are targets too, up to the first word that is not one; such a file meant as an argument
  goes after a `--`.
- With no target, `errand run` runs `errand.default_run`, the targets the project declares in
  `errand-project.py`, read from the project root — keeping, among errand's own entries, the
  [bulk](./declaring-work#the-four-traits) ones. With none declared, it prints the help.

**What follows the target is the target's.** errand's options go before it; everything after it —
`--env` included — is handed to what runs: the `sys.argv` of an errand file, the command line of a
script, an executable, pytest or Catch2, what follows `--` for `cargo test`. Declared `Param`s are
read out of it, and there a comma is a [matrix](./matrices): `--n=1,2` is two runs. The rest passes
through **as written** — `--size 1,2` is one run, given `1,2` — and is part of the run's name, since
`--size 4096` and `--size 8192` are two runs. With no target there is nothing to hand arguments to.

A target that designates nothing is an **error**, not an empty run: a path with no glob must exist,
a glob must match a file that can be run (or, with `::`, that an entry runner takes), and a
`::name` must match an entry of the files it is about — with the closest thing there is, when there
is one. A command must exist on the place's `PATH`.

::: tip `errand list` is a dry run
`errand list` with a target shows what matched and what parameters each one takes. It is the
quickest way to find out whether your target means what you think.
:::

## What counts as a candidate file

For errand's own entries, behind a `::`, finding candidate files is a **text check, not an
import**: a file is a candidate if it *imports* `errand`.

So a source file that happens to share its entry's name — `Cell.py` next to `test_Cell.py` — is
never mistaken for one. And neither is a file that merely mentions errand in a comment, which would
otherwise be imported and executed on the strength of a word.

A directory holding an `errand-*.py` of its own is **another project**, and is not walked into: its
entries would run with this project's `src`, runners and environments, which is to say wrongly.

Directories you want skipped for other reasons — vendored code, fixtures, a copy of something that
would be imported and should not be — go in `errand.configure( exclude = [ … ] )`.

## A file that will not import

A candidate that will not import — a missing dependency, an example nobody set up — **costs its own
row and nothing else.** Everything readable still runs; what could not be read is listed at the
end, and takes the return code with it.

Tolerant, not silent. Half a project installed is an ordinary state of affairs, and an empty screen
is a poor way of saying so.

If the reason is that the file only applies to *some* environments, exit before the import rather
than letting it fail — see [skipping a file that does not apply](./tags#skipping-a-file-that-does-not-apply).

## Narrowing by kind and by tag

```bash
errand run -k bench '**::*'          # kind: test | bench | exp
errand run -k bench -k exp '**::*'   # repeatable
errand run -e 'slow & !gpu' '**::*'  # entry tags
errand run -e '!legacy' -k bench "bench/solvers.py::*"
```

`-k` names the kind, which is the preset the entry was declared with. `-e` reads the
[expression language](/reference/expressions) over the entry's own tags — and for an
[adopted suite](./runners), a `@pytest.mark.slow` or a Catch2 `[tag]` is one of those tags, so the
same expression filters them.

## Several at a time

```bash
errand run -j 8 '**::*'     # eight entries at a time
errand run -j auto '**::*'  # as many as the machine has cores
errand run '**::*'          # one at a time: the default
```

`-j` runs **one process per entry**, because the isolation between entries is the module reload, and
a reload only isolates within one interpreter.

A serial run stays in this process, where it is faster and its output arrives live. Each parallel
entry's output is held and printed whole, in completion order — interleaved lines from several
entries at once are unreadable and, worse, unattributable. What came of a child is read back from
its result file rather than parsed out of its chatter: the path was worked out before the child
started, and the file is the record either way.

While a run is parallel its output is still live *in its record*: `output.txt` is written as the
run talks — under `.errand/runs/`, or the visible tree with [`-o`](./output) — so `tail -f` works on
it, and so does [the screen](./tui).

## Running something in an environment, without an entry

```bash
errand run --env gpu python -m mypkg.toolchain  # that command, in that environment
errand run --env cluster nvidia-smi             # on the other machine, through ssh
errand run --driver torch python -c "import torch; print( torch.__version__ )"
errand shell --env gpu                          # a shell there, to type into
```

Everything after the target is the command's, not errand's: a comma there is only a comma. See
[Being let into one](./upkeep#being-let-into-one).

## Next

[Parameters and matrices](./matrices) — where a comma starts meaning something.
