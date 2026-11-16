# errand tui: decisions

- **Main screen**: one list grouped by machine (agent state, VMs, processes, guests under their VM) + detail pane on the right (meta, waiting, live output tail) + the files of the run, readable before it ends.
- **Projects**: all projects in full, current one highlighted; `p` restricts to the current project.
- **Actions**: stop (`s` + confirm; cancel line then INT/TERM/KILL), full output in `$PAGER` (`o`), shell `ssh -t` in the cwd (`x`), stop a VM. No agent stop.
- **Old TUI**: dropped, with `session.py`, `test_session.py`.
- **Library**: stdlib curses; keep terminal.py / drawing.py / panes.py.
- **Keys**: letters are verbs, `/` filters, ↑↓ ←→ tab ? q r p s o x.
- **Queue**: the ADR 0009 `waiting` records are enough.
- **Transport**: through the agents, via the hub: new agent ops `table` ( `table.scan()` ), `kill` ( id or pgid: cancel line, INT/TERM/KILL ), `tail` ( file from offset ), `ls` ( a leaf ), `seen` ( history ). Opening the TUI starts the agents of the ledger's machines; no ssh fallback ( `remote_table` stays for `errand status` ).
- **Run files**: `run_case` writes `$ERRAND_PROC_DIR/leaf`; detail pane lists the leaf's files ( newest first ) and tails `output.txt` ( or the process output ); enter / `o` opens a file in `$PAGER`.
- **History**: one link per run, `~/.cache/errand/seen/<id>.json` = { leaf, project, what, env, started }, written by `run_case` where it runs; status/duration/output read from the leaf when shown; the agent drops links whose leaf is gone. A folded `history` node per machine, newest first, 50 then more.
- **Steps from processes**: not now; separate session ( small ADR then code ). The TUI leaves room for a `step` column.
- **HTML view**: separate session: the same as `errand tui`, as HTML for humans, served by the agents.
