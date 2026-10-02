# Running it

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

## The pattern

The positional pattern is a comma-separated list of `file[::name]` specs, both sides globbable.

- The **file** part matches the full stem. Files are found anywhere in the tree, with no directory
  or project distinction.
- A bare file part with no `*` must resolve to **exactly one** file, or you get an error listing the
  candidates.
- The **name** part is fnmatch: no `*` means exact.

The pattern is the only way to narrow by location — there is no `--directory`.

::: tip `--help` is a dry run
`errand --help` with a pattern shows what matched and what parameters each one takes. It is the
quickest way to find out whether your pattern means what you think.
:::

## What counts as a candidate file

Finding candidate files is a **text check, not an import**: a file is a candidate if it *imports*
`errand`.

So a source file that happens to share its entry's name — `Cell.py` next to `test_Cell.py` — is
never mistaken for one. And neither is a file that merely mentions errand in a comment, which would
otherwise be imported and executed on the strength of a word.

A directory holding a config file of its own is **another project**, and is not walked into: its
entries would run with this project's `src`, providers and environments, which is to say wrongly.

Directories you want skipped for other reasons — vendored code, fixtures, a copy of something that
would be imported and should not be — go in `configure( exclude = [ … ] )`.

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
errand -k bench                  # kind: test | bench | exp
errand -k bench -k exp           # repeatable
errand -e 'slow & !gpu'          # entry tags
errand -e '!legacy' -k bench "solvers::*"
```

`-k` names the kind, which is the preset the entry was declared with. `-e` reads the
[expression language](/reference/expressions) over the entry's own tags — and for an
[adopted suite](./providers), a `@pytest.mark.slow` or a Catch2 `[tag]` is one of those tags, so the
same expression filters them.

## Several at a time

```bash
errand -j 8           # eight entries at a time
errand -j auto        # as many as the machine has cores
errand                # one at a time: the default
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
errand --env gpu -- python -m mypkg.toolchain   # that command, in that environment
errand --env cluster -- nvidia-smi              # on the other machine, through ssh
errand --driver torch -- python -c "import torch; print( torch.__version__ )"
```

Everything after a bare `--` is a command to run *in* the environment rather than arguments to
errand. See [Being let into one](./upkeep#being-let-into-one).

## Next

[Parameters and matrices](./matrices) — where a comma starts meaning something.
