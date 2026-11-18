---
status: accepted
date: 2026-11-15
---

# Steps: a run says where it is, and errand shows it live

A run that takes hours says nothing to errand until it ends. Its output scrolls in `errand run`,
`errand tui` shows the end of it, and that is all: an iteration count, a residual going down, a
picture that gets better are lost among the lines, or never printed. ADR 0009 gave a process a way
to say what it waits for (`$ERRAND_PROC_DIR/waiting`). This ADR gives a run a way to say where it is.

## Decision

**One call, three kinds of content:**

```python
errand.step( f"iteration {i}", done = i / n, residual = r, energy = e )
```

- the text is the current state, as a person reads it; it stays until another one is given;
- `done` is a fraction from 0 to 1: a bar, and an estimated end;
- the named values are numbers, one **curve** each, in the order of the calls.

Everything is optional: `errand.step( residual = r )` adds a point without changing the text.
In a shell script: `step "iteration 41" done=0.41 residual=3e-7`.

**A file that evolves** (an HTML page, an image redrawn as the run goes) is not an event, it is a file
of the run. The run designates it once:

```python
errand.view( "convergence.html" )                    # the process writes it itself
errand.view( "convergence.html", content = html )    # errand writes it, atomically
```

A reader must never see a half-written file: with `content`, errand writes it to a temporary file
and renames it over the old one; a process that writes the file itself must do the same. Shell:
`view convergence.html`.

**Every call is a dated event in the run's journal**, `<leaf>/steps.jsonl`, one JSON object per line:

```json
{"t": 1763220000.12, "text": "iteration 41", "done": 0.41, "residual": 3e-07}
{"t": 1763220000.95, "residual": 2.1e-07}
{"t": 1763220001.40, "view": "convergence.html"}
```

It lives in the run's directory, so it comes back with the record, stays with the run in the
history, and goes with it. The process finds it through `$ERRAND_STEPS`, set by `run_case` for each
case. Without it (a process errand did not start) both calls do nothing, and never raise.

**At most ten writes per second.** Between two writes, the calls are merged (the last text, the last
`done`, the last value of each curve) and written at the next one, or when the process exits: the
last state is never lost, the curves are sampled at 10 Hz at most. No cap on the size (a few MB per
hour at worst).

**Where it shows:**

- `errand tui`: the process row shows the text, or a bar when there is `done`; the detail shows the
  text, the bar and the estimated end, how long ago the last step was (a run that hangs shows), one
  sparkline per curve (log scale when the values are positive and span more than two decades), and
  the designated views first among the files. A finished run of the history shows the same, read in
  its directory.
- `errand run`: on a terminal, one line at the bottom, rewritten in place under the output that
  scrolls (a scroll region keeps it there), erased when the case ends. Off a terminal, nothing: the
  journal is in the record. A session running elsewhere follows its journal and sends the line as one
  of its marks (`\x1eerrand-op {"op": "step", …}`), outside `output.txt`; the side that drives it
  draws it.
- `errand status`: the text after "running".

**`step` is during a run, `track` between runs.** `errand.track` is a kind of entry whose numbers
are followed from one run to the next; a step's curves are the inside of one run.

## Consequences

The journal is the protocol: the TUI, `errand run`, `errand status` and the future HTML view only
read it. A process writes plain JSON lines, so any language can say its steps without errand's
Python. What a TUI reads of a running process is a summary of the journal's ends (its first and last
64 KB), computed where the run is: a long journal costs nothing to watch.

## Settled with Hugo, 2026-11-15

`grill/steps/decisions.md`, two rounds.

## Done, 2026-11-15

`errand/steps.py` (`step`, `view`, the journal, its summary, `SHELL_STEPS` handed as
`$ERRAND_STEPS_SH`); `run_case` sets `$ERRAND_STEPS` and follows the journal (`cli/footer.py`: the
line at the bottom, or the session's marks, drawn by `sessions.follow`); `table` reports the step of
the case running, `errand status` and `errand tui` show it, the TUI reads a finished run's journal
and opens HTML views in the browser. Tried for real: a local `errand run` of a Python and a shell
script on a terminal. Not tried for real: the line relayed from a session on another machine.
The user guide: `docs/guide/steps.md`, with `step` and `view` in the Python API reference.

## Amended, 2026-11-18: a view is said where it opens

A tool that writes a page says `OUTPUT: file://...` for a ctrl+click; on a machine that does not
share its disk, that path leads nowhere. `view` now says it on the machine that drives the run: the
session turns each `view` of the journal into a mark, by its path from the copy's root
(`footer.view`); the driving side (`cli/views.py`, `Views`) brings that one file back at once
(`layers.fetch_file`, or the guest's `pull_file`), its date kept so the run's coming back leaves it,
and says its local path, once per file. A run nobody follows (no `$ERRAND_RELAY`) says its own path.
`view` returns whether errand says it, so a library keeps its own line outside errand. Tried for
real: a session on this machine, and a run on lmo over ssh, by sync and by rsync, whose page arrived
before its end (`tests/test_views.py`). Not tried: a Windows guest.
