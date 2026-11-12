"""`errand tui`: a screen for choosing what to run, and watching it happen.

Drawn with the curses of the standard library, so errand still installs with
nothing at all. Everything that is not drawing is in `session.py`, which has no
screen in it and is tested without a terminal.

**There is no focus to manage.** One pane is active, the arrows drive it, and
clicking a pane selects it. The wheel scrolls whatever is under the pointer and
changes nothing else -- which is what a wheel is for.

**One function key per rectangle, written in its own title**: F1 cases, F2
about, F3 runs, F4 files, F5 preview. One press from anywhere, and the page
follows -- a key written where it takes you has to be neither remembered nor
cycled through.

    ╭─ F1 cases ───────────────╮╭─ F4 files ───────────────────╮
    │ ▾ bench_solver.py        ││   shape.svg         12.1 kB  │
    │   [x] solve              ││   result.yaml          512 B │
    │   [ ] gradient           ││   output.txt         1.2 kB  │
    ╰──────────────────────────╯╰──────────────────────────────╯
    ╭─ F3 runs ────────────────╮╭─ F5 output.txt ──────────────╮
    │ ▾ errand bench_solver    ││ iteration 41  residual 3e-07 │
    │   ok   solve  n=1000     ││ iteration 42  residual 2e-07 │
    │   ..   solve  n=5000     ││                              │
    ╰──────────────────────────╯╰──────────────────────────────╯

**Runs and history are one list**, because they are one thing: a command, and
what it produced. Today's is at the top and still moving, yesterday's is three
rows down, and both read the same way -- since both are read out of the output
tree rather than remembered.

**Enter on a case asks the only question left** -- where, with which tags, with
which parameters. Not *which case*: that was the list enter was pressed in.

One file per part: the terminal ( `terminal` ), the tree of files and cases ( `tree` ), rows and panes
( `panes` ), drawing ( `drawing` ), the dialog ( `dialog` ), the screen and its mixins ( `screen`,
`lists`, `actions` ), and the loop that reads keys ( `loop` ).
"""
from __future__ import annotations

from .terminal import OWN_MOUSE
from .loop import main
from .screen import Screen
from .panes import Pane, Row
from .dialog import Dialog


__all__ = [
    'OWN_MOUSE',
    'main',
    'Screen',
    'Pane',
    'Row',
    'Dialog',
]
