# Tutorials

Four walkthroughs. Each one adds a leg, and each one is a directory you can `cd` into:
the first three ship with errand, in [`examples/`](https://github.com/hleclerc/errand/tree/main/examples).

**Which first?** Start where your project is:

- a **pytest / Catch2 / cargo** project → [3 · Adopt an existing suite](./adopt-a-suite)
- you want to see the **layers** (containers, ssh, Slurm) at work → [2 · Four environments](./environments)
- **no framework**, work to write → [1 · errand's own entries](./first-entry)

| | what it shows | needs |
|---|---|---|
| [1 · errand's own entries](./first-entry) | no configuration at all: entries, parameters, matrices, the output tree | nothing but `errand` |
| [2 · Four environments](./environments) | environments as layer stacks, tags, building them, running in several at once, `--batch` | reading, mostly |
| [3 · Adopt an existing suite](./adopt-a-suite) | a pytest / Catch2 / cargo project adopted in three lines, unmodified | a compiler, cargo |
| [4 · Numbers over two machines](./two-machines) | the whole thing end to end: numbers taken in two places, compared | an ssh host |

The first and the third need nothing but their own toolchain. Examples two and four name micromamba environments, Apptainer images, ssh
hosts and a Slurm partition that do not exist on your machine — they are there to be read and
adapted, and `errand --envs` will tell you honestly that none of them is built.

::: tip Reading order, if you are in a hurry
Read [Start from what you have](/guide/start). Then [Environments](/guide/environments) and
[Where the output goes](/guide/output), which are the two ideas everything else is built on.
:::
