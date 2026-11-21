---
status: accepted
date: 2026-11-21
amends: 0026
---

# A page's services run on the machine one chooses, as the installed packages describe them

ADR 0026 lets a page served by `errand.Static` reach the services its directory names, through a
relay at its own address. Its first version (steps 1-4, 2026-11-20) works end to end on one machine,
but three things are wrong:

- **the recipe is the writer's.** `services.json` carries a command with the paths of the machine
  that wrote the store (`-P /Users/…/sdot-ffi/src/sdot/viz/services/blender.py`, a `PYTHONPATH` to a
  checkout, the writer's Python). On lmo, on n14 or on a colleague's Mac, those paths are wrong;
- **a store can carry any command.** Only the person reading the recipe before saying yes stands
  between a dishonest `.sviz` and the machine;
- **everything happens on the machine that serves the page.** There is no choice of machine, no view
  of what a machine already has, and `errand status` lists a service only once it has run (its
  `spec.json`). That is why Hugo's page said his declared services were "not installed".

This ADR replaces three parts of 0026: *The directory says what it asks for*, *Installing* and *For
now, the service runs on this machine*. 0026 keeps the relay `.errand/svc/<name>/`, `.errand/`
reserved in every view, `X-Errand-Root`, the two-sided rule, `?svc.` and `--root` without errand, and
the conventions about answers.

Settled in a grill on 2026-11-21 (`grill/page-services/decisions.md`, three rounds).

## Decision

### 1. Code comes from packages; a store holds names and a copy of their description

The producer's **package** describes its services, as data, in a file it ships:
`errand-services.json`, next to the services' code (sdot: `sdot/viz/services/errand-services.json`).
errand reads it **without importing the package**. It finds it through an entry point,
`[project.entry-points."errand.services"] sdot = "sdot.viz.services"`, read in the env's
`*.dist-info/entry_points.txt`. The module's directory is resolved from the env's `site-packages`
or, for an editable install, from `direct_url.json` and the editable finder's mapping file.

```json
{ "format": 1,
  "package": { "name": "sdot", "pip": "sdot", "index": "https://pypi.org/simple" },
  "services": {
    "blender": {
      "protocol": 1,
      "text": "Pictures of the current view by Blender (Cycles, on the GPU when there is one).",
      "version_of": [ "blender.py", "../store.py" ],
      "run": [ "{tool:blender}", "-b", "--factory-startup", "-P", "{file:blender.py}", "--", "--port", "{port}" ],
      "needs": { "gpus": 1, "gpu_kind": "any" },
      "idle": "10m",
      "tools": {
        "blender": {
          "min": "5.0",
          "look": { "macos-*": [ "/Applications/Blender.app/Contents/MacOS/Blender" ], "*": [ "blender" ] },
          "version_from": [ { "plist": "../Info.plist", "key": "CFBundleShortVersionString" },
                            { "dirname": "blender-(\\d+\\.\\d+\\.\\d+)-" },
                            { "dpkg": "blender" }, { "snap": "blender" } ],
          "fetch": { "linux-x86_64": { "url": "https://download.blender.org/release/Blender5.2/blender-5.2.2-linux-x64.tar.xz",
                                       "sha256": "84098912…a168", "run": "blender-5.2.2-linux-x64/blender", "version": "5.2.2" },
                     "macos-arm64":  { … } } } } },
    "sdot.ao": {
      "protocol": 1, "text": "Bakes the ambient occlusion of the faces of the frame shown (sdot, CPU).",
      "version_of": [ "ao.py", "../occlusion.py" ],
      "run": [ "{python}", "-m", "sdot.viz.services.ao", "--port", "{port}" ],
      "idle": "10m" } } }
```

- **`run`** is a list of words, never a shell line. Its placeholders form a closed set, all
  resolved **on the machine that runs it**:
  - `{python}`: the interpreter of the env that has the package;
  - `{file:REL}`: a file of the package where it is installed there;
  - `{tool:NAME}`: a program found or fetched there (below);
  - `{port}` / `{port:NAME}`: for the keeper (ADR 0018).

  The literal words come from the package. They are trusted as much as the package is: it was
  installed on that machine.
- **`needs`**: `platforms`, `gpus`, `gpu_ram`, `gpu_kind` (`cuda`, `metal`, `any`), `ram`. Tools and
  the package are needs too, by their presence.
- **`tools`**: where to look (`look`, per platform pattern), where to read the version **in files**
  (`version_from`), and pinned downloads (`fetch`: URL, sha256, the program inside, its version).

**The store holds only names, and a copy of the description.** The producer writes its
`services.json`:

```json
{ "format": 2,
  "services": {
    "blender": { "version": "3fa29c1e", "protocol": 1, "optional": true,
                 "package": { "name": "sdot", "version": "2026.11.3" },
                 "described": { …the package's entry for "blender", copied, with its "package" block… } } } }
```

The copy lets a machine that lacks the package be told how to get it. It never runs anything (§4).
The store carries **no code**: code comes from repositories (PyPI, conda-forge,
download.blender.org) or from a local install (`pip -e`).

### 2. `name#version`: a hash anyone can recompute by reading files

```
h = sha256( f"errand-service/1 {name} protocol {protocol}\n" )
for rel in version_of:                        # in the listed order, relative to errand-services.json
    data = read( rel );  h.update( f"{rel} {len( data )}\n" );  h.update( data )
version = h.hexdigest()[ :8 ]
```

- The producer computes it when it writes the store. errand computes it on each machine, from the
  installed package's files. Both read files and run nothing. It works for an editable install whose
  checkout moved on ("lmo's checkout provides `blender#91c0d2aa`, the store asks `#3fa29c1e`").
- What `version_of` lists is the producer's choice: the service's file, what it loads by path
  (`blender.py` loads `store.py`), and what changes its answers.
- **Versions coexist.** A machine may declare `blender#3fa29c1e` and `blender#91c0d2aa` at once,
  because two stores were written by two sdots. The relay takes the exact version the store asks for,
  never a "compatible" one.
- **Checked before every start.** A declaration records the `errand-services.json` it came from. The
  keeper recomputes the version just before starting. If it differs, the service does not start and
  its state is `wrong version` (in the page and in `errand status`). A declaration with no provider
  (typed by hand) is `unverified`: allowed, and said.

### 3. Every machine is offered, per service; here first

The page offers, **for each service**, every machine errand knows (its places: the machines the
user's envs and hosts name). Each machine has a state:

| state | meaning |
|---|---|
| `running` | declared at this version and running |
| `ready` | declared at this version, not running (it starts at the first request) |
| `installable` | every need is met, or can be met by lines to type (and a store copy) |
| `unavailable` | a need cannot be met: greyed, with the reason ("no card", "no Blender for linux-arm64") |
| `wrong version` / `unverified` | as in §2 |
| `unreachable` | its agent did not answer within 10 s |

**Order**: `running`/`ready`, then `installable` (fewest lines, least to copy), then the rest. Within a
group, **here first**, then the machine the run wrote the store on, then errand's places in their order.
The default choice is the first of that order.

**The choice is kept by errand**, per view, on the machine that serves the page:
`POST .errand/services/<name> {"on": "lmo"}`, refused for a machine not offered. A change applies
from the next request; open connections stay where they are. Choosing a machine starts nothing and
installs nothing. It only says where to route among declared services.

**Reaching another machine.** A request on `.errand/svc/<name>/…` for a service chosen on M goes
through `forward` (ADR 0018, step 6): this machine's errand opens a channel to M's agent, which ensures
`name#version` there. `X-Errand-Root` names **the store as M sees it**: the original (where the run
wrote it), a copy on a file system M shares, or errand's copy on M (below). The page sees no
difference: same origin, same relay.

**A machine without the store.** The store is a need too. When M neither has the store nor shares a
file system with a machine that has it, the page offers a **Copy to M** button with the size
(`1.3 GB, 412 files`). The button asks errand (`POST .errand/copy {"on": "n14"}`) to copy the view's
files into a cache zone of errand's on M (`views/<id>/`, ADR 0022: a zone per file system). The copy
is kept up to date while the view is open, as a brought-back view is (ADR 0017 §5: what changed
comes, the manifest last). It is removed with the view or by `errand caches`.

This is the one action a page triggers by itself. It copies the view's own files, as data, into
errand's cache on a machine of the user's. It runs nothing and declares nothing.

### 4. Lines to type, tailored to the machine; nothing installed by the page

For each service and each machine, errand composes the lines that would make it `ready` there, **from
what that machine has**. The page shows them, with a comment per line saying what it does to the
machine, and a *Copy* button. It runs none of them.

```
# 1 · Blender 5.2.2 from download.blender.org into errand's cache on lmo ( 342 MB, checked against its sha256 8409…a168 )
errand serve fetch --on lmo https://download.blender.org/release/Blender5.2/blender-5.2.2-linux-x64.tar.xz#sha256=84098912…a168
# 2 · the service blender#3fa29c1e, as lmo-jax's sdot describes it, GPU 1, stopped after 10 min unused
errand serve install --on lmo --gpus 1 --idle 10m blender#3fa29c1e -- /home/hugo/.cache/errand/tools/84098912…/unpacked/blender-5.2.2-linux-x64/blender -b --factory-startup -P /home/hugo/miniforge/envs/lmo-jax/lib/python3.12/site-packages/sdot/viz/services/blender.py -- --port {port}
```

- **`errand serve fetch --on M SOURCE`** brings code from a source into errand's cache on M, and
  runs nothing:
  - `URL#sha256=…`: a file, checked, kept by its contents (`tools/<sha256>/`), unpacked. Its path is
    known before it runs, so the next line can name it;
  - `pip:sdot==2026.11.3 [--index URL]`: a dedicated env made by errand (a uv venv,
    `errand-svc-sdot-2026.11.3`, under errand's build records, ADR 0004) that touches no other env.
    `--into ENV` installs into an existing env instead; the page offers it when an env of M already
    has the package's dependencies.
- **`errand serve install --on M [needs] name#version -- WORDS`** writes the declaration into M's
  `services-installed.json`, keyed by `name#version`. The command is spelled out with M's paths: the
  person sees exactly what will run. `install` looks up which package on M provides that exact
  `name#version` and records it (§2, the check before every start). If none does, it says so and
  records the declaration as `unverified`.
- `errand serve install` with no `--` (`errand serve install --on M blender#3fa29c1e`) composes the
  same command from M's package, shows it and asks. It is the short form for someone who trusts the
  package.

**Which description composes the lines.**
- To **run**: only the description of a package **installed on M**. Never the store's copy.
- To **propose** installing: the description of a package on M, else of one installed **here**,
  else the store's copy. The page says which ("described by the store, not by a package of lmo").
- **Trusted sources**, per user: `errand.sources = [ "https://pypi.org/simple", "conda-forge",
  "https://download.blender.org/" ]` (these three by default). A line that fetches from a source not in
  the list is shown **in red**: "unknown source, named by the store". `fetch` refuses it unless the
  person repeats it in `--source <url>`.
- A local install (`pip -e ~/Projects/sdot-ffi`) is never proposed. It is **found** (by the
  `dist-info`'s `direct_url.json`) and counts as an installed package.

### 5. The diagnosis: the agent looks, and runs nothing

Beside the lines, the page shows what M's agent found. This is a new read-only agent operation,
`services`, beside `look.OPS`. It takes the descriptions to look for (from M's packages, here, or the
store) and the paths the user gave. It answers:

- the services M declares under that name, with their versions and states;
- the envs of M that have the package (an env errand knows on M, and the envs under the
  `micromamba` / `conda` roots of M), their version, and the `name#version` each one provides;
- for each tool:
  - the candidates found, from the description's `look`, the `PATH`, errand's cache, and the paths the
    user gave;
  - the version of each, **read from files** by the description's `version_from` rules (`Info.plist`,
    a directory name, dpkg's status file, snap's `meta/snap.yaml`, a `dist-info`), and whether it meets
    `min`;
- the cards (the agent's `resources`), free or held;
- whether M sees the store: original, shared file system, errand's copy, or none (with the size to
  copy).

```
What lmo's agent found
· /usr/bin/blender · 4.1.1 (dpkg) — this service needs 5.0 or later
· no other Blender on the PATH, nor in errand's cache
· sdot 2026.11.3 in the env lmo-jax — provides blender#3fa29c1e, the version this store asks for
· a card: RTX 2080 Ti, 11 GB, free now
· the store: the original, /home/hugo/runs/foam.sviz
```

**Nothing is run to read a version.** When no rule applies, the version is "unknown", and the page
offers a line that the person types, naming exactly what it runs:

```
# runs /opt/foo/blender --version once, on lmo, to read its version
errand serve probe --on lmo -- /opt/foo/blender --version
```

The answer is kept by (path, size, date). The user can also give a version by hand with a path
(`--path blender=/opt/foo/blender@5.2.2`, or the page's path field).

**A path the user gives.** The page has a field per tool: "Blender is installed at …". It is
`POST .errand/machines/<M>/paths {"tool": "blender", "path": "/opt/foo/blender"}`, kept here, per
machine. It only adds a place for the agent to look (a `stat` and the file rules). It is never run.

**When.**
- On opening: the machine chosen for each service.
- On opening the machine menu: the others, in parallel. Each one shows when it answers ("…" before,
  `unreachable` after 10 s).
- The answers are kept per machine, here, until *Refresh* or until a file they read changes.
- *Refresh* re-reads the files of the chosen machine, or of every machine when the menu is open. It
  never re-runs a `probe`.

### 6. errand lists every declared service, and `spec.json` goes

- `errand status`, `errand serve list`, `errand web`: the union of every declaration and every state.
  A service declared and never started is `ready`. Each line shows `name#version` (no version for a
  declaration by hand that gives none), where it is declared (`services.py`, `installed`, `adhoc`, a
  project), and its state (§3).
- `.errand/services` says `ready` where it said `declared`.
- **No more `spec.json`.** The keeper reads the declaration by its name, from where it lives:
  - `services.py` and `services-installed.json`, read again;
  - an ad hoc service (`errand serve --gpus 1 -- ollama serve`) is written into
    `services-installed.json` with `"adhoc": true`, and removed when it stops;
  - a project's service is read again from the project, whose path stays in `state.json`.

  `state.json` (pid, ports, state) stays.

### 7. What the page calls

All relative to the view's own address (one origin, one token, ADR 0026):

| call | answer |
|---|---|
| `GET .errand/services` | per service: `version`, `protocol`, `optional`, `text`, `on` (the machine chosen), and that machine's entry (below) |
| `GET .errand/machines` | the machines offered, in order, with whether each one's diagnosis is known yet |
| `GET .errand/machines/<M>[?refresh=1]` | per service of the store: `state`, `why`, `store` (`original` / `shared` / `copy` / `none` + size), `found` (the diagnosis lines), `lines` (`[{ comment, command, described_by: "M" / "here" / "store", unknown_source: bool }]`); waits for M's agent up to 10 s |
| `POST .errand/services/<name>` `{"on": M}` | the choice (§3) |
| `POST .errand/copy` `{"on": M}` | starts the copy; its progress is in `.errand/machines/<M>` (`store: {"copying": 0.42}`) |
| `POST .errand/machines/<M>/paths` `{"tool", "path"}` | a place to look (§5) |
| `ANY .errand/svc/<name>/…` | the relay, to the machine chosen (§3) |

Under any other static server these are 404s, and the page is on its own (ADR 0026, *Without errand*).

## Considered options

- **The store carries the recipe (0026 as built).** The writer's paths are wrong elsewhere, and a
  dishonest store writes what it likes.
- **The store carries a restricted template**: literal words remain (`-c 'import os…'`), which would
  need a grammar and an allow-list.
- **The store carries the service's code** (`blender.py` needs only Blender's Python): a forger
  recomputes any hash, and the store becomes a way to ship code. Code comes from repositories or a
  local install.
- **A hash of the full install line**: the paths differ from machine to machine, so the same service
  would have a different identity on each.
- **`GET /errand/identity` asked of the service at start**: needs the service to run before its
  version is known, and every service to implement it. Recomputing from files does the same with
  nothing run.
- **`--version` run by the diagnosis**: running a program to look at it. It is only run when the
  person types `probe`.
- **Only the machines that hold the store**: Hugo wants every machine; the store becomes a need that a
  copy satisfies.
- **The store copied by a typed line**: Hugo prefers a button. A copy is data into errand's cache, so
  a button is acceptable.
- **The choice of machine in the URL** (`?on.blender=lmo`): the relay would trust a parameter on
  every request, and each browser would have its own choice.
- **A new verb `errand server`** beside `errand serve`: the two would be confused.

## Consequences

- A store no longer names a path. The same store opened on the Mac, on lmo or by a colleague gets
  lines tailored to the machine chosen.
- A dishonest store can name a service, and propose fetching from a source. A source outside the
  user's list is red and refused without a typed `--source`. It cannot make a machine run anything:
  running uses only descriptions of packages installed there.
- A page can copy its own view to a machine of the user's, unasked: a page that clicks its own button.
  This costs disk space in errand's cache, shown in `errand caches`, and runs nothing.
- Every machine errand knows may be asked for a diagnosis: the menu opens connections to agents (lazily,
  in parallel, 10 s).
- `errand status` shows services nobody has started yet.
- A producer must ship `errand-services.json` and its entry point, and compute versions the same way
  errand does. The algorithm is in §2: about ten lines, with no errand dependency.

## Steps

**errand**

1. `errand status` / `serve list` / `web` list every declaration (`ready`); `spec.json` removed
   (ad hoc into `services-installed.json`, the project's path in `state.json`); `declared` → `ready` in
   `.errand/services`.
2. Packages: the entry point `errand.services` found in an env's `dist-info` (editable installs too),
   `errand-services.json` read, the placeholders composed, `name#version` computed from files;
   declarations keyed `name#version`; the check before start (`wrong version`, `unverified`).
3. The agent's `services` operation (read-only): envs, tools with `version_from`, cards, the store;
   `errand serve probe`; `--path`.
4. `errand serve fetch` (`URL#sha256=`, `pip:` into a dedicated uv env, `--into`), `errand.sources`
   and `--source`; `errand serve install --on M name#version -- WORDS` and its short form.
5. The page's calls (§7): machines, the choice per view, lines composed per machine, the relay
   through `forward` with `X-Errand-Root` as M sees the store.
6. `POST .errand/copy`: the view copied into errand's cache on M, kept up to date, removed with the
   view or by `errand caches`.
7. The guide (*A page that asks for a service*, *Installing what a page asks for*) rewritten; tests:
   a dishonest store (an unknown source, a service no package provides), two versions side by side,
   an editable checkout that moved on, a machine without the store.

**sdot** (amends `sdot-ffi/adr/0001` §3)

1. `sdot/viz/services/errand-services.json` (blender, sdot.ao, sdot.region: `run`, `version_of`,
   `needs`, `tools` with Blender's `look`, `version_from` and `fetch`); the entry point in
   `pyproject.toml`; the file shipped in the wheel.
2. `declare( store )` writes the format-2 `services.json`: names, versions computed by §2's algorithm,
   the copied description. No path, no `PYTHONPATH`, no `sys.executable`.
3. The services stay as they are (`--port`, `X-Errand-Root`, `--root`).

**The page** (the viewer, in sdot; for the session rewriting `Visualizer.py`)

1. The services panel, per service:
   - a machine menu, in errand's order; greyed entries with their reason;
   - the state;
   - "What M's agent found";
   - the lines with their comments, red for an unknown source, and *Copy*;
   - *Refresh*;
   - a path field per tool;
   - *Copy to M* when M lacks the store.
2. A service's controls (Render, Bake, Cells) are enabled when the chosen machine says `ready` or
   `running`. Otherwise they are greyed with the panel's one-line reason.
3. Without errand (the 404s): as 0026 says, the text and `?svc.`.

## Progress

- 2026-11-21, errand steps 1-7 done (uncommitted), sdot steps 1-3 done (uncommitted). The page steps are left to the
  session rewriting the viewer.
  - New modules:
    - `errand/packages.py`: envs (conda / micromamba roots, errand's `svc-envs`, this interpreter), providers found by
      the entry point in `entry_points.txt`, editable installs through `direct_url.json` and the finders' `MAPPING`,
      §2's version, `compose`;
    - `errand/diagnose.py`: the read-only look; versions from `Info.plist`, a directory's name, dpkg, snap, errand's
      fetches, and remembered probes; the states and the lines;
    - `errand/agents/servicesop.py`: the agent's `services` operation (`look`, `copy_into`, `compose` read-only; `probe`,
      `fetch`, `install` from the command line);
    - `errand/reach.py`: the machines (here, then the ledger's), `--on M`, `ask`.
  - `install.py` rewritten: `install( key, words | None )`, `composed`, `check`, `fetch_url`, `fetch_pip` (a uv venv
    under `<cache>/svc-envs/`), `errand.sources`.
  - `serve.py`:
    - names may carry `#version`;
    - `listed()` is every declaration plus every state, `ready` / `unverified` / `wrong version`;
    - `spec.json` is gone: the keeper gets `NAME [CWD]` and reads the declaration;
    - ad hoc services go into `services-installed.json` with `adhoc` and are removed at stop;
    - `declared()` is serialised by a lock.
  - `web/page_services.py` rewritten after §7: format 2 (format 1 still read, without a version), the choice per view
    (`serve/choices.json`), paths (`serve/paths.json`), diagnoses kept 300 s (2 s here), the relay to another machine
    through `serve.forward`, the copy by `syncop.push` into `views/<vid>` on M, re-pushed every 10 s while the page
    asks.
  - `static.register( origin = )` with `static-origins.json`. `cli/views.py` and `cli/drive.py` give a view's machine
    and path over there.
  - CLI: `errand serve look | fetch | probe | install [--on M]`. `errand serve install DIR NAME` is refused with a
    pointer to `look`. `errand status` and `errand serve` show `ready` services with where they are declared.
  - Tests:
    - `tests/test_install.py` rewritten, 9 pass: providers, editable, ready → wrong version, unverified, short form, ad
      hoc, fetch and sources, a diagnosis that runs nothing, a dishonest store;
    - `tests/test_page_services.py` rewritten, 4 pass, including another machine through a local agent: its
      diagnosis, the relay through it, the copy;
    - `test_serve`, `test_forward`, `test_static_views` and `test_status` still green.
  - Guide: *A page that asks for a service* rewritten.
  - sdot: `viz/services/errand-services.json`, the entry point in `pyproject.toml`, `declare()` in format 2, and
    `version()` (the same digits as errand's, checked). `test_viz_ao` updated and green.
  - Departures from the Decision:
    - the diagnosis has a state `unknown` (a tool whose version no file says, with no fetch for this platform): the
      lines are only the `probe` lines;
    - `Info.plist` is read relative to the program's directory (`../Info.plist`);
    - when a package is not on M, `install` is proposed in its short form (no `--`): the command is composed only
      once the package is there.
  - Not done / not tried:
    - the sdot installs on this Mac predate the entry point. `pip install -e ~/Projects/sdot-ffi` again in an env makes
      errand find it. Until then the diagnosis says "describes no service";
    - no real remote machine tried yet (lmo): only a local agent standing for one;
    - a shared file system is recognised by checking the files at the paths sent. Errand's ADR 0022 views of file
      systems are not used;
    - the host agent must be restarted to serve the new routes.
