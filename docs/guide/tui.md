# The screen

```bash
errand --tui
```

Here it is, over three places at once — your machine, a container, and a cluster behind ssh and
Slurm. Search a case, press enter, tick the places, and each one gets its own row:

<Term scene="tui" caption="errand --tui, drawn by hand from the screens below: a case ticked on three environments, each with its own stack of layers. The rows fill in as the runs finish; the cluster's output shows the ssh, the allocation and the fetch back." />

**Two pages**, because there are two questions: *what do I run*, and *what came of it*.

No focus to keep track of: one rectangle is active, the arrows drive it, and clicking one selects it;
the wheel scrolls whatever is under the pointer and changes nothing else.

**`tab` walks the rectangles of the page; the function keys are the verbs.** What you type is the
search, on either page — so the letters are spoken for, and a verb belongs on a key nothing else can
claim. `F2` and `F3` are the page before and the page after: two pages, two keys side by side,
nothing to aim at, only a direction.

| | | | |
|---|---|---|---|
| `F1` | these keys | `F5` `F6` | run the last command again · the one under the cursor |
| `F2` `F3` | the page before · after | `F7` `F8` | interrupt what is running · open the file |
| `tab` | the next rectangle | `F9` | read the project again |
| `esc` | clear the search, then leave | `F12` | leave |

The screen has nothing of its own: it writes a command, and it reads
[the output tree](./output). Everything it shows you could have got with `errand` and `ls`.

## cases — what do I run

```text
 [cases]   runs                                      errand · myproject · idle
 find: shp gpu_
 ╭─ cases  3 found ──────────────────────╮╭─ solve ─────────────────────────────╮
 │   solve            bench/shapes.py:42 ││ bench/shapes.py:42                  │
 │   solve_coarse     bench/shapes.py:61 ││ kind: bench                         │
 │   shape_gradient   tests/geometry.py:9││ tags: gpu, slow                     │
 ╰───────────────────────────────────────╯│ needs: gpus=1                       │
                                          │                                     │
                                          │ --n   default 1000                  │
                                          │   how many points                   │
                                          │                                     │
                                          │ last run                            │
                                          │   PASS   gpu   gpu@gpu-box          │
                                          │   12.4s                             │
                                          │   seconds = 12.406                  │
                                          ╰─────────────────────────────────────╯
 type to search · enter runs it · space ticks · tab next box · F3 runs · F1 keys
```

**Typing is the search** — there is no key to press first, because finding one case among three
hundred is what this page is for.

It is the matching an editor's *go to file* does, not an edit distance: the letters have to appear
**in order but not together**, so `tsq` finds `tests/test_shapes.py::quick`. Then they are *scored*
— together beats scattered, the start of a word beats the middle of one, early beats late, short
beats long — and the letters that matched are shown in bold, so a row tells you why it is there.

Several words all have to be found, each possibly in a different place: `shp gpu` is "a case whose
name looks like shp **and** whose tags or file say gpu". Adding a word narrows; you never have to
rewrite what you typed.

**`esc` clears what you typed**, and only then leaves: a filter is the thing you most want gone, and
it should not be the hardest to get rid of. While a search is on, space is a word separator, so the
tick is `ctrl-space` — or a click straight on the box.

With nothing typed, the cases are **a tree of directories and files**, because that is the shape the
work has: a project is a layout before it is a list, and the directory is how you remember where a
case lives. A directory holding one single thing does not cost a row of its own — its name joins its
child's, `bench/gpu/heavy.py` on one line, since a row you can only walk through tells you nothing.

Facing them: everything about the one under the cursor, down to how it went the last time it ran —
read out of [the output tree](./output), so it is there after a restart and after somebody else ran
it.

A file that declares work and will not import costs its own row, marked `!`, with the traceback
facing it. Half a project installed is an ordinary state of affairs; an empty screen is a poor way
of saying so.

## runs — what came of it

