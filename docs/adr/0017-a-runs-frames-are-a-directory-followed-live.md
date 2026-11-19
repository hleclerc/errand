---
status: proposed
date: 2026-11-19
---

# A run's frames are a directory, followed live and opened by its viewer

An otrec run on lmo writes an HTML page of its steps: a frame every N iterations (the cloud of balls,
their fields such as the dissonance), an FBP image under them, the curves (loss, metrics) in windows.
The page is `sdot.viz.Visualizer`'s: hand-written WebGL, one file, every frame embedded as a
compressed blob (`compact = True`: 16-bit positions and fields, byte shuffle, deflate). Pages reached
180 MB. Compression brought them down about 8 times. A foam run, 10 000 balls and about 300 frames, still
weighs tens of MB, and:

- **the whole file must come back from lmo** before anything shows (`errand.view` brings it back as
  soon as it is named, ADR 0010 amended, but whole);
- **the browser parses and inflates it all at once**, every frame, base64 included (+33 %);
- **the Recorder keeps every frame in memory** until `write_html` at the end: nothing shows while the
  run goes on, and a run that dies leaves no page;
- **the page is written once**: to look at a run while it goes, it would have to be written again,
  whole, again and again.

What a person looks at is one frame at a time, and the curves. Seen from a distance, this is an
application: a document (`xyz.sviz`, a directory), opened by a viewer that reads the frame it shows,
and that can still produce a self-contained page, a GIF, a ParaView series afterwards.

It spans three projects. sdot owns the format and the viewer (`sviz`), otrec writes it, errand brings
the directory back as it grows and knows, by declared rules, what opens it. errand knows nothing of
frames. Running the viewer's server is a service in the sense of ADR 0018.

Settled in a grill on 2026-11-19 (`grill/serve/`). A first version of this ADR, the same day, served
the files of the run from lmo through a capability route of `errand web` (`/s/<cap>/…`); that route is
dropped: errand brings the directory back live, and the viewer reads it here.

## Decision

