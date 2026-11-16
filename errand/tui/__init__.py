"""`errand tui`: what runs where, for whom, since when -- and what waits.

    ╭─ machines ─────────────────────────────────────╮╭─ detail ─────────────────────────╮
    │ ▾ hugos-mbp  ( this machine )   idle · read 1 s ││ machine   lmo                    │
    │ ▾ lmo           2 running · 1 waiting · read 2 s ││ project   /home/hugo/sdot-ffi     │
    │     sdot-ffi   test_solve.py::solve   12 min ru… ││ state     running                │
    │     otrec      grid2d.py    4 h  waiting: slurm… ││ files                            │
    │   ▸ history ( 37 )                               ││   output.txt    12.1 kB  3 s     │
    ╰──────────────────────────────────────────────────╯╰──────────────────────────────────╯

This machine, and every machine of the ledger ( ADR 0008 ), each asked by its own thread through its
agent ( `agents.look`: `table`, `seen`, `ls`, `tail`, `kill` ). Under a machine: what runs there,
whoever started it and from wherever, its VMs with what runs in their guests, and its history --
links to the directories of the runs done there, as long as those directories are there. On the
right, the row under the cursor: what it is, the files of its run, the end of its output.

Drawn with the curses of the standard library, so errand still installs with nothing at all.
`rows` builds the list ( no terminal, tested without one ), `screen` holds the state and the
actions, `loop` draws and reads keys, `machines` asks.
"""
from __future__ import annotations

from .panes import Pane, Row
from .screen import Screen


def __getattr__( name ):
    # The parts that need `curses`, only when asked: the list, the detail and the machines are read
    # without a terminal too ( `errand web`, on an interpreter without curses ).
    if name == "OWN_MOUSE":
        from .terminal import OWN_MOUSE
        return OWN_MOUSE
    if name == "main":
        from .loop import main
        return main
    raise AttributeError( name )


__all__ = [ 'OWN_MOUSE', 'main', 'Screen', 'Pane', 'Row' ]
