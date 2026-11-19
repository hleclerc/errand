---
status: accepted
date: 2026-11-18
---

# The terminal is drawn by the side that drives: blocks, a gutter, and lines that do not stay

What `errand run` prints is hard to read quickly. On a run on lmo with two cases, one passing and one
failing (2026-11-18), it showed:

- **errand's words and the program's in one stream.** errand writes `PASS`, its headers, its
  transfers to the session's stdout, beside what the case prints. The side that drives cannot tell
  them apart: it can neither color nor indent "the case's output", since it does not know where it
  starts. Over there stdout is not a terminal, so `PASS` and `FAIL` lose their colors; only the final
  summary, drawn here, has them.
- **Lines whose history is worth nothing.** `sync push`, `126 sent`, then three `sync pull`: five
  lines out of thirty, useless a second after they were printed.
- **No boundary between cases.** A case gets a header only when it has parameters: the output of
  `broken` followed the `OUTPUT:` of `solve` with nothing in between.
- **stdout and stderr indistinguishable**, though the transport keeps them apart end to end (the
  agents' `OUT` and `ERR` frames).
- **Tracebacks four fifths errand's**: `here.py`, `discovery.py`, two `importlib` frames, then the
  user's line.

Under `-j` (measured the same day):

- **The blocks leak.** Only Python's `sys.stdout` is put in a block (`agents/ops.py`, `sys.stdout =
  buf`). Python's stderr and everything written to descriptors 1 and 2 (a child process, a C
  library) go out live, interleaved between the cases, with nothing to say which one wrote them.
- **The screen is not shared.** One status line for every case, the last one that spoke; a case's
  block appears only at its end.
- **`output.txt` is incomplete.** It is written as the case goes, over there, from Python's streams
  only: what a child writes is only in `stdout.txt` / `stderr.txt` (`_keeper.py`). None of the three
  files holds everything.

And a program that asks for input (`input()`) gets EOF at once: a session's stdin is closed.

## Decision

### What stays in the history

**A line stays if someone may need it afterwards: to understand a result, to find a file, to act.
A line that only says that errand is at work is transient.** Five kinds:

| kind | examples | drawn as |
|---|---|---|
| transient | the step under way, a push or pull under way, a wait for the queue or an allocation | the status lines at the bottom, rewritten in place, erased when done |
| infrastructure | a push, a pull, a carry, once finished | transient too, always. Its numbers ( files, bytes, seconds ) go to the run's journal ( below ) |
| structure | a case starts; a case ends with its status, its duration, its key results | kept, in color |
| the case's own | its stdout, its stderr, its views ( `OUTPUT:`, ADR 0010 ) | kept, indented under its case |
| errand's problems | warnings, errors, a conflict, a run left over there | kept, yellow or red |

The numbers of a transfer are written to **`steps.jsonl`** of each run concerned, as dated events
(`{"t": …, "transfer": "push", "files": 126, "bytes": 1.1e6, "s": 0.8}`): the push before the case,
the pull appended here when the run arrives. `output.txt` is the case's own output, written over
there, and finished before the pull that brings it: it is no place for errand's numbers.

### One renderer, on the side that drives

errand's own words become **events**, on the channel the session already uses for its marks
(`op: step`, `want`, `view`): a case starts, a case ends, a transfer, a warning, the summary. The
`OUT` and `ERR` frames carry nothing but the program's bytes.

The side that drives draws everything: colors, gutter, status lines, blocks. It knows whether ITS
terminal is one, which is the only terminal that matters. A run here, with no session, goes through
the same renderer.

**Attribution by session.** A session runs one case at a time, so every byte that arrives on its
`OUT` or `ERR` belongs to the case it last said it started, whoever wrote it: Python, a C library, a
child process. Nothing is swapped in the process to find out (`sys.stdout = buf` goes).

### Layout

- **Every case has a header**, parameters or not: `▸ solve  exp_demo.py:5 · n=3`.
- **The case's output is indented behind a gutter**: `│` dim for stdout, `┃` amber for stderr. The
  gutter is colored, not the text: many programs write ordinary lines to stderr ( tqdm, `logging` ),
  and the program's own colors are kept.
- **Its end** says the status, the duration and the key results on one line:
  `PASS solve  2.1 s · residual 1e-3`; a failure adds where its whole output is ( `output.txt` ).
- **A compact banner**: `errand run · lmo · ssh → vars · 2 entries`, not the `==========` line with
  the full host name.
- **Tracebacks** lose errand's frames and the import machinery's ( amended at step 6: in `output.txt`
  too, one stream feeding both; whole with `-v` ).

The gutter has three modes: **`bar`** ( `│ ┃`, the default ), `spaces` ( a rectangular column,
easy to drop with a block selection ), `off`. Chosen by `errand.configure( output = "spaces" )`,
`$ERRAND_OUTPUT`, or `--plain` ( `off`, no colors ) on the command line. Copying stays easy whatever
the mode: the record holds the raw output, and a failure says where.

Off a terminal ( a pipe, a CI log ): no colors, no status lines, the gutter kept, since it helps
in a log too.

### Colors, by role

Bold cyan for structure ( a case's header ); green, red, yellow for `PASS`, `FAIL`, `SKIP`; dim for
everything errand does to get there; underlined for links; the gutters as above. Nothing else.

A program over there does not color its output, since its stdout is not a terminal. When the
terminal that drives is one, errand sets `FORCE_COLOR=1` and `CLICOLOR_FORCE=1` for the run, unless
the environment already says otherwise ( `NO_COLOR`, or its own value ).

### Several cases at once ( `-j` )

- **A block per case, complete**: everything the case wrote, both streams, with its gutter, drawn
  in the history when it ends.
- **The bottom is shared**: one status line per case running, at most a third of the terminal's
  height, then `+k more`. No longer the last one that spoke.
- **Focus, like tabs**: `1` … `9`, or Tab, puts one case in front: its output scrolls live in the
  bottom area, above its status line. Esc goes back to blocks. Its block is still drawn whole at its
  end.

### `output.txt` holds everything

Where descriptors can be redirected ( POSIX ), the keeper ( `_keeper.py` ), which already receives
descriptors 1 and 2, also writes `output.txt`: both streams merged in the order they arrived,
beside `stdout.txt` and `stderr.txt` apart. Elsewhere, as today, what Python writes.

### Input

A case reads the keyboard when the terminal that drives is one: with `-j 1`, the case running; with
`-j N`, the case in front ( Focus ). The bytes go through the agents' `IN` frame, which `errand shell`
already uses. Otherwise, and always off a terminal or under `--batch`, EOF, as today: nothing waits
for an answer that cannot come.

A case that wrote a line without its end, then nothing for a few seconds, is said to wait on its
status line ( `waits for input?` ). A hint, never a decision: errand cannot know.

## Consequences

The terminal shows what happened, organized by case; the record holds what happened, whole. The two
no longer compete: the screen can be compact because the files are complete.

The session's stdout stops being a text stream that a person could read as it is: what errand says
is events, and a session followed by an older errand reads them as such. Both ends are errand of the
same version ( the sources travel with the run ), so no compatibility is kept.

Tests that read `errand run`'s output as text ( `run_errand` in `tests/_infra.py` ) read what the
renderer draws off a terminal: the gutter appears in it. They match on the case's own lines, or
use `--plain`.

`errand tui` could later draw a process's output with the same renderer.

## Steps

Each step is usable on its own, in this order:

1. **Events and renderer, serial.** errand's own lines become events; the renderer draws headers,
   gutter, ends, banner, colors; `--plain`, `$ERRAND_OUTPUT`, `configure( output = … )`.
2. **Attribution by session.** Complete `-j` blocks; `sys.stdout = buf` removed; the keeper writes
   `output.txt`.
3. **Transient infrastructure.** Transfers on the status lines only; their numbers in `steps.jsonl`.
4. **The shared bottom and Focus.**
5. **Input** to the case running or in front.
6. **Forced colors** for programs over there, **trimmed tracebacks**.

## Open

Settled as the steps were done ( 2026-11-18 ):

- the thresholds: two seconds of silence after a line left open for `waits for input?`; a third of the
  terminal's height for the cases' lines, then `+k more`;
- `FORCE_COLOR` and `CLICOLOR_FORCE` are set by default, when the terminal that drives shows colors,
  never against `NO_COLOR` or a value already chosen;
- the block of the case in front is drawn whole at its end too: the history does not depend on what
  was looked at.

## Step 1 done, 2026-11-18

`errand/cli/render.py` ( `Renderer`: banner, header, gutter, end line, notes, asides ); a session says
`banner`, `head`, `note` and `ran` ( with its `tail`: seconds, short results, where the output is ) as
events, drawn by `sessions.Marked` in the order of the stream; a case in this process is drawn by the
same renderer. The gutter is put where bytes leave for the terminal, never before the files: by the
keeper on what it passes on ( `_keeper.py`, two optional arguments ), or by `streams._Copy` when the
descriptors stay a terminal. So a child process's output gets it too when the keeper runs, and not yet
on a terminal here ( step 2 ). `--plain`, `$ERRAND_OUTPUT`, `configure( output = … )`. A view brought
back after its case ended comes as an aside, under the next header. The final summary is unchanged.
Tried for real: a run here and one on lmo, on a terminal. The suite: as before, its 7 failures of
test_tui, test_web, test_windows seen in every full run since 2026-11-16, passing alone.

## Step 2 done, 2026-11-18

`sys.stdout = buf` is gone from the session: under `-j` the renderer of each session holds what the
session writes between a case's header and its end ( `Renderer.blocks`, set by `drive._in_blocks` ),
and draws it at once. A child of a local `-j` draws its own block, in colors when the terminal it is
shown on is one ( `ERRAND_COLOR` ). The keeper writes `output.txt`: both streams as they came, a
session's marks taken out of the files; one `select` loop reads both streams, and with a gutter it
ends a line the other stream left open. On a terminal here, the keeper takes descriptors 1 and 2
through two pseudo-terminals ( `streams._terminal_pair`: no byte changed, the gutter's width taken
off ): the run sees a terminal, and a child's output gets the gutter. `style.Tee.isatty` answers as
the terminal. Tried for real: a run here on a terminal ( Python, a child, colors, `\r` ), `-j 2` here
and on lmo. `tests/test_render.py`. The suite's 7 failures came from `test_status.py`, which replaced
four functions ( errand's cache among them ) and never put them back: fixed.

## Step 3 done, 2026-11-18

`errand/cli/bottom.py`: the line at the bottom made of named parts ( `env`, `step`, `work` ), drawn
under the renderer's lock, nothing off a terminal; `working( text, kind )` shows a piece of errand's
work with the time it takes and hands back its record. The push ( and `also`'s ), errand's sources
sent, a carried build, each pull, and the environment driven ( `-> box  ssh:…` ) are on it only; the
`N sent ( … MB )` line and `prepared N entries in …` are gone. What deserves to stay ( a file moved
aside, a conflict, a run kept over there ) is still said. A push's numbers travel with the request
( `known.transfers` ) and open each case's journal; a pull's are appended to the journal of each run
it brought back ( the `leaf` of each `ran` ); `steps.summarize` leaves `transfer` events out. Tried for
real on lmo, on a terminal; `tests/test_render.py` ( one test over ssh ).

## Step 4 done, 2026-11-18

A case's end line closes its gutter ( `  ╰ PASS …` ), in the column of its output, at Hugo's asking:
the eye runs down one column for the ends, the headers alone at the left edge. `Footer.show_lines`
keeps any number of lines below the scroll region. `bottom`: errand's line ( `env`, `work` ), a line per
running case ( `case_start` on a session's `start`, `case_step` on its `step`, `case_end` on `ran`;
a local `-j` child's step polled from its journal ), compact on one line with one case, at most a third
of the terminal then `+k more`; Focus on `1`…`9` / Tab, Esc back ( `bottom.keys`, cbreak, read only when
stdin and stdout are terminals ), the case in front's last lines above the lines ( `Renderer.recent`, or
the child's output read as it comes ). A local `-j` child's stdin is `/dev/null`. Settled: the block of
the case in front is still drawn whole at its end. Tried for real: local `-j 2` and `-j 2` on lmo, on a
terminal, checked through an emulation of the screen; `tests/test_render.py`.

## Step 5 done, 2026-11-18

A session started for a terminal keeps its input open ( `agents.start( keep_input = True )`, a
`LocalSession`'s stdin a pipe ): `Session.write` sends `IN` frames on its attach channel, which the
agent delivers. One session: `bottom.feeding` reads the keyboard as it is ( canonical: the terminal
echoes and edits ), each line to the case; Ctrl-D closes its input. Several: `bottom.key` edits the line
of the case in front at the bottom, Enter sends it, and it goes in the case's block ( `Renderer.typed` );
Ctrl-D, Esc. A case's number is its own while it runs ( the lowest free ), not its place in the lines.
A local `-j` child's stdin is a pipe when the keyboard is a terminal. `⌨ waits for input?` on a case's
line after a line left open and two seconds of silence ( `Renderer.waiting` ). A run here reads the
input errand was given, as before; a session not started for a terminal gets EOF at once.
`tests/_tty.Term( controlling = True )`: the terminal the program's own, as a real one is -- without
it, nothing reads a line. Tried for real: one case here and on lmo, two under `-j 2` here and on lmo,
answered through Focus. Left: after an answer typed to a case run in this process, the next line of
its output lacks its gutter ( the terminal's echo ended the line, the keeper cannot know ).

## Step 6 done, 2026-11-18

`render.forced_colors()` in the environment of the cases that `drive` starts and of a local `-j`'s
children, not under `--batch`. `cli/tracebacks.py`: a case's traceback ( `here.run_case`, `mpi` ) without
errand's frames nor the import machinery's, a library's kept, chained exceptions and groups trimmed
alike, Python's colors when it gives them; none left out when there is no other frame than errand's.
Unlike the decision above, the traceback is the same on the terminal and in `output.txt`: one stream
feeds both. The whole one is `-v`'s. An empty line of a case's output keeps its gutter ( `│` alone ).
Tried for real: a chained failure here, the colors on lmo on a terminal, off one, and with `NO_COLOR`.

## Revised 2026-11-18: where it goes, said in context

The banner ( `lmo-torch · 1 entry  lmo-torch@host` ) said the environment twice and nothing of the way
there; what the sync said came before it, out of context; errand's transient line at the bottom read as
foreign. Now:

    ▸ lmo → micromamba prj-torch → vars                          ↑ 20 files · 113.1 MB · 9.8 s
      ┆ sdot-ffi/src/sdot/precompiled-kernels/cpu-x86-64: kept there, it holds *.so ( build zone )
      ┆ 30 run directories made there, kept, not in the project here ( … )
      ▸ pencil (lmo-torch)  exp_2d_real.py:79 · n=5000 · bins=512
        │ …
        │ ↗ file:///…/pencil.html
        ┆ 41 s · iteration 41                    ( while it runs and says nothing; erased by its next line )
        ╰ PASS pencil  1 min 30 s
      ↓ 8 files · 8.4 kB · 0.2 s

- **The place line** ( `cli/place.py` ): the layers of the environment in their order, the machine
  first. While errand gets there, what it does is drawn on its right, live, with its time ( `bottom.working`
  draws there while a place line is open ), then the numbers it came to. Every message of the sync goes
  under it, behind `┆`, whole. The bottom keeps only the cases.
- **The environment** goes after each case's name, `(lmo-torch)`; the banner says nothing more than the
  count, when there are several. A run here has no place line: its banner is `▸ host`.
- **The coming back** has a line of its own under the last case, `↓ …`, drawn the same way.
- **A view** ( `errand.view` ) is drawn inside its case, behind its gutter, `↗ link`; the end of the case
  waits for the views on their way ( `Views.settle` ), so the link is never after the `╰`. `OUTPUT: link`
  when the output is plain ( `--plain`, `ERRAND_OUTPUT=plain|off` ), as a run nobody drives says it.
- **Cases under their place**: two spaces further in, their header in the cases' colour, the place line
  in its own ( magenta ).
- **How long it has run** is said under the case's last line, `┆ 41 s · its step`, while it is quiet on
  a terminal, and erased by whatever it writes next ( `Renderer.status` ); the bottom says nothing of a
  case running alone. Under `-j` the bottom keeps a line per case, and Focus.
