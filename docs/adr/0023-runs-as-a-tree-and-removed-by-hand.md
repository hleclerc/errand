---
status: proposed
date: 2026-11-19
---

# The runs as a tree, their parameters as a table, removed by hand

The runs tab of `errand tui` and `errand web` lists what runs, what waits, then every run done, by day,
all machines mixed. After a few days it is a very long list: a single parameter set of the foam
experiment had 34 runs. One cannot see which cases exist, compare their parameters, nor get rid of the
runs one no longer wants.

Settled in a grill with Hugo on 2026-11-19 (`grill/runs-tree/decisions.md`).

## Decision

### The tree

    running / waiting                              ( as today: a short list on top )
    otrec/
      experiments/exp_2d_real.py                   a directory with one child is merged with it
        foam                                       an entry ( test, experiment )
            row  n      nb_splits reduction | loss   status  when     runs   ← a table, its header sorts
            500  10000  1         1         | 0.005  PASS    12:13    34
            500  2000   1         8         | 0.002  PASS    12:14    1
              ▸ a set unfolded: its runs ( date, machine, env, status, duration )
    sdot-ffi/
      …

- The levels: the directories of the file's path from the project's root (the projects one thinks of:
  `otrec/`, `sdot-ffi/`, `errand/`), the file, the entry, its **parameter sets**, their runs.
- A parameter set: the runs whose parameters are equal; the environment and the machine are not part of
  it, they are columns of the runs (and of "the last one" of a set). An entry without parameters lists
  its runs.
- The table: one line per set, a column per parameter, then the results the run declared
  (`p.results[ … ]`, `result.yaml`), the status, date and duration of its last run, how many runs. Its
  columns are aligned as text (the list is monospaced in both views); a click on a column of the header
  sorts by it (again: the other way), `s` in the TUI goes from a column to the next.
- Order: the latest activity first, at every level. At the start, folded at the top directories, but
  what runs or waits, unfolded down to its run. What is folded or unfolded by hand is kept.
- A run brought back by `-o` is one run: the history of a machine lists the runs started there, never
  the copies brought to it.

### Where it comes from

Each machine's agent says its history (`seen`, the links `~/.cache/errand/seen/*.json`): the leaf, the
project, `what`, the env, the start, and from `result.yaml` the status, the duration, the file, the entry's
name, its `params` and `results`. An older agent does not say the last three: the file's path is then
read from the leaf (`errand-outputs/runs/<file>/<entry>/<run>`), the parameters from `what`. The limit
of a history goes from 200 to 2000 runs.

### Removing

At every level (directory, file, entry, set, run):

- **keep only the latest** (`D` in the TUI): for each parameter set and environment below, the most
  recent run stays, and the most recent PASS when it is another; the others go;
- **remove** (`d`): every run below.

What goes: the run's directory on its machine, through its agent (`runs_remove`), and its copy here
when there is one (the leaf from `errand-outputs/` on, under a project of this machine). **For good, at
once.** Nothing outside a run's directory: the agent removes only a leaf its `seen` noted, and never one
whose run runs or waits. The confirmation is the red box of `kill` and the caches: how many runs, on
which machines, the room freed, "for good". A machine that cannot be reached: what can be is removed
(the copies here, the machines that answer), the rest is said and stays listed, marked; nothing is
queued.

ADR 0019 keeps its meaning: errand never removes by itself what a run made. Here the user asks, run by
run, and confirms.

## Considered options

- **A level per machine** (machine → project → …): a case run on lmo and on the Mac would be two trees.
- **A trash, emptied after 7 days**: safer, but Hugo wants the room back at once, the confirmation says
  what goes.
- **All or nothing when a machine cannot be reached**, or a queue of removals for later: the first
  blocks everything for one machine off; the second removes behind one's back later.

## Consequences

- The runs tab becomes readable for weeks of runs; the parameters of a study can be compared in place.
- Runs can be removed from the page and the TUI, on every machine at once.
- Agents gain an operation that removes: bounded to the leaves they noted.

## Steps

1. The model (`tui/rows.py`): the tree, the sets, the table as aligned text, the sort; `seen.runs` says
   name, file, params, results; the history limit 2000.
