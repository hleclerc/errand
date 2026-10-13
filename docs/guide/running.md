# Running it

```bash
errand run                                # everything bulk under this directory
errand run bench/solvers.py               # every entry in that file
errand run bench/solvers.py::solve        # just that one
errand run "bench/solvers.py::grad_*"     # a glob on the name; no glob means exact
errand run "**/test_*.py::{basic,quick}"  # any depth, and alternatives
errand run bench/solvers.py,tests         # several targets; a directory is all of it
errand run -k bench                       # benchmarks only
errand run -k exp "bench/solvers.py::*"   # experiments only, in that file
errand list                               # the matched entries, with their parameters
errand tui                                # one screen: tick what to run, watch it run
```

## The pattern

The positional pattern is a comma-separated list of `path[::name]` targets.

- The **path** is read from the directory you are in, extension included: what the shell completes
  and what pytest prints. A directory is everything under it.
- Both sides are **globs**, the same on both sides: `*` and `?` inside a name, `[…]` a class,
  `{a,b}` alternatives, and `**` any depth of directories on the path side. No glob means exact.
- A comma outside braces separates targets; `\,` is a comma that is only a comma.
- With no target, everything bulk **under the current directory** runs.

**What follows the target is the target's.** errand's options go before it; everything after it —
`--env` included — is handed to what runs: the `sys.argv` of an errand file, the command line of a
script, an executable, pytest or Catch2, what follows `--` for `cargo test`. Declared `Param`s are
read out of it; the rest passes through, and is part of the run's name in `runs/`, since
`--size 4096` and `--size 8192` are two runs. A comma is a [matrix](./matrices) there too, declared or
not: `--size 1,2` is two runs, `--size=1,2` as well, `\\,` is a comma and `,,` an empty value. With no target there is nothing to hand arguments to: `errand run . --n=5` is everything here.

A target that designates nothing is an **error**, not an empty run: a path with no glob must exist,
a glob must match a file that declares work, and a `::name` must match an entry of the files it is
about — with the closest thing there is, when there is one.

::: tip `errand list` is a dry run
`errand list` with a pattern shows what matched and what parameters each one takes. It is the
quickest way to find out whether your pattern means what you think.
:::

## What counts as a candidate file

Finding candidate files is a **text check, not an import**: a file is a candidate if it *imports*
`errand`.

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
errand run -k bench          # kind: test | bench | exp
errand run -k bench -k exp   # repeatable
errand run -e 'slow & !gpu'  # entry tags
errand run -e '!legacy' -k bench "bench/solvers.py::*"
```

`-k` names the kind, which is the preset the entry was declared with. `-e` reads the
[expression language](/reference/expressions) over the entry's own tags — and for an
[adopted suite](./runners), a `@pytest.mark.slow` or a Catch2 `[tag]` is one of those tags, so the
same expression filters them.

## Several at a time

```bash
errand run -j 8     # eight entries at a time
errand run -j auto  # as many as the machine has cores
errand run          # one at a time: the default
```

`-j` runs **one process per entry**, because the isolation between entries is the module reload, and
a reload only isolates within one interpreter.

A serial run stays in this process, where it is faster and its output arrives live. Each parallel
entry's output is held and printed whole, in completion order — interleaved lines from several
entries at once are unreadable and, worse, unattributable. What came of a child is read back from
its result file rather than parsed out of its chatter: the path was worked out before the child
started, and the file is the record either way.

While a run is parallel its output is still live *in the tree*: `output.txt` is written as the run
talks, so `tail -f` works on it, and so does [the screen](./tui).

## Running something in an environment, without an entry

```bash
errand shell --env gpu -- python -m mypkg.toolchain  # that command, in that environment
errand shell --env cluster -- nvidia-smi             # on the other machine, through ssh
errand shell --driver torch -- python -c "import torch; print( torch.__version__ )"
```

Everything after a bare `--` is a command to run *in* the environment rather than arguments to
errand. See [Being let into one](./upkeep#being-let-into-one).

## Next

[Parameters and matrices](./matrices) — where a comma starts meaning something.
