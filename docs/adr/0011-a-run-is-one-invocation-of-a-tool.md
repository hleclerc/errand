---
status: accepted
date: 2026-11-16
---

# A run is one invocation of a tool; entries lose their needs

errand was first designed around tests and benchmarks. Each entry carried what it needed (`cpus`,
`ram`, `gpus`, `ranks`, `exclusive`), how it should be treated (`bulk`, `keep`, `stable_path`) and
what kind it was (`test`, `bench`, `experiment`). Every runner cut its files into entries so that
each case could be its own run, with its own claim in the queue, its own record and its own output
directory. That cut is where most of the runners' complexity sits: `collect`, building in order to
list (`builds_to_collect`), `whole_files` / `takes_selector`, the pytest collection plugin, and one
pytest process per test.

It is not used. Across loom, sdot-ffi and otrec there are 810 `test( … )` declarations, and one
of them passes an argument (`ranks = 4`). No one else declares needs. What still matters in runners is
something else:

- the interpreter depends on the place (`python3` here, `python` there, a pinned one elsewhere);
- `file::name` should call the file's test tool, without the user having to name it;
- finding that tool and adapting it to the environment is worth doing for the user.

errand must also stay agnostic: Python is the language we happen to use, not the one errand
serves.

## Decision

**A run is one invocation of a tool.** `x.py::test_y` is handed to the tool once, and the tool does
the selection (`pytest x.py::test_y`, `cargo test y`, `ctest -R y`, `./suite "y"`). errand no longer
lists the cases before running them. It makes no run, record, claim or directory per case. A target
of N files is still N runs, and the place grid of ADR 0007 is unchanged.

**A runner is a claim and a command.** A runner says which files it takes (extension, shebang,
something in the contents, a file nearby such as `Cargo.toml` or `conftest.py`). It turns a target
into an argv in which tools are named, not resolved:

| runner     | takes                                     | command                                      |
|------------|-------------------------------------------|----------------------------------------------|
| `python`   | `x.py`                                    | `{python} x.py`                              |
| `pytest`   | `test_*.py::sel`                          | `{python} -m pytest x::sel --junitxml={report}` |
| `errand`   | a `.py` that imports errand, `::sel`      | errand's own entries, below                  |
| `cargo`    | `::sel` in a crate                        | `{cargo} test sel`                           |
| `catch2`   | a Catch2 source, `::sel`                  | build, then `{binary} "sel" -r junit::out={report}` |
| executable | anything else                             | the file or command as it is                 |

Optionally, a runner also has a **build** command, run once per command and per environment in
`{build_dir}` during the preparation (see Building), its **zones** and its **jobs** form, and a **list** command (`pytest --collect-only -q`, `--list-tests`,
`cargo test -- --list`). `errand list` shows the list command's output as it is: errand does not
read entries from it. The rule of ADR 0003 that decides which runner takes a target is kept: `::`
goes to an entry runner, anything else to a file runner, and among entry runners the most
specific claim wins, with a tie reported as an error.

**Tools are named and resolved in the place.** A runner starts `python`, `cargo`, `cmake`… by name.
The environment can give its own name for each: `Env( [ … ], tools = { "python": "python3.12" } )`.
Without one, `python` is the interpreter errand runs on in that place (already the environment's,
since errand runs inside it), and any other tool is the first of its usual names found on the
`PATH`. A target whose first word is a named tool runs as named, and a build line writes
`{cmake}`. A tool that is missing follows the rule pytest follows today: it is installed when the
environment is errand's own, and reported otherwise.

**Needs belong to the run, not to the entry.** `--cpus`, `--ram`, `--gpus`, `--ranks` and `-x` on
the command line, or as options of a runner instance. The queue is unchanged, since it never needed
to know about entries. The traits go: `bulk` is already `default_run`, `keep` and `stable_path` go,
and `exclusive` is `-x`. `test`, `bench` and `experiment` become aliases with no meaning, and
`-k` goes.

