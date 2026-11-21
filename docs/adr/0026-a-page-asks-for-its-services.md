---
status: proposed
date: 2026-11-20
amended-by: 0027
---

# A page asks for its services, and errand serves it through the page's own address

`errand.Static` (ADR 0017 §5) serves a directory that carries its own page: files, read-only, on a
server beside `errand web`, with the token in the path. Nothing runs there, and the page reaches
nothing of errand. `errand serve` (ADR 0018) keeps servers on a machine: started on demand, never
twice, under the queue, stopped when nobody uses them.

Put together, a page can do more than show its files. A page can ask for things that only a program
can compute:
- a picture of the current view by an offline renderer (a Blender that stays loaded);
- a field computed on demand;
- the part of a large scene that is being looked at, rebuilt from small sources rather than stored.

Those answers are not files written once by the run. They depend on what the person is doing in the
page: the camera, the frame, the region.

Two things must still hold:

- **a directory stands on its own.** Opened by any static server (`python -m http.server`), or by
  someone without errand, the page works on its files. What it cannot do is said, with how to get it.
- **a page is data.** A run's page may come from someone else's run. It must never make errand run a
  command that the machine's owner has not declared.

Settled in a grill on 2026-11-20.

> **Amended by ADR 0027 (2026-11-21).** *The directory says what it asks for*, *Installing* and *For now, the
> service runs on this machine* are replaced: code comes from installed packages (`errand-services.json`), a store holds
> `name#version` and a copy of the description, and each service runs on the machine one chooses in the page. The relay,
> `.errand/`, `X-Errand-Root`, the two-sided rule and `?svc.` stay as below.

## Decision

### The directory says what it asks for: `services.json`

At the root of the directory, beside the page, the producer writes the services the page can use:

```json
{
  "render": {
    "protocol": 1,
    "optional": true,
    "install": {
      "text": "Offline pictures of the current view.",
      "command": "{download:blender} -b --python-expr 'import viewer_render; viewer_render.main()' -- --port {port}",
      "ports": "",
      "downloads": {
        "blender": {
          "version": "4.5.3",
          "url":    { "linux-x86_64": "https://…/blender-4.5.3-linux-x64.tar.xz", "macos-arm64": "https://…" },
          "sha256": { "linux-x86_64": "…", "macos-arm64": "…" },
          "run":    { "linux-x86_64": "blender-4.5.3-linux-x64/blender", "macos-arm64": "Blender.app/Contents/MacOS/Blender" }
        }
      }
    }
  }
}
```

- **The name is abstract** (`render`, `field.ao`, `region`), with the version of the protocol the page
  speaks. The directory never says where a service runs, nor with which cards.
- **`install`** is a recipe, made of data and not a script: a text for people, a command, ports, and
  downloads pinned by version and sha256 per platform.
- The name of the file is a parameter: `errand.Static( "index.html", services = "services.json" )`.
  That default name has no "errand" in it, because the page reads the same file without errand.

### The machine says how it runs: `services.py`, as in ADR 0018

A name in `services.json` is reachable only if the machine declares a service by that name in
`~/.config/errand/services.py` (or the installed services below). The declaration holds the command,
the env, the claim (`gpus = 1`), `idle`, the ports.

**A page can start only what both sides name**: a service the directory asks for *and* the machine
declares. A name the page asks for but `services.json` does not list is refused too, so a page cannot
reach every service of the machine, only those its directory says it uses.

### The page reaches them through its own address

The `errand.Static` server reserves one name in every view, `.errand/`:

- `GET .errand/services`: for each service the directory asks for, `{ "state": "declared" |
  "running" | "missing", "protocol": n, "install": "<command to type>" }`. The page finds it next to
  its own URL (a relative fetch). Under any other static server this answer is a 404, and the page
  knows it is on its own.
- `.errand/svc/<name>/<path>`: a **relay**, at the HTTP level, WebSocket upgrades included:
  - errand ensures the service, as `errand serve --ensure` does, waiting in the FIFO queue if a
    claim must wait;
  - it relays the request to the service's announced port;
  - it adds **`X-Errand-Root: <the view's directory here>`**: a service shared by every view learns
    which directory a request is about, while the page never sees a local path.

