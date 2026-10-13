---
status: accepted
date: 2026-10-13
---

# Targets are resolved in the environment, in a preparation phase and a run phase

The side errand is started from used to resolve the targets, collect the entries and expand the
grid before entering any environment, and used that list to predict what to fetch back, what
`--batch` would produce, what the screen would show, and how big a Slurm allocation to ask for. It
cannot: there is not always a local environment. A binary built over there exists only over there;
`cargo metadata` needs a cargo; a file that imports torch can only be read where torch is. And a
compiled suite can only list its cases once it is built, where it is built. So **the side errand is
started from only chooses the environments and forwards the command as it was typed**; resolving the
targets, building, collecting and expanding the grid all happen in the environment. A typo is then
reported from there, after entering it: that is the price, and it is the right one.

**Two phases.** Preparation resolves, builds and collects, and writes a **plan**: the entries, what
they ask of a machine, and the directories they will write. The run phase runs it. The plan is what
the fetch back, `status`, `watch` and the screen read, and what a run-phase allocation is sized
from. The run phase collects again without rebuilding and checks that the plan has not changed —
the sources moved between the phases, or the filesystem is not really shared — which is an error.

**Layers carry conditions.** Every layer takes `when =`, an expression in the language `-t`, `-e`
and `has_tag` already speak, with a reserved pseudo-tag `phase` ( `prepare` or `run` ). A layer
with no condition is active in both phases. This keeps every layer's arguments symmetric — two
`Slurm( … )` with all their options, one per phase — rather than a `prepare = { … }` argument on the
scheduler that would describe a second allocation in a second vocabulary. At most one scheduler is
active per phase; each phase's stack is checked like any stack. In preparation a scheduler starts
one task, whatever `nodes` says — preparing is one process — and is not sized from entries nobody
knows yet.

**One pass or two.** One pass when the active stack is the same in both phases and holds no
scheduler: the child prepares, writes its plan, and runs, in one process, and the fetch back reads
the plan afterwards. Otherwise two passes. Under `--batch` the preparation is itself submitted, and
submits the run phase when it is done, sized from its plan: the shell comes back at once, and
`status` says preparing, queued, running.

**Consequences.** `errand list` is the preparation phase: it answers what would run *there*, which
only there can say — on a cluster it goes through the preparation queue. `errand setup` covers the
union of both phases' layers. Catch2 builds during preparation and lists its cases with the binary,
one entry per case like pytest: the one-entry-per-file granularity was only a workaround for
collecting without building.