2. The page: folds, the header that sorts, the actions on a row ( `d`, `D` ).
3. The TUI: the same rows, `s`, `d`, `D`.
4. Removing: `runs_remove` in the agent ( `look.py` ), the copy here, the plan and its confirmation
   (`web.act`, the TUI's confirm).

## Done, 2026-11-19

- `tui/runtree.py`: the tree ( dirs merged, file, entry, sets ), its rows ( `tnode`, `thead`, `tset`, `run` ), the
  table as aligned text, the sort ( `s:<entry>=<col>` in `opened` ), `keep_latest`, `find`, `all_runs`. Node ids are
  short hashes ( entry names and parameter sets hold commas, and the page sends its sets comma-joined ).
- `tui/rows.py`: the runs tab = running, waiting, then the tree; `build( unfold = True )` for what looks a row up by
  its key ( a run's page `/job`, `/r/<id>` ).
- `agents/seen.py`: the history says `name`, `params`, `results`; the limit is 1000 ( `seen`, `watch` ).
- `agents/look.py`: `runs_remove` ( `dry`: sizes ), only leaves its `seen` noted, never a busy one; `latest` and the
  link go with it.
- `tui/removal.py`: `plan` ( how many per machine, the room through `dry`, the copies here under this machine's
  projects ) and `send` ( what was not removed, said ); the page's `/act` `runs_remove` and the TUI's `d` / `D` with
  the same red confirmation.
- The page: `t:` folds ( folded until opened, busy ones open until folded ), a header whose columns sort ( click, `s` ),
  the buttons "keep only the latest" ( `D` ) and "remove" ( `d`, in the list; in the detail `d` still downloads ).
- The TUI: the same rows, `→ ←` fold, `s` sorts, `d` / `D`.

Tests: `errand/tests/test_runs_tree.py` ( tree, table, sort, folds, keep_latest, the agent's op, plan and send with a
copy here ); `test_tui.py` and `test_web.py` updated to the tree. Seen on this Mac's and lmo's runs with `errand web
dev`: the foam table ( 13 sets ), sorted by `n` both ways, a set unfolded into its 4 runs; the plan of "keep only the
latest" for foam: 22 runs on lmo ( 399.6 MB ) and their 19 copies here, not confirmed.

Not done: a run that could not be removed is not marked in the list ( it simply stays ); commands run by `errand run
<cmd>` ( no file ) show as top rows of their own.

## Slow, then not ( 2026-11-19 )

The page was slow: not the tree ( 4 ms to build, 7 ms unfolded, `/state` ~50 ms ) but the history. The Mac held
27,323 links in `~/.cache/errand/seen` ( mostly errand's own test runs ), and `seen.runs` read every one and checked
every leaf before sorting and cutting at the limit: 1.2 s, every 5 s, in each agent's `watch` loop -- the loop that
also says what starts and ends. `seen.runs` now remembers in its process what it read: a link once, a `result.yaml`
again only when its date changes, the listing again only when the directory's date does; it checks the leaves of the
runs it says, and all of them every 10 minutes. 850 ms the first time, ~40 ms after. Test: the history remembered
( `test_runs_tree.py` ).

## In two times, several rows at once ( 2026-11-19 )

Hugo found the removal slow: the window waited for a `du` on each machine ( ~5 s ), the page for the removal itself.
Now the window opens at once: `removal.plan` asks nobody ( how many runs, where, the copies here ), `measure` then asks
the room freed and fills the window shown ( the page: `runs_measure` on the plan kept under an id; the TUI: a thread ).
Yes: the runs are greyed and struck through at once ( `runtree.GOING`, a row's mark `going`; the page greys them even
before the server answers ), removed from a thread; gone from the list when their agents removed them, shown again as
they were if not. What was done is said through `/events` ( `said` ). Several rows chosen together: ⇧↑ ⇧↓, ⇧-click,
⌘-click ( the page ), ⇧↑ ⇧↓ ( the TUI ); `d` and `D` act on all of them; esc, one again. Measured: `/state` 17 ms, a
plan 80 ms, a run's detail 35-90 ms. Tests: `test_runs_tree.py` ( the two times, the rows together, the greyed rows; the
page's flow through `Web.act` ).

## The older runs, files run whole, the table aligned ( 2026-11-19 )

- **Runs that came back**: a machine's history is its latest 1000 runs; "keep only the latest" removed what was listed,
  then the older runs of the same sets came up into the list -- as if the removed ones came back. Now a row of the tree
  goes to each machine as its id ( `runs_remove` `nodes`, `how` ), resolved there over every run it noted
  ( `look._selected` ); the window says them once measured ( "Mac: 1226 runs ( 857 older, not listed ), 5.4 MB" ) and
  removes exactly those; a yes before the window knew lets each machine resolve the rows itself. "Keep only the latest"
  is per machine too ( the set, env and machine ). The agent reads its links from `seen`'s cache, and rings the host
  agents when it removed ( asked by `errand web` for this machine, it is no agent ).
- **A file run as a whole** ( `sh x.sh`, `python foo.py` ) has no entry level ( `runs/<file>/<run>` ): its directory was
  read as the file's. `rel_file` now tells them apart by the file's name ( the record's `file`, else `what` ).
- **The table's header** started 19 px left of its lines in the page ( no sign column ): it has an empty one now.
- **A set of one run** is that run: its table line is the run's row ( `Row.tabled` ), chosen as a run ( its detail, its
  outputs, `d` ), nothing to unfold and its parameters not said twice. A set of several runs unfolds into them as before.