**`-j N` runs N runs at once; a single run gives it to its tool.** Several runs (files, grid
points) are what runs at the same time, each on one worker, so the tools never multiply the
machine's cores. A single run has nothing beside it: `-j N` then goes to its tool when the runner
says it takes it (`Runner.jobs`): pytest-xdist's `-n N`, cargo's `--test-threads N`. Whether the
tool accepts it can depend on the place: xdist is a plugin, so it is checked there, and installed
or reported by the same rule as pytest itself. The claim of that run asks for N cpus, unless
`--cpus` says otherwise. A runner without a parallelism of its own (Catch2, a script) is said to
run alone, rather than handed a flag it does not know.

**errand's own entries stay, as one runner among others.** `if test( "…" ):` is how loom and sdot
write their tests, and it keeps its name, `Param`, its tags and one process per selected entry.
That is now the runner's internal business, not the core's. `ranks` stays an argument of these
entries, because this runner starts each entry itself and can start that one under MPI.

**One output directory per run.** `-o` asks for one, as before:
`runs/{target, selector included}/{when}-{place}[-{args}]/`, exported as `ERRAND_OUT_DIR`. A
directory per case is the tool's business: errand's entries write `{out}/{entry}/`, and a pytest
fixture can write `{out}/{nodeid}/`.

**A runner says where its tool writes.** The first choice is to point the tool at the output
directory in its command (`--junitxml={out}/…`, `--benchmark-storage={out}/…`). For what a tool
writes elsewhere by its nature, a runner declares **zones** (ADR 0006), the way a layer adds what
it builds (`kept()`):

- `back` for what the user wants here: `target/criterion/` for `cargo bench`, `htmlcov/` for a
  pytest run with coverage, `.benchmarks/` for pytest-benchmark when it is not redirected;
- `build` for what stays over there and is never overwritten by a push: `target/`,
  `{build_dir}`, `.pytest_cache/`.

The zones of a runner are part of the project's zones, as what a layer builds is, whichever runner
a command uses: environments and commands share one copy over there. A `back` zone is brought back
after each command, whether or not `-o` was given, because the tool writes there whether or not
anyone asked. The project's own `zones =` has the last word on a path both name. A zone is a path
from the project root, and may name the environment: `{env}`, and `{build_dir}` for `build/<env>`
(`/{build_dir}/target/criterion`). Without an environment in view, a zone stands for every declared
one, since they share the copy.

**Per-case results come from the tool's report.** When the tool writes a JUnit XML report (pytest,
Catch2, ctest, cargo-nextest, go via gotestsum, jest…), errand reads it into the run's record:
counts by status and the names of the failed cases. A tool without a report gives one status, its
exit code, and 77 still means SKIP. `ERRAND_RESULTS` is unchanged.

**The core knows no language.** The table above is data, and adding a language is one row. The
configuration stays in Python (`errand-envs.py`). That is errand's configuration language, not the
language of the work it runs, in the way Starlark is Bazel's.

## Building

errand still compiles nothing itself (`what-is-errand.md`). It decides **where** the build command
runs and **how its result reaches** the place that runs, and leaves "what is stale" to the tool
(make, ninja, cargo).

**A runner's build runs in the preparation phase, its command in the run phase.** Compiling on one
machine and running on another is therefore an environment, not a runner option. The preparation
has its own list of layers, which defaults to the run's:

```python
login = errand.Ssh( host = "login.hpc", root = "/scratch/me/proj" )
image = errand.Apptainer( image = "containers/cuda.sif" )   # both phases: same compiler, same libraries

errand.envs[ "cluster" ] = errand.Env(
    [ login, errand.Slurm( partition = "gpu", gpus = 1, time = "2:00:00" ), image ],
    prepare = [ login, errand.Slurm( cpus = 16, time = "0:30:00" ), image ],
)
```