### 1. The data: a `.sviz` directory of chunks (sdot)

    foam.sviz/
        index.html            the page with no data in it (the viewer, ~100 KB): any static server opens it
        manifest.json         the scene: title, dim, bounds, axes, layers, colours, fields (name, range per
                              frame), images, curves, the list of frames (axis values, file, size, nb of
                              points), `complete`. Rewritten whole, atomically, after a frame (at most once a
                              second, and at the end). The only file that ever changes
        base-<hash>.bin       what every frame draws: shared primitives (the truth's outline), images
                              (the FBP layer). Named by its contents: changed, it is a new file
        frames/000123.bin     one frame. Written once (a temporary name, then renamed), never changed

**A chunk** (`.bin`) is `u32 length | JSON header | blobs`. The header lists the arrays:
`{ name, dtype, shape, k, at, len, lo?, step? }`. A blob is an array's bytes shuffled, then deflated:
exactly what `Visualizer._pack` does today, so the browser inflates it with its own
`DecompressionStream( "deflate" )`. `lo`, `step`: the array holds 16-bit codes of floats (`compact`),
per column for `[ n, d ]`, 65535 for NaN, as today. A chunk holds every kind of primitive the
Visualizer has (points, radii, matrices, colours, layers, fields, edges, polygons, polytopes); its
indices refer to its own pool of positions, so a chunk is drawn with no other but the base.

**Why a file per frame**, and not one HDF5, an npz per frame, zarr, or one file read by ranges:

- the number of shapes changes from frame to frame (`split_items`, `remove_isolated`): the data is
  ragged, one table per frame, not an array with a time axis (zarr, an HDF5 dataset);
- the browser reads it with nothing but the platform: no h5wasm, no zarr library, no zip parser.
  The page stays without dependencies, as the Visualizer's page is now;
- a file written once is safe to read while the run writes the next one, safe to cache by name,
  and crosses a sync as one new file (ADR 0006): a growing single file would be sent again;
- `python -m http.server` does not answer `Range` requests: a single file read by ranges would need a
  server of our own even to test;
- 300 files are nothing to a file system. A run of 30 000 frames would be another matter; then frames
  are grouped by 100 into a file with an index in the manifest. Not now.

An npz per frame was the closest option: a standard, read by numpy. It does not shuffle bytes (worse
compression of 16-bit codes), has no place for `lo` / `step`, and needs a zip parser in the page. The
chunk is read in Python by `sdot.viz.read_scene( path ).frame( i )` (20 lines, numpy only), which gives
the arrays back as float32.

Measured with the prototype (`sdot-ffi/prototypes/viz_store/`, synthetic descent, 10 000 balls, 2 fields,
300 frames): **24 MB on disk, 80 kB a frame** (positions 40 kB, each field 20 kB: 16-bit codes do not
compress further, about 2 bytes a value). Writing a frame costs under 8 ms (300 frames in 2.3 s,
comparisons included). In the browser, over `http.server` on this machine, a frame is fetched, inflated
and decoded in **68 ms**; the page holds the frames it has seen, not 300. Two encodings were tried for
later: the Morton order of the first frame gives nothing; positions as a difference to the previous
frame (a key frame every 30) save 25 % overall. Neither is in this decision.

### 2. Writing it as the run goes (sdot, otrec)

The Visualizer gets a **store mode**: the same calls, but a frame is written when the next one opens,
and forgotten.

```python
viz = Visualizer( title = "foam", frame_axis = "iteration", compact = True, field = "dissonance",
                  store = "out/foam.sviz" )            # writes index.html and the manifest at once
viz.add_layer( "fbp", visible = False )
viz.add_image( fbp, lo, hi, layer = "fbp" )           # into the base: a new base-<hash>.bin
viz.add_edges( p, e, shared = True, layer = "truth" ) #   ( shared primitives may come at any time )
viz.new_frame( it )                                   # the previous frame is written, its arrays released
viz.add_points( x, radius = r, fields = { ... } )
viz.clear_curves().add_curve( "loss", y, x, log_y = True )   # the curves, given again whole as they grow
viz.close()                                           # the last frame, `complete: true`
```

`on_frame = callable` is called after each frame written (and after `close`): it is where a run says
its view again (section 4). Without `store`, the Visualizer is what it is today, and `write_html`
writes one self-contained page. The page is the same page in both cases (section 3).

**otrec**: `Recorder( every = 10, store = path )` creates the Visualizer in store mode when the first
stage begins, writes each frame as it is taken, and keeps none in memory. The truth and the images go
in when they are known (`Recorder.set_truth`, `Recorder.add_image`, or still `write_html`'s arguments
at the end). The curves (losses, metrics, blur, number of shapes, median radius) are replaced in the
manifest at each frame ( `clear_curves`, then `add_curve` ): they are live. `write_html( path, … )` stays: with a store, it is `close()`
then an export; without one, as today. The library does not import errand: the experiment passes
`on_frame = lambda: errand.view( store )`.

### 3. The page: the Visualizer's, reading chunks lazily (sdot)

One page, one code path, two sources of chunks:

- **fetched**: `index.html` beside the manifest reads `manifest.json`, then `base-….bin`, then the
  frame it shows, by relative URLs. It needs a server (a page opened as `file://` cannot `fetch`, and
  says what to run);
- **inlined**: the self-contained export holds the same manifest and the same chunks as blobs, as it
  holds blobs today, and the loader resolves a chunk's name in that map instead of fetching it.

What changes in the page's script:

- the global lists (`POS`, `PNT_V`, `FR_PNT`…) become per chunk: `buildScene` draws the base chunk
  and the shown frame's chunk, each with its own pool, instead of ranges of one pool;
- `setFrame` becomes asynchronous: the shown frame stays until the asked one is decoded, and the last
  asked wins. Decoded frames are kept in an LRU bounded in bytes (256 MB). The neighbours are
  fetched ahead (2 each side; 6 ahead while playing, in the direction of play);
- what needed every frame reads the manifest instead: the range of a field "over all the frames"
  from the per-frame ranges, the frame bar and the axes' grid from the frame list. The morph waits
  for its second frame; the GIF export loads frame after frame;
- **while `complete` is false**, the page reads the manifest again every 2 s: new frames appear on
  the bar, the curves grow, and a page that shows the last frame follows the end;
- everything else (layers, fields, curve windows, theme, navigation, slices) is unchanged.

### 4. sviz: the viewer as a command (sdot)

Installed with sdot (a console script):

    sviz open xyz.sviz [--url]          the viewer's server ensured, the directory registered, the browser
                                        opened; --url prints the URL instead of opening it
    sviz export xyz.sviz --html out.html [--every k] [--frames a:b] [--max-mb N]
                                        ONE self-contained page, to send to someone (a subset if asked)
    sviz export xyz.sviz --vtk out/     the ParaView series ( `write_vtk` )
    sviz serve                          the server, in the foreground

- **One server per user**, serving every directory opened: one port, one URL per directory,
  `http://127.0.0.1:<port>/<token>/<id>/`. The token is in the path, as `errand web` does: on a
  shared machine, other accounts reach 127.0.0.1 too. Python stdlib only: static files, nothing
  computed. It never runs inside an errand agent's process.
- **With errand installed**, `sviz open` runs `errand serve --ensure sviz -- python -m sdot.viz.server
  {port}` (ADR 0018): errand owns it, says it in `errand status`, stops it after `--idle` without a
  connection. **Without errand**, `sviz open` starts the same server detached, and the server stops
  itself after the same idle time. sdot does not depend on errand.
- **The viewer is the installed one**: `sviz open` serves its own `index.html` beside the directory's
  data, not the copy inside the directory (which may be older; it is there for any static server).
- **The GIF (and a video)** stay a button of the page, which renders them already. A command-line
  `sviz export --gif` would need a headless browser: later, if it is needed.
- `sviz open --there` (the server on the machine that holds the run, reached through
  `errand serve forward`, ADR 0018) comes later, for runs too large to bring back.
- A Finder that opens `xyz.sviz` on a double-click needs a small macOS application declaring the
  extension as a package: later.

**Where ParaView's line is.** The viewer shows, hides, colours and plays what was written. It has no
filters, no pipeline, no readers of other formats: anything derived is computed in Python when the
frame is written. ParaView stays the way out (`--vtk`).

### 5. A run's page, its outputs, and what opens them (errand)

Settled in the grill's rounds 4 and 5 (`grill/serve/`, 2026-11-19), replacing the declared openers of the
first version.

**The run's link, said at the start.** The head line of a run in the terminal carries the address of its
page in `errand web` (the `/job?key=…` page that exists), local or remote run alike: it is the page of
*my* `errand web`, which reads remote runs through the agents.

    ▸ foam (lmo-torch · gpu 0)  …  ↗ http://127.0.0.1:20501/job?key=…

The link holds no secret: the cookie of `errand web` lasts 30 days, renewed at each visit (today it
is a session cookie, lost when the browser restarts). `errand run --open` (`-O`) opens the page at the
start: a tab per run up to 4, beyond that the main page. A user default: `errand.configure( open = True )`.

**The list on the left.** The run's page keeps its layout (list on the left, preview on the right). Views
(`errand.view`) and outputs merge into one list; the rich outputs (html, a view with an opener, images,
pdf) come first, in the order they appeared. A `.sviz` is one line, with its state (`331 frames`,
`running` while its manifest is not `complete`), never the list of its chunks. A click shows it on the
right, a double-click opens it in a tab of its own.

**A view can be a directory.** `errand.view( "foam.sviz" )`: the journal line is the same
(`{"t": …, "view": "foam.sviz"}`, ADR 0010); the mark carries `"dir": true`, from the run's side,
which can see it. On the driving side (`cli/views.py`, `Views`), **naming it again brings what
changed**: the files missing here, and those whose size or date differ (the manifest), into the
project here where the run's own coming back would put them. Nothing is deleted here. The latest state
always comes, never one transfer per call. **The manifest comes last**, after the files it lists
(generic rule: the files of a directory view in order of date, the last written last). errand does not
watch the directory itself: the run says when it changed (`on_frame`).

**What opens a view: said by its producer.** `errand.view( path, open = … )` takes an opener object
that says everything; nothing is declared by the user, on any machine:

```python
# sdot, when errand is importable ( as `announce` )
errand.view( store, open = errand.Static( "index.html" ) )
```

- **`errand.Static( index )`**: the view is a directory that carries its own page; it is served as it
  is. Nothing runs on the driving machine, no environment is built, and the page is the one written
  with the data, so **of the same version** (sdot's editable checkouts raise no question). sdot takes
  this one.
- **`errand.Opener( command, env = None, name = None )`**, later, at its first real user: a command
  (a list, `{path}` = the local copy) that prints a URL and returns, run in an errand environment
  (`Uv`, `Micromamba`, `Apptainer`…, a `Node` tomorrow) built **in errand's cache** on the driving
  machine, once per description (its stamp). The object travels in JSON in the journal line. A
  package installed editable says `source = <its directory>`; errand turns it into the local path
  when it lies in a tree errand pushes (`~/Projects-rsync/sdot-ffi` on lmo → `~/Projects/sdot-ffi`),
  and installs that copy editable; otherwise `package==version`. The store's `format` protects the
  rest: a viewer too old says so.
- **No confirmation.** One opener: it opens. A list (`open = [ a, b ]`): the first by default, the
  others from a right-click on the line in the run's page.

**Static views are served by a second server of the host agent**, beside `errand web`: its own fixed
port, its own token **in the path** (`http://127.0.0.1:<port>/<token>/<id>/`), files only, read-only,
only under the directories that a `Static` view declared (the run's local copy). Not inside `errand
web`: its preview is a sandboxed iframe (an opaque origin, which cannot read its neighbour files with
the cookie), and `allow-same-origin` would let a run's page call `POST /act`. On another origin with the
token in its path, the page needs no cookie and reaches nothing of errand.

**Where the URL shows.** In the run's page, the preview is an iframe on that URL. In the terminal, the
view is said `↗ http://127.0.0.1:…/<token>/<id>/` (an `index.html` read as `file://` cannot fetch its
neighbours), once the first frame has come back. The self-contained page of the end (`foam.html`)
stays an output said as `file://`, which a ctrl+click opens.

`sviz` stays: for whoever runs without errand (`sviz open`), and for `export`.

## Considered options

- **Keep one page, compress harder.** Delta coding (−25 %, measured), fewer frames, 8-bit fields. The
  page still travels whole and is parsed whole, and still exists only at the end. Kept for the export.
- **One HDF5 file written by the run.** `h5py` on the run's side, h5wasm (several MB, from a CDN) in
  the page, SWMR to read while it is written, a growing file resent by every sync.
- **zarr.** The directory-of-chunks idea, standardised. But the frames are ragged, a writer and a
  reader library are needed, and a scene's attributes (layers, colours, curves) fit a JSON manifest.
- **Serve the files where they are, through `errand web` (`/s/<cap>/…`)**, the first version of this
  ADR: only the frames looked at cross. It needs a capability route, a sandboxed page with CORS, and
  a viewer that depends on errand to be reached. Bringing the directory back live is simpler, works
  after the run and offline, and keeps the viewer a local program. Serving from there comes back,
  generically, with `forward` (ADR 0018) and `sviz open --there`.
- **The directory names its own opener** (a file inside), or **the user declares openers by name**
  (`errand.openers[ "*.sviz" ] = "sviz open --url {path}"`, the first version). The second needs a
  line per user and machine, and errand runs in a Python without sdot: the line would also have to name
  an environment. The producer's object (`errand.Static`, `errand.Opener`) says it all. A run choosing
  what runs here: `Static` runs nothing here; for `Opener`, it is the user's own code that chose it
  (rounds 4–5).
- **Static views served inside `errand web`**: same origin as its actions, and a sandboxed iframe
  cannot read its neighbours with the cookie.
- **errand serves any directory with an `index.html`** in `errand web`. It works without sviz, but
  makes `errand web` a second viewer server. Not now.
- **Rerun, ParaView.** ParaView has the generic data model, filters and remote rendering we do not
  want. Rerun (log points, scalars on a timeline, live, a viewer app) is close in spirit; it has
  neither ellipses in 2D, nor polytopes, nor n-D slices, nor a self-contained page for the docs.

## Consequences

- Nothing is rsynced at the end to be looked at: the directory comes back as it grows, one small file
  a frame, and the viewer reads here what is here.
- A run is looked at while it goes, from the first frame; a run that dies leaves a store up to its
  last frame. The Recorder's memory no longer grows with the frames.
- Everything comes back, not only what is looked at (24 MB for the foam run). For runs where that is
  too much, `forward` (ADR 0018).
- Sharing is an explicit step (`sviz export --html`), no longer the default output.
- A page opened as `file://` no longer works for a store, only for an export; it says what to run.
- A user-level file (`~/.config/errand/services.py`) is read by errand for the first time (ADR 0018).
- A run's address is said at its start, and its page shows its views as they come: the terminal's
  ctrl+click and the browser lead to the same place.

## Steps

1. **sdot: the format.** Chunks, `Visualizer( store = , on_frame = )`, `close()`, `read_scene()`; a
   test that a store's frames give back what the self-contained page holds today.
2. **sdot: the page reads chunks.** Per-chunk pools, asynchronous `setFrame`, LRU, prefetch, ranges and
   bar from the manifest, morph and GIF asynchronous, the manifest polled. `write_html` builds the
   inlined page from the same chunks: the docs' examples must look the same.
3. **sdot: `sviz`** `open` (detached server, no errand yet), `export --html`, `export --vtk`, `serve`.
4. **otrec: `Recorder( store = )`**; `exp_2d_real.py` writes `foam.sviz` and passes `on_frame`.
5. **errand, in this order** (rounds 4–5): (a) the run's link on its head line, the 30-day cookie,
   `--open`; (b) the list on the left (rich outputs first, a `.sviz` on one line with its state);
   (c) directory views (the mark's `dir`, what changed brought back, the manifest last) and otrec's
   `on_frame`; (d) `errand.Static`, the second server, the URL in the page (iframe) and in the
   terminal, sdot declaring its opener. Tried for real: a foam run on lmo, watched while it goes.
6. Later: `errand.Opener` (command, environment, sources) at its first user; with ADR 0018, `sviz open`
   through `errand serve --ensure`, then `sviz open --there` through `forward`.
7. Later, if measured worth it: positions as differences to a key frame; frames grouped into files for
   very long runs; `sviz export --gif`; the macOS package.

## Prototype

`sdot-ffi/prototypes/viz_store/` (new files, nothing else touched; written before the extension was
settled, its directories are `*.scene`): `store.py` (chunks, `SceneStore` writer, `SceneReader`),
`viewer.html` (a 2D-only page: lazy frames, LRU, prefetch, field colours over the manifest's ranges,
the FBP image from the base chunk, the manifest polled while the run goes), `demo.py` (a synthetic
descent, sizes, the encodings compared). Tried in a browser over `python -m http.server`: frames
fetched on demand, and a store written slowly (one frame each 0.4 s) grew on the page's bar while it
was open.

## Step 1 done, 2026-11-19

`sdot/viz/store.py` (new): chunks (`chunk_bytes`, `read_chunk`), `scene_arrays` (a frame of a Visualizer
as a chunk's arrays, on a pool of its own, the shared primitives first), `StoreWriter`, `read_scene`
(`Scene`: `len`, `value( i )`, `base()`, `frame( i )`). `Visualizer( store = , on_frame = )`: a frame is
written by the next `new_frame` and forgotten, `close()` writes the last; a shared primitive goes to a
base scene that shares the tables of colours, layers and images, written when it changes; `clear_curves()`;
`to_html` refuses a store. With `compact`, every float array but the polytopes' is on 16 bits (radii and
matrices too, which the page keeps in float32).

As on the page, a shared primitive is drawn in **every** frame, even one added after some frames were
written: the frames read the manifest's last base. `index.html` is not written yet: it comes with the
page (step 2).

Tested (`sdot-ffi/tests/test_viz_store.py`): the frames of a store give back the page's (points,
radii, ellipses, colours, layers, fields, edges, faces, polytopes, an image, a shared point added late),
in float32 and in 16 bits; a store holds only the frame being built; `on_frame` is called; the curves.
`test_Visualizer.py` still passes.

## Step 2 done, 2026-11-19

One template for both pages. `to_html` inlines the data as before; `store_page( title )` (written as
`index.html` when a store opens) is the same template where each placeholder reads a member of `STORE`
(`decPos(STORE.POS)` for `decPos("__POS__")`). The page's loader, in a store, reads the manifest, the
base and the last frame (waiting, with a note, for a run that has written none), joins base and frame
into the arrays of the self-contained page (the base first, as the shared primitives), and runs the main
script unchanged in its rendering. What changes with the frame shown is swapped by `useScene`; the frames'
ranges then say "the shared ones, then the rest" for the frame shown.

- `setFrame` updates the bar and the curve cursors at once, and draws when the chunk is there: at once
  from the cache, else on arrival. The next three frames and the previous one are fetched ahead. Cache of
  256 MB, the least recently shown dropped first.
- Morph and play wait for the next chunk (a tick is skipped); the GIF awaits each frame.
- The manifest is asked again every second until `complete`: new frames stretch the bar (rows made again
  only when the set of shown axes changes), the view follows them when it shows the last frame and does
  not play; a new base empties the cache; curves given again are redrawn where the user left their
  windows.
- A field's range "over all the frames" is the union of the frames' [min, max] from the manifest, not the
  1 %–99 % quantiles of the self-contained page.
- Images and the bounds come from the first read: an image added later, or bounds that grow, need a
  reload. The manifest gains `options.bg` (the background resolved per theme).

`write_html` of a store (the self-contained export) is not done: it is `sviz export --html` (step 3).
A store is read through a server only (`fetch` does not read `file://`).

Checked in a browser (`sdot-ffi/prototypes/viz_store/store_demo.py`): a 2D run (image, layer, shared
outline, points with two fields, a polytope, a log curve, morph, `compact`) and a 3D cloud draw the same
as their self-contained pages; frame changes, fields over the frame and over all frames, play with morph
at the same pace; a run writing a frame every 0.5 s followed live (bar, curve, last frame followed, a
frame chosen kept). Tests: `test_viz_store.py` (4, with the page of a store: no placeholder left) and
`test_Visualizer.py` pass.

## Step 3 done, 2026-11-19

`sdot/viz/sviz.py` (new), the console script `sviz = "sdot.viz.sviz:main"` in sdot's `pyproject.toml`:

- `sviz open xyz.sviz [--url] [--idle 10m]`: registers the directory in `~/.cache/sdot/sviz/dirs.json`
  (id = its name and a hash of its absolute path), ensures the server (under a lock; detached:
  `start_new_session`, or DETACHED_PROCESS on Windows; log in `server.log`), prints
  `http://127.0.0.1:<port>/<token>/<id>/` and opens it. The token (`token`, mode 600) and the port
  (`last-port`, when free) are kept: a URL stays valid from one start to the next.
- `sviz serve [--port P] [--idle T]`: stdlib `ThreadingHTTPServer` on 127.0.0.1. `index.html` is the
  installed `store_page`, made at each request; the other files are read from the directory (a path
  leaving it is a 404), all `no-store`; `/<token>/ping` says `sviz`. `dirs.json` is read at each request,
  so `open` never talks to the server. It stops after `idle` without a request; a store page asks for
  its manifest (`HEAD`) every minute, so a tab kept open keeps the server.
- `sviz stop`: SIGTERM; the server removes its `server.json` as on idle.
- `sviz export xyz.sviz --html out.html [--every k] [--frames a:b] [--max-mb N]`: `store_page( title,
  files = )` inlines the manifest (frames chosen, `complete`) and their chunks in base64; the loader
  reads them there instead of fetching. `--max-mb` keeps one frame out of k, the last always, the page
  itself counted. A store page opened as `file://` says to use `sviz open`.
- `sviz export xyz.sviz --vtk out/name`: `write_vtk` unchanged, given an adapter over the store
  (`frame( i )` joins the base and frame i, `positions` is their pool).

`write_html` of a Visualizer stays the page as before (the docs' examples unchanged); the inlined store
is the export of a store only.

Not done: `errand serve --ensure` (step 6); a test of the detached start under errand's runner (tried by
hand on the Mac: open, same URL after `stop` and `open` again).

Tests (`sdot-ffi/tests/test_sviz.py`): export --html (frames chosen, size cap, files inlined, no
placeholder left); export --vtk (as many points and cells per frame as the Visualizer's own series);
the server (page, manifest, frame bytes; wrong token, unknown id, `..` and `%2e%2e`: 404; it stops when
idle and cleans its state). In a browser: an export of 16 frames out of 60 under 1 MB, and a 3D store
through `sviz open`.

## Step 4 done, 2026-11-19

otrec's `Recorder( store = , page = , on_frame = )`: each frame is drawn in a `Visualizer( store = )` as it
is recorded, and forgotten; `frames` keeps what the curves need (iteration, stage, sigma, loss, metrics,
`nb_points`, `median_radius`). `page` holds the options `write_html` took at the end (title, truth,
images, field, curves, fps), now known at the start; the field shown at the start is set once a frame
has it. The curves are given again after each frame (`clear_curves`), and by `close()`, which writes
the last frame (the losses after it included). `write_html` builds the same page as before from the
same pieces (`_page_viz`, `_draw`, `_curves`), and refuses a recorder with a store.

`experiments/exp_2d_real.py` (foam, pencil, sandstone, bamboo) writes `<name>.sviz` instead of
`<name>.html`: `sviz open foam.sviz`, or `sviz export foam.sviz --html foam.html`. `on_frame` is not
passed yet: `errand.view` of a directory is step 5.

Tested (`otrec/tests/test_recorder_store.py`, `--env torch`): the frames of a store give back those
kept in memory (points, ellipses), its curves are the page's, the truth and the image are in the base,
`write_html` refuses a store. `test_reconstruction.py` still passes.

The examples keep their page: `Recorder.close( html = )` writes the self-contained page of the store
too (`sviz export --html`, its `OUTPUT: file://` link said). A real foam run on lmo (2026-11-19,
`--env lmo-torch -o`, 10 min 11 s): 331 frames, `foam.sviz` 25 MB, `foam.html` 32 MB, brought back at
the end (342 files); `sviz open` shows it, an uncached frame in 16 ms.