One origin, one token, no CORS. A connection held by the relay is a connection of the service, so the
service is not stopped while a page uses it (ADR 0018's activity rule).

For now, the service runs **on this machine**, beside the copy of the directory errand brought back.
Later, a declaration can say that a service runs where the directory was written (`there = True`): the
relay then goes through `forward` (ADR 0018, step 6) to the run's machine, with `X-Errand-Root`
naming the directory over there. The page sees no difference.

### Without errand

- the page works on its files. The controls of a missing service are greyed, with its `install.text`
  and the command to start it by hand;
- **`?svc.<name>=<url>`** in the page's URL points a service at a server started by hand. Such a
  server is told its directory on its own command line (`--root DIR`): there is no relay to add
  `X-Errand-Root`. It answers CORS for `127.0.0.1` / `localhost` origins, since the page is on another
  port.

### Installing: a recipe proposed, and confirmed by a person

`errand serve install <view> <name>` (and later, a button in `errand web`, an origin of errand's own):

1. shows what the recipe would declare: the command, the ports, what it downloads, from where, with
   which hash;
2. asks, and does nothing without a yes;
3. downloads into errand's cache, named by contents (as in ADR 0013), checks the hash, and writes the
   declaration into `~/.config/errand/services-installed.json`, which errand reads after
   `services.py`. A declaration in `services.py` wins over an installed one of the same name.

The page itself can only show the command to type. **Nothing runs on the word of a page or of a
`services.json`**: the relay starts only declared services, and only a person declares one.

### What services answer

errand does not look at the answers. By convention (the guide says it):

- answers are **ephemeral** for errand, and a service caches what costs with `errand.memo`
  (ADR 0015), keyed by its inputs;
- a service that offers to **keep** a result writes it into the directory it was asked about (under
  `X-Errand-Root`), and adds it to the directory's own index. The directory then stands on its own for
  what someone chose to keep. errand brings it back like any other change to a view.

## Considered options

- **Actions as commands that only write files** into the directory (a run per request). This
  keeps everything a file, but answers that follow the camera are not files, and a renderer that
  reloads its scene on every request is slow. Kept only as the "keep" convention.
- **Direct URLs per service** given to the page: several origins, a token per service, CORS
  everywhere.
- **The page declares the command** (no `services.py` entry needed): any page could run anything.
- **A second launcher in the page's tool**, for use without errand: it would duplicate the queue,
  the ownership and the stopping rules. `?svc.` covers that case instead.
- **Inside `errand web`**: its preview is a sandboxed iframe with an opaque origin (ADR 0017 §5), so
  the page could not fetch its files. Opening that up would let a page post to `/act`.

## Consequences

- `errand.Static` stops being "nothing runs here": a page can start declared services. The two-sided
  naming rule and the install confirmation are what keep that safe. A test pins them down: a name the
  directory lists but the machine does not declare, a name the machine declares but the directory does
  not list, and a page that asks for an install.
- The relay becomes HTTP-aware: requests, streamed answers, WebSockets.
- A directory can be sent to someone without errand: they get the files, and the commands to start
  what is missing.

## Steps

1. `services.json` read by `errand.Static`; `.errand/services`; the two-sided rule.
2. The relay `.errand/svc/<name>/` (HTTP, chunked answers, WebSocket), `X-Errand-Root`, ensure + queue,
   connections counted for the service. Local services only.
3. The guide: a page that asks for a service, with a toy service (a field computed from the
   directory's files), and `?svc.` / `--root` for use without errand.
4. `errand serve install` and `services-installed.json`, with downloads by contents and hash.
5. `there = True` through `forward` (after ADR 0018 step 6).
6. The install button in `errand web`.

## Progress

- 2026-11-20, steps 1-3 done (uncommitted): `errand/web/page_services.py` (`services.json`, the machine's
  services read from `~/.config/errand/services.py` only and again when it changes, `.errand/services`, the two-sided
  rule, the HTTP relay with `X-Errand-Root` percent-encoded, bodies, chunked requests, `101` + WebSocket frames), hooked
  in `web/static.py` (`.errand/` reserved, other methods than GET/HEAD refused on files); `tests/test_page_services.py`
  (3 pass; `test_static_views`, `test_serve` unchanged and green); guide section *A page that asks for a service* in
  `docs/guide/serve.md`. Tried in a browser against an isolated static server: status, a relayed `fetch`, a real
  WebSocket. The host agent must be restarted to serve it.
  Departure: the file's name is fixed, `services.json`; `errand.Static( services = )` was not added (nothing needs
  another name yet).
- 2026-11-20, step 4 done (uncommitted):
  - `errand/install.py`: `plan`, `describe`, `install` (no yes → nothing), `services-installed.json` read by
    `serve.declared` and by the relay after `services.py`. CLI: `errand serve install DIR|VIEW NAME [--yes]`.
  - `.errand/services` gives a missing service's `install.how` as that command, with the view's **id**: the page
    still never sees a local path.
  - Tests in `tests/test_install.py` (4 pass); `test_page_services`, `test_static_views`, `test_serve` still green.
    Guide section *Installing what a page asks for*.
  - Tried for real on a store written by the viewer: Blender found in `/Applications` (no download); `sdot.ao`
    installed, started by the keeper, answered.
  - Departures from the Decision: `downloads` became **`tools`**. Each tool may name `local` candidates, tried before
    any download: a machine that already has the program downloads nothing. A recipe may carry an **`env`**, so that a
    checkout's package stays importable.