**Layers lose `when`.** It used to select the phase (`when = "phase=prepare"`) or tags
(`when = "cuda"`) for each layer. That made you rebuild two stacks in your head from one list.
Two explicit lists cost a copy, which is cheap in Python, and a tag-dependent layer is either a
`Vars` whose values are a function of the tags, or another environment. A conditional layer
(`OnRun( … )`) was rejected for the same reason. It leaves holes in an ordered stack, needs its
mirror `OnPrepare`, and would soon become `OnTag`, which is `when` again.

A `build =` list, defaulting to `prepare`, can be added later if building and the rest of the
preparation need different places.

The same build is used by every target of a command and every point of its grid. It runs once per
environment and per command, never once per run, and it fails the command before anything runs.

**The build directory is the environment's (`build/<env>/`, `{build_dir}`), and it is a `build`
zone.** Then there are two cases.

- **The preparation place and the run place see the same copy.** This is a login node and compute
  nodes sharing `/scratch`, or two hosts with one home. ADR 0006 already recognizes this from the
  copy's manifest, without anything being declared. Nothing moves.
- **They do not.** The build zone is **carried** from the preparation copy to the run copy after the
  build. It goes through the agents, by manifest, like any other sync. With the default rule of
  ADR 0005 (the local side orchestrates), it goes through here. Only what changed crosses, and
  mtimes are kept, so the run place does not look stale to make the next time it is the
  preparation place. This is a third direction for a zone, next to `back` and pushed: from one copy
  to another.
  The plan the run checks itself against was written in the preparation's copy: it travels with
  the run's request, and is kept in the run's copy for `status`. Each machine is set up with its own
  list of layers (`Env.places`).

**The machine that runs can be different from the one that builds.** A login node may lack the
GPU, have another CPU generation, or have other system libraries. Errand does not check that.
Running both phases in the same image, as in the example, is the recommended answer, and the
documentation says so. The build's own record (ADR 0004: fingerprint, stamp) names the place that
built it, so a mismatch can at least be read after the fact.

**A plain command can have a build too.** `errand.runners[ "solve" ] = errand.Command(
"{build_dir}/solve", build = "cmake --build {build_dir}" )` is a runner instance like the others:
`errand run -r solve …`, or claimed by pattern.

## Open

- The carry between two copies through here doubles the traffic of a large build directory. A direct
  transfer from agent to agent is an optimization for later, and needs the two places to reach each
  other.
- Whether a `back` zone should be brought back after every run, or only when it changed, is left to
  the manifest: only what changed crosses anyway.

## Considered options

- **Keep the per-case cut and drop only the needs.** This keeps the per-case history and
  directories. It also keeps everything that makes runners heavy (listing, building in order to
  list, one process per pytest test) for the sake of per-case claims, which were the reason for the
  cut and which no one uses.
- **No runners, plain commands only.** The user would write `python3 -m pytest …` in the right form
  for each environment, and `x::y` would mean nothing. Choosing the interpreter for the place and
  finding the test tool are exactly what is worth keeping.
- **Infer the tool from the project, not from the file.** This is not enough. In the same directory,
  `test_a.py` may be pytest's and `test_b.py` errand's, and only the contents can tell them apart.

## Consequences

- A pytest target runs in one process instead of one per test. That is much faster, but a crash
  (a segfault in a native kernel) now ends the whole run. Isolation comes from the tool
  (`pytest --forked`, xdist) or from errand's own entries, which keep one process per entry.
- History shows a run with its counts and its failed names, not a row per case that has its own
  timeline. Comparing a case across dates goes through the reports kept with `-o`.
- Code that goes: `collect` / `builds_to_collect` / `whole_files` / `takes_selector` in
  `runner/base.py`, `_pytest_plugin.py`, the per-entry path of `results.py`, `TRAITS` and the
  needs part of `RESOURCES` in `entries.py`, and Catch2's build-in-order-to-list. Pages that change:
  `guide/runners/*`, `guide/declaring-work.md`, `guide/output.md`, `reference/runners.md`.
- This revises ADR 0001 (runners collect N entries) and ADR 0003 (needs per entry, in the
  framework's vocabulary), and drops the "Needs" and "Traits" points of 0003's step 2.
