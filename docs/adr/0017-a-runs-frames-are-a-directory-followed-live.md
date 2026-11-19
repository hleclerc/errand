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

### 5. A directory view, followed live (errand)

errand learns two things, neither about frames.

**A view can be a directory.** `errand.view( "out/foam.sviz" )`: the journal line is the same
(`{"t": …, "view": "out/foam.sviz"}`, ADR 0010); the mark carries `"dir": true`, from the run's side,
which can see it. On the driving side (`cli/views.py`, `Views`), **naming it again brings what
changed**: the files missing here, and those whose size or date differ (the manifest), into the
project here where the run's own coming back would put them. Nothing is deleted here. The latest state
always comes, never one transfer per call, as for a file. **The manifest comes last**, after the files
it lists, so that a page never reads a frame it announces that is not here yet (generic rule: the
files of a directory view in order of date, so the last written last). errand does not watch the
directory itself: the run says when it changed (`on_frame`).

**Openers: what opens a view, by declared rules.** errand finds the viewer of a view by its name,
never by something inside it (a run, maybe on another machine, must not pick a command run here):

```python
# ~/.config/errand/services.py, or a project file ( ADR 0018 )
errand.openers[ "*.sviz" ] = "sviz open --url {path}"
```

The command is run on the driving side with the local path; it prints a URL. errand then says that
URL (`OUTPUT: http://127.0.0.1:…/`) instead of the path, once per view, in the run's block (ADR 0016),
and `errand web` shows an "open" button for it. A view with no opener is said as a path, as now. sdot's
documentation gives the line to add; `sviz` can print it (`sviz opener`).

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
- **The directory names its own opener** (a file inside). A run would choose what is executed here.
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

## Steps

1. **sdot: the format.** Chunks, `Visualizer( store = , on_frame = )`, `close()`, `read_scene()`; a
   test that a store's frames give back what the self-contained page holds today.
2. **sdot: the page reads chunks.** Per-chunk pools, asynchronous `setFrame`, LRU, prefetch, ranges and
   bar from the manifest, morph and GIF asynchronous, the manifest polled. `write_html` builds the
   inlined page from the same chunks: the docs' examples must look the same.
3. **sdot: `sviz`** `open` (detached server, no errand yet), `export --html`, `export --vtk`, `serve`.
4. **otrec: `Recorder( store = )`**; `exp_2d_real.py` writes `foam.sviz` and passes `on_frame`.
5. **errand: directory views** (the mark's `dir`, what changed brought back, the manifest last) and
   **openers** (`errand.openers`, the URL said, the button in `errand web`). Tried for real: a foam
   run on lmo, watched while it goes.
6. With ADR 0018: `sviz open` through `errand serve --ensure`; then `sviz open --there` through `forward`.
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
