# Where a run is: steps

```python
import errand

for i in range( n ):
    r = solver.iterate()
    errand.step( f"iteration {i}", done = i / n, residual = r )
```

```text
$ errand run --env cluster python solve.py
…the output scrolls here…
iteration 41 · ▕████▏      ▏ 41 % · 2 min left · residual 3e-07 ↘
```

A run that takes hours says nothing until it ends: an iteration count, a residual going down, a
picture getting better are lost among the lines, or never printed. **`errand.step`** lets the run
say where it is, and errand shows it live: at the bottom of `errand run`, in `errand status`, in
`errand tui`. Every call is also written down, dated, beside the run's [record](./output).

## step

```python
errand.step( text = None, *, done = None, **values )
```

One call, three kinds of content, all optional:

| | | shown as |
|---|---|---|
| `text` | the current state, as a person reads it. It stays until another one is given | the text |
| `done` | a fraction from 0 to 1 | a bar, and an estimated end |
| `name = number` | named numbers, one **curve** each | the last value and its trend; a sparkline in the TUI |

```python
errand.step( "assembling" )                       # just the text
errand.step( residual = r, energy = e )           # two points, the text unchanged
errand.step( f"epoch {k}", done = k / epochs, loss = loss.item() )
```

Values are numbers: something `float()` cannot convert raises, as a typo would.

**Call it as often as you like.** errand writes at most ten times per second; the calls in between
are merged ( the last text, the last `done`, the last value of each curve ) and written at the next
write, at the end of the case, or when the process exits. The last state is never lost; the curves
are sampled at 10 Hz at most.

**Outside errand, it does nothing.** A script run by hand, or a process errand did not start, calls
`step` for free: nothing is written, nothing raised.

## view: a file that evolves

An HTML page, an image redrawn as the run goes: that is not a step, it is a file of the run worth
watching. Name it once:

```python
errand.view( "convergence.html" )                   # the process writes it itself
errand.view( "convergence.html", content = html )   # errand writes it
errand.view( "mesh.png", title = "current mesh" )
```

A relative path is in the run's directory, beside `output.txt`, so it comes back with the record,
from wherever the run is. Call `view` again with new `content` each time the file changes.

### Where it opens

errand says it, once per file, as a link a terminal opens with a click:

```text
OUTPUT: file:///Users/me/proj/errand-outputs/runs/solve/2026-11-18_10h02m11-lin@lmo/convergence.html
```

That path is on **the machine that drives the run**, not the one that runs it. A run on another machine
names the file; errand brings that one file back **at once**, to where the run's own coming back
would put it, and says its path here. Named again while it is on its way, it comes once more after:
the last state always arrives, never one transfer per call. Its date is kept, so at the run's end the
file is not sent again unless it changed. A file rewritten while it is read is read again: still, a
process that rewrites a view in place, rather than replacing it ( above ), can have half of it shown
here until the next state arrives.

A run nobody drives ( `--batch` ) says the path where it is. A file outside the project over there
cannot be brought back: it is said as `host:path`.

`view` returns whether errand says it: False outside errand, so a library can keep its own line for a
script run by hand:

```python
try:
    import errand
    said = errand.view( path )
except ImportError:
    said = False
if not said:
    print( f"OUTPUT: { path.absolute().as_uri() }" )
```

::: warning Replace it, never rewrite it in place
A reader must never see half a file. With `content`, errand writes a temporary file and renames it
over the old one. A process that writes the file itself must do the same:

```python
tmp = out / ".convergence.html.tmp"
tmp.write_text( html )
tmp.replace( out / "convergence.html" )
```
:::

## In a shell script

```bash
eval "$ERRAND_STEPS_SH"

for i in $( seq 1 100 ); do
    ./iterate
    step "iteration $i" done=$( awk "BEGIN { print $i / 100 }" ) residual=$( cat residual.txt )
done
view convergence.html
```

`$ERRAND_STEPS_SH` holds the functions `step` and `view` ( which says where the file opens, as above ), in POSIX sh, and `download URL`, which prints
the path of a file fetched as [`errand.download`](/reference/python-api#download) does, and `require`,
which grows the run's claim as [`errand.require`](/guide/machine#the-run-asks-from-its-code) does. The first argument of
`step` is the text unless it reads `name=value`; the values are written as given, so they must be
numbers. There is no merging: each call is a line.

## Where it shows

**`errand run`**: on a terminal, one line at the bottom, rewritten in place while the output scrolls
above it, and erased when the case ends. Off a terminal ( a pipe, a CI log ) nothing is drawn: the
journal is in the record. A run on another machine sends its line back with the rest, and it is
drawn here; it never gets into `output.txt`.

**`errand status`**: the same line, after `running`:

```text
    lmo   3f2a9c1e  run solve.py  --env lin  12 min  running · iteration 41 · ▕████▏      ▏ 41 % · 2 min left · residual 3e-07 ↘
```

**`errand tui`**: the process row shows the text and a bar. Its detail shows:

- the text, the bar and the estimated end;
- how long ago the last step was: a run that hangs shows;
- one sparkline per curve, on a log scale when the values are positive and span more than two
  decades ( a residual );
- the views, first among the run's files. Enter opens one; an `.html` or `.svg` view opens in the
  browser.

A finished run of the history shows the same, read in its directory.

## The journal

Every call is a dated line of **`steps.jsonl`**, in the run's directory:

```json
{"t": 1763220000.12, "text": "iteration 41", "done": 0.41, "residual": 3e-07}
{"t": 1763220000.95, "residual": 2.1e-07}
{"t": 1763220001.40, "view": "convergence.html"}
```

```text
2026-11-15_14h02m11-lin@lmo/
  result.yaml
  output.txt
  steps.jsonl      every step, dated
  convergence.html a view
```

It is the whole protocol. A process finds the file through **`$ERRAND_STEPS`**, set for each case,
so a program in any language can say its steps by appending JSON lines to it, one per write. The
keys `t`, `text`, `done`, `view` and `title` have the meaning above; every other key with a number
is a curve.

It is plain JSON lines: load it with `pandas.read_json( path, lines = True )` to plot the whole
history of a run. Watching a long journal costs nothing: the screens read only its first and last
64 KB.

## step and track

`step` is **inside one run**: where it is now, and its curves as it goes. [`track`](./declaring-work#test-bench-track-experiment)
is **between runs**: a number followed from one run to the next. A solver can do both: steps while
it iterates, and its final residual as a tracked result.

## Next

[Results and records](./output) · [What is running](./status) · [The screen](./tui)
