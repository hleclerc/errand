# Steps from processes: decisions

- **Name**: `errand.step(...)` in Python, `step …` in shell.
- **Scope**: further than a text line: the protocol opens the way to convergence curves, an HTML output that evolves, etc. (round 1, Q2).
- **errand run**: shows steps too, not only the TUI and `errand status` (round 1, Q3).
- **History**: depends on the kind of output; a dated history of steps is of interest (round 1, Q4).
- **One call** (round 2, Q1): `errand.step( text = None, *, done = None, **values )`; text = current state, `done` = fraction 0–1 (bar, estimated end), named numbers = one curve each. Every call is a dated event; the last one is the state; the text stays until another is given. Shell: `step "iteration 41" done=0.41 residual=3e-7`.
- **Files that evolve** (Q2): `errand.view( path, title = None )` designates a file of the run (HTML, PNG…), shown first in the TUI detail (`o` opens it), said once by `errand run`; the future HTML view shows it live. Shell: `view convergence.html`. A reader must never see a half-written file: `errand.view( path, content )` writes it atomically (temp + rename) for the process; a process writing the file itself is told to do the same (docs).
- **Journal** (Q3): `<leaf>/steps.jsonl`, one dated event per line, comes back with the record, stays with the run in the history. Found by `$ERRAND_STEPS`, set by `run_case` for each case; without it `step` does nothing and never raises.
- **Rate** (Q4): at most 10 writes per second; the last state is never lost (written at the next write or at exit); no size cap, no option.
- **TUI** (Q5): row shows the text or a bar; detail shows text, bar + estimated end, age of the last step, one sparkline per curve (log scale when positive over > 2 decades), designated views first; finished runs show their curves from the leaf.
- **errand run** (Q6): on a terminal, a bottom line rewritten in place under the scrolling output, erased at the end of the case; nothing off a terminal; relayed through ssh/agents with the output. `errand status` adds the text after "running".