```text
 cases   [runs]                                   errand · myproject · running
 find: a command
 ╭─ runs ────────────────────────────────╮╭─ files ─────────────────────────────╮
 │ ▾ errand shapes --n 1e3,5e3       4/8 ││   shape.svg                 12.1 kB │
 │   ok    solve  n=1000  [local]        ││   result.yaml                 512 B │
 │   ok    solve  n=1000  [gpu]          ││   output.txt                 1.2 kB │
 │   ..    solve  n=5000  [local]        │╰─────────────────────────────────────╯
 │ ▸ errand -k bench --fp 32       6 ok  │╭─ output.txt ────────────────────────╮
 │ ▸ errand tests --n 10           1 ok  ││ iteration 41   residual 3.1e-07     │
 ╰───────────────────────────────────────╯│ iteration 42   residual 1.9e-07     │
                                          ╰─────────────────────────────────────╯
```

**Runs and history are one list**, because they are one thing: a command, and what it produced.
Today's is at the top and still moving, yesterday's is three rows down, and both read the same way —
both are read out of the output tree rather than remembered.

Fold one open to see its cases; `F6` runs it again, and `F5` runs the last one again from either
page. **The runs page is searched the same way**, over the commands: a history is only useful once
one line of it can be found. The two searches are separate, so the one you keep on `cases` is still
there when you come back from looking at `runs`.

Facing them: the files a run wrote, and below, the one under the cursor. Text is shown as text —
`output.txt` follows the run as it is written — and anything else says what it is and how big.
Enter or `F8` hands it to the desktop (`xdg-open`, `open`), so an experiment's `.svg` is two keys
from the case that produced it.

## asking where

Enter on a case asks the only question left: where, with which tags, with which parameters — not
*which case*, which was the list you pressed enter in.

```text
 ╭─ run: solve ──────────────────────────────────────────────────────────────────╮
 │ › --env    [x] local   [x] gpu                      two ticks is two runs     │
 │   --fp     [x] 32      [x] 64                    only the ones that say so    │
 │   --n      1000,5000                                     how many points      │
 │   -j       1                                             how many at once     │
 │   --batch  [ ] detach                                 outlives this window    │
 │   ─────────────────────────────────────────────────────────────────────────   │
 │   errand shapes::solve --env local,gpu --fp 32,64 --n 1000,5000               │
 ╰───────────────────────────────────────────────────────────────────────────────╯
   space ticks · ←→ picks · type into a field · enter runs · esc gives up
```

**Every line has the same three columns**: the flag on the left, the field in the middle, what it
means on the right, faded. A thing spread over two lines is a thing you have to assemble before you
can read it, and there is width to spare.

A field shows what you **typed** in bold, or what happens anyway in grey, with a cursor blinking in
it — which is the only way of saying *type here* that nobody has to be taught. Chips are ticked with
space, walked with `←→`, and clicked.

**Ticking two of anything is a [matrix](./matrices).** Two environments, two values of a tag and two
of a parameter are eight runs — for exactly the reason a comma is, and the window builds exactly
that comma. Below the rule, in its own colour, is that command: not a prompt, and nobody is being
asked to type it — it is what is about to happen, said once, so that the day you want it in a script
you already know what to write.

## Output under -j, over ssh, and from yesterday

**Each case's output is read from the file that case is writing**, never from a share of one pipe.
The paths are worked out before the run starts, so the name is known in advance — which is why it
reads the same under `-j 8`, for a run on another machine, and for a job submitted yesterday.

Tick `detach`, close the window, open it tomorrow: the state was never in the screen. A run started
*from* the screen belongs to the screen, so leaving is refused while one is going —
[`detach`](./detached) is how work is meant to outlive a window.

## All the keys

| | |
|---|---|
| `F1`…`F12` | one per thing to do — see the table at the top |
| `tab` | the next rectangle of this page |
| typing | the search, on either page |
| arrows, click, wheel | move · choose and activate · scroll what is under the pointer |
| space | tick a case, or fold — `ctrl-space` while a search is on |
| enter | cases: ask where · runs: its files · files: open it |
| `esc` | clear the search, then leave |
| `F9`, `F1`, `F12` | read the project again · the keys · leave |

## Next

[Configuration](./configuration).
