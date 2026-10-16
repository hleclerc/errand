# Examples

Start where your project is: the layers (containers, ssh, Slurm) → `01`; a pytest / Catch2 / cargo
project → `02`; no framework, work to write with errand's own entries → `03`.

| | what it shows |
|---|---|
| [`01-environments`](01-environments/) | environments as layer stacks, tags, building them, running in several at once, `--batch` |
| [`02-existing-suite`](02-existing-suite/) | a pytest / Catch2 / cargo project, its tests run one by one, unmodified |
| [`03-entries`](03-entries/) | errand's own entries, with no configuration at all: parameters, matrices, the output tree |

`03` needs nothing but `errand`, `02` its own toolchains. `01` names micromamba, Apptainer, ssh
hosts and a Slurm partition that do not exist on your machine — it is there to be read and
adapted, and `errand envs` will tell you honestly that none of it is built.
