# Every run, live in the browser

```bash
errand run -O --env lmo python train.py     # -O, --open: the run's page opens in the browser
errand web                                  # every run of every machine, as a page
```

Each run has a page, and it is live: the console as the program writes it, its step and progress
bar, its curves, its images and HTML pages redrawn as the run writes them, wherever it runs. No
`scp` to look at a figure, no `tail -f` over ssh: the page follows the run, and stays once it ends.

`errand web` is the same for everything: what runs on every machine you sent work to, what waits,
every run done as a tree with a table of its parameters and results, the machines' gauges, the
library caches they hold. Pick a run, and its page is on the right.

Neither one runs anything itself. What runs is owned by the agents over there: close the tab, nothing
stops. Nothing is asked again and again either: the agents say what changes, when it changes, and the
page shows it at once.

## A run's page

`errand run` prints, under each run's head, the address of its page; `-O` ( `--open` ) opens it
in the browser by itself, a tab per run for the first few, then the main page:

```text
  ▸ train  lin  lmo
    ↗ http://127.0.0.1:20501/r/3f2a9c1e
```

What it shows, as it happens:

- **the console**, stdout and stderr, as the program writes them;
- **where the run is**: the text and bar of its last [step](./steps), the estimated end, how long
  since the last step ( a run that hangs shows ), a curve per value it reports;
- **its views**: the files it names with [`errand.view`](./steps#view-a-file-that-evolves), an image,
  an SVG, an HTML page, brought back from the machine that runs it as soon as they change, and shown
  in place. A directory that carries its own page ( `errand.Static` ) is served as it is, while the
  run is still writing it;
- **its files** once it ends: `output.txt`, `result.yaml`, what it wrote in its directory.

```python
for it in range( n_iter ):
    ...
    errand.step( f"iteration {it}", done = it / n_iter, loss = loss )
    if it % 50 == 0:
        plot_mesh( mesh, "mesh.png" )
        errand.view( "mesh.png", title = "current mesh" )    # on the page a moment later
```

The address holds no secret, and works for a run on any machine: the page is served by this
machine's agent, which asks the others.

## Runs

Tab `1`. What runs and what waits on top, then every run done, as a tree:

```text
otrec/
  experiments/exp_2d_real.py
    foam
        n      nb_splits reduction | loss   status  when     runs
        10000  1         1         | 0.005  PASS    12:13    34
        2000   1         8         | 0.002  PASS    12:14    1
          ▸ its runs: date, machine, env, status, duration
sdot-ffi/
  …
```

- **The tree** is the path of the file from the project's root, the file, the entry, then its
  **parameter sets**: the runs whose parameters are equal, whatever machine or environment.
- **The table** has a column per parameter, then the results the run declared, the status and date
  of the last run, how many runs. `s` sorts by the next column.
- **Removing**: `d` removes the runs under the row, `D` keeps only the latest of each set and
  environment, after a confirmation. `⇧↑ ⇧↓` chooses several rows.
- **Runs elsewhere**: the list is this machine's record ( every run started from here has its
  directory here ). `c` checks the other machines for runs not here ( `◇` ), `b` brings one back.

## The detail

Right of the list, the row chosen: its run's page ( above ), its facts, its views and outputs. The
output chosen is shown below them, text, image or HTML, and opens whole in a tab of its own.
A row can also be killed, through every layer, once confirmed.

## Machines

Tab `2`. Each machine of the ledger: its gauges ( CPUs, memory, cards ), measured only while shown,
what holds it, its VMs and guests, what is kept warm. `a` switches a machine's gauges off or on ( what
runs there is followed all the same ), or watches a dormant one; `r` gives it a
name, `f` forgets it until work is sent there again.

## Caches

Tab `3`. The [library caches](./caching#a-library-s-caches-kept-tidy) of every machine: per cache,
a row per place, then its entries merged across places, with their size and when they last served.

- `i` removes the dead entries, `u` those unused for n days ( `n` sets n, 30 by default ), of one
  place or, on a cache's row, of every place;
- `d` removes the entry under the cursor where it is dead or unused, `D` everywhere it is;
- `h` has the place's machine hold the directory: its agent purges it daily;
- `v` shows every entry, or only the dead and unused.

## From another machine

`errand web` opens the page in the browser and prints its address. It is served by this machine's
host agent, on `127.0.0.1` only, one per user and machine. The port is open to every user of the
machine, so the page is served only to who holds a token: `errand web` opens it with a code used once,
then a cookie keeps it. `errand web token` prints the token, for another browser.

From another machine, a tunnel:

```bash
ssh -L 20501:localhost:20501 lmo     # then errand web there gives the URL
```

## The same in the terminal: errand tui

```bash
errand tui
```

The same tabs, the same tree and detail, in curses, for a session with no browser. `w` opens the
run under the cursor in the browser.

| key | |
|---|---|
| `1` `2` `3` | runs, machines, caches |
| `↑ ↓` `pgup pgdn` | move · `→ ←` unfold, fold · `tab` the list or the detail |
| `enter` | open an output as this machine opens it · `e` in `$EDITOR` · `o` in `$PAGER` · `w` the run's page |
| `/` | filter: machine, project, command, state · `p` this project or all |
| `k` | kill, once confirmed · `x` a shell on its machine, where it works |
| `R` | ask every machine again now |
| `?` | every key · `q` leave, nothing stops |

The page takes the same keys, with buttons beside them.

## Next

[What is running](./status) · [Where a run is: steps](./steps) · [Data and results, computed once](./caching)
