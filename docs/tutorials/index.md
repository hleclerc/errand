# Tutorials

Four walkthroughs, in order. Each one adds a leg, and each one is a directory you can `cd` into:
the first three ship with errand, in [`examples/`](https://github.com/hleclerc/errand/tree/main/examples).

| | what it shows | needs |
|---|---|---|
| [1 · Your first entry](./first-entry) | no configuration at all: entries, parameters, matrices, the output tree | nothing but `errand` |
| [2 · Four environments](./environments) | environments as layer stacks, tags, building them, running in several at once, `--batch` | reading, mostly |
| [3 · Adopt an existing suite](./adopt-a-suite) | a pytest / Catch2 / cargo project adopted in three lines, unmodified | a compiler, cargo |
| [4 · A bench over two machines](./two-machines) | the whole thing end to end: a number taken in two places, compared | an ssh host |

The first needs nothing. Examples two and four name micromamba environments, Apptainer images, ssh
hosts and a Slurm partition that do not exist on your machine — they are there to be read and
adapted, and `errand --envs` will tell you honestly that none of them is built.

::: tip Reading order, if you are in a hurry
Do tutorial 1. Then read [Environments](/guide/environments) and
[Where the output goes](/guide/output), which are the two ideas everything else is built on.
:::
