# Examples

Read them in order; each one adds a leg.

| | what it shows |
|---|---|
| [`01-minimal`](01-minimal/) | no configuration at all: entries, parameters, matrices, the output tree |
| [`02-environments`](02-environments/) | environments as layer stacks, tags, building them, running in several at once, `--batch` |
| [`03-existing-suite`](03-existing-suite/) | a pytest / Catch2 / cargo project adopted in three lines, unmodified |

The first one needs nothing but `errand`. The other two name micromamba, Apptainer, ssh hosts and a
Slurm partition that do not exist on your machine — they are there to be read and adapted, and
`errand --envs` will tell you honestly that none of them is built.
