# Examples

Start where your project is: the layers (containers, ssh, Slurm) → `01`; a pytest / Catch2 / cargo
project → `02`, then `04` and `05` for a real build; no framework, work to write with errand's own
entries → `03`.

| | what it shows |
|---|---|
| [`01-environments`](01-environments/) | environments as layer stacks, tags, building them, running in several at once, `--batch` |
| [`02-existing-suite`](02-existing-suite/) | a pytest / Catch2 / cargo project, unmodified, one run of each tool per file |
| [`03-entries`](03-entries/) | errand's own entries, with no configuration at all: parameters, matrices, the output tree |
| [`04-catch2`](04-catch2/) | a Catch2 suite built with CMake: the build in the preparation, then one run per binary |
| [`05-cargo`](05-cargo/) | a cargo crate: `cargo test --no-run` in the preparation, then one run per test target |
| [`06-mpi`](06-mpi/) | an MPI program with communications: `--ranks`, entries on several ranks, Slurm over two nodes in an Apptainer image |

`03` needs nothing but `errand`, `02` its own toolchains, `04` CMake and a C++ compiler, `05` cargo, `06` micromamba ( and a cluster for its second half ). `01` names micromamba, Apptainer, ssh
hosts and a Slurm partition that do not exist on your machine — it is there to be read and
adapted, and `errand envs` will tell you honestly that none of it is built.
