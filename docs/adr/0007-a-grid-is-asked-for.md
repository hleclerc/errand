---
status: accepted
date: 2026-11-13
---

# A grid is asked for, with its separator

ADR 0003 kept one comma grid where errand reads the value: a declared parameter ( `--n=1,2` is two
runs ), with `\,` for a literal comma. It still caused errors. A parameter often holds a comma as part
of one value: a shape `1,2`, a list of layers, two tolerances read together. Each one silently
became several runs, or failed to parse with a message about the type, not the grid.

## Decision

Several values make a matrix **only under `--grid=SEP`**, an option of errand's ( before the
target; `run`, `list`, `setup`, `shell` ). SEP splits every declared parameter's value, `--env` and
every tag; without `--grid`, a value is one value. One separator serves the whole command.

- The separator is the user's to pick, so there is **no escape**: a value holding SEP asks for
  another SEP ( `--grid=+ … --shape=1,2+3,4` ). `\,` is gone.
- A comma without `--grid` where it cannot be one value -- a number, an environment name, a tag
  value -- is an error that says how to ask for the grid.
- Environments and tags follow the same rule as parameters, though a comma cannot be in their
  values: one rule for every value errand reads is easier to hold than two.
- **Targets keep their comma**: a target word is a pattern ( `{a,b}`, `a.py,b.py` ), not a value.
- `errand setup a b` names several environments by words, with no `--grid`.
- `errand tui` writes `--grid=SEP` when anything has two values ticked ( or a comma typed in a
  field ), SEP the first of `,` `+` `|` `;` that no value holds.
- `--grid` reaches the environment with the rest of the command ( the agents' `KNOWN` ), since the
  matrix is expanded where the work runs ( ADR 0002 ).

## Consequences

`errand run --env a,b t.py::x --n=1,2` used to be four runs and is now an error ( no environment
`a,b` ). Scripts and docs that relied on it add `--grid=,`.
