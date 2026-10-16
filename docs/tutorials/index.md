# Tutorials

Four walkthroughs. Each one adds a leg, and each one is a directory you can `cd` into:
the first three ship with errand, in [`examples/`](https://github.com/hleclerc/errand/tree/main/examples).

**Which first?** Start where your project is:

- you want to see the **layers** (containers, ssh, Slurm) at work → [1 · Four environments](./environments)
- a **pytest / Catch2 / cargo** project → [2 · Adopt an existing suite](./adopt-a-suite)
- **no framework**, work to write with errand's own entries → [4 · errand's own entries](./first-entry)

| | what it shows | needs |
|---|---|---|
| [1 · Four environments](./environments) | environments as layer stacks, tags, building them, running in several at once, `--batch` | reading, mostly |
| [2 · Adopt an existing suite](./adopt-a-suite) | a pytest / Catch2 / cargo project, its tests run one by one, unmodified | a compiler, cargo |
| [3 · Numbers over two machines](./two-machines) | the whole thing end to end: numbers taken in two places, compared | an ssh host |
| [4 · errand's own entries](./first-entry) | no configuration at all: entries, parameters, matrices, the output tree | nothing but `errand` |

The second and the fourth need nothing but their own toolchain. Tutorials one and three name micromamba environments, Apptainer images, ssh
hosts and a Slurm partition that do not exist on your machine — they are there to be read and
adapted, and `errand envs` will tell you honestly that none of them is built.

::: tip Reading order, if you are in a hurry
Read [Getting started](/guide/start). Then [Environments](/guide/environments) and
[Where the output goes](/guide/output), which are the two ideas everything else is built on.
:::
