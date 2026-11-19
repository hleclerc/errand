---
status: accepted
date: 2026-11-19
---

# The runs listed are this machine's record

ADR 0023 built the runs' tree from each machine's history ( its agent's `seen` links, the latest 1000 ), merged. On this
Mac the history held 24,995 links: the counts were wrong, older runs came up into the list as others were removed, and
a removal had to look for runs on every machine. Yet every run started from here has its directory here, wherever it
ran: `~/Projects/errand-outputs/runs/` held 62,989 runs, 9,969 of them run on lmo, each with its `result.yaml`
( name, file, env, place, host, status, duration, params, results ).

Settled in a grill with Hugo on 2026-11-19 (`grill/runs-local/decisions.md`). Replaces "Where it comes from" and the
part of "Removing" that asks every machine, in ADR 0023.

## Decision

- **The list is this machine's record**: the run directories under the `runs/` of every project root seen here ( the
  roots `seen` kept ), all of them. A run's machine is its `result.yaml`'s ( `host`, `place` ), named as the ledger
  names it. What runs or waits still comes from the agents' tables, placed in the tree by its path under `runs/`.
- **Projects as sub-lists**: `~/A/B` and `~/A/C` give `~/A`, then one sub-list for `B`, one for `C`; a root inside
  another is a sub-list of its own, not merged with the outer one's directories.
- **The tree is the path under `runs/`**: directories ( merged when they have one child ), the file, the entry, the
  parameter sets, the runs, cut where `result.yaml`'s `file` says; a run without one ( killed, lost ): by its path,
  "lost". Counts are exact.
- **An index** ( `~/.cache/errand/runs-index.json` ): one compact record per run with its `result.yaml`'s date; read at
  start, a directory whose date did not change not read again; updated when the bell rings ( a run ends, is brought
  back ) and by a sweep every 60 s ( a walk of the directories' dates: 0.25 s for 63,000 ). Kept by this machine's host
  agent, which serves the page; the TUI keeps the same, from the same file.
- **Removing** a run: its directory here, and, when it ran elsewhere, its directory there through that machine's agent,
  found by its path under `runs/` among the runs that agent noted, nothing else. What is listed is what goes; the window
  knows at once how many. A machine that cannot be reached: here goes, there stays, and the check finds it.
- **The check** ( a separate action ): every machine says the runs it noted, compared with the record here. Those there
  only ( removed here but not there, or started from elsewhere ) are listed at their place, marked "on lmo only", to
  bring back or remove. Here but not there: nothing to say.
- **errand's own test runs** are runs like the others.

## Considered options

- **The agents' histories** ( ADR 0023 ): limited, merged, and a removal that must look everywhere.
- **Reading every `result.yaml` at each start** ( ~30 s with the general YAML reader ): the index keeps them.
- **Merging nested roots**: one list mixing two projects' outputs.

## Consequences

- The runs tab lists everything started here, with exact counts; nothing comes up when something is removed.
- A run started directly on another machine shows only through the check.
- The host agent holds the index in memory ( 55 MB measured for 70,000 runs; the TUI as much ).

## Steps

1. The index ( `agents/registry.py` ) and the tree from it, with what runs.
2. Removing here and there.
3. The check: there only, brought back or removed.
4. The TUI.

## Done, 2026-11-19

- `agents/registry.py`: the roots ( `note_root` at each `errand run` from a project, `seen`'s, and their neighbours that
  hold `errand-outputs/`; scratch directories left out ), the index ( `runs-index.json`, `Run` records with `__slots__`,
  a directory listed again only when its date changed, a run with its `result.yaml` read is final ). Measured here:
  70,176 runs, 55 MB in memory, the first reading 28 s ( once ), then 0.2 s to load and 33 ms to look again.
- `tui/rows.py`: `record_runs` ( the record, the machine from `host`: this one whatever number the network gave its
  name, the ledger's, else a name only, `Elsewhere` ), kept for the same record and filter, the tree built once for
  it ( `tree_of` ); a row looked up by its key opens only what is above it ( `reach`, `runtree.path_to` ): 70,000 runs
  are never unfolded. The check ( `check`, `CHECKED`, `bring_back` through `fetch_view` ).
- `tui/runtree.py`: the projects as sub-lists ( `_projects`, from every root: ids stay the same whatever the filter ),
  exact counts ( `Node.count` ), a file outside its project shown where it is ( `~/.cache/tl24-n2/u6b.sh` ).
- `tui/removal.py`: here, and there by `rels` ( `look._by_rel` ); the window says how many at once.
- The page and the TUI: `check` ( `c` ), `bring back` ( `b` ) on a run marked ◇; a run's detail read here, its
  machine said as where it ran.
- Tests: `test_runs_tree.py` ( the record, removing here and there, the check ); the tests that describe runs through
  histories give them to the record ( `tests/_record.py` ).

Seen on this Mac: `~/Projects/` 70,363 runs, `./` 58,738, `errand/` 11,042, `otrec/` 283…; a foam run of lmo opened
from its copy here, its sviz shown; the check: "Lmo: all here, node14: all here". Not done: a command run whole
( `python`, `sh` ) whose file is not a path is filed under its name ( errand records no directory for it ); runs whose
host errand does not know ( cluster nodes, this Mac under a network's name ) are removed here only, said in the window.

## The tree from the files' own paths ( 2026-11-19, Hugo )

The roots as sub-lists under their common directory ( `~/Projects/`, then `./`, `otrec/`, … ) gave a level that always
held everything, and a `./` that split one project's files in two: `~/Projects` running `otrec/x.py` and
`~/Projects/otrec` running `x.py` are the same file. Now a run's path is its root's path from the roots' common
directory, then its path under `runs/`: the common directory is no row, `otrec/` holds the runs of both roots ( 1,778
here ). At each level the folders come first, then the files and the commands, each by their latest run.
