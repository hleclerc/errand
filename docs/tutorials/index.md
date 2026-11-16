# Tutorials

Three walkthroughs, from reading a declaration to running on a cluster and a Windows VM.

| | what it shows | needs |
|---|---|---|
| [1 · Four environments](./environments) | environments as stacks of layers, tags, building them, running in several at once, `--batch` | reading, mostly |
| [2 · Numbers over two machines](./two-machines) | one measurement taken here and on a server over ssh, recorded, compared a month later | an ssh host |
| [3 · A cluster, a Windows VM, and what is running](./cluster-and-vm) | a training on Slurm with results brought back, an allocation kept warm, a Windows build from a Mac, `errand status`, `attach`, stopping everything | read it; reproducing needs a cluster and a Linux host with KVM |

The first one ships with errand, in
[`examples/01-environments`](https://github.com/hleclerc/errand/tree/main/examples/01-environments).
It names micromamba environments, Apptainer images, ssh hosts and a Slurm partition that do not exist
on your machine: read it, adapt it, and `errand envs` tells you which of them are built here.

**Which first?**

- you want to see how a place is declared → [1 · Four environments](./environments)
- you have a server and want comparable numbers → [2 · Numbers over two machines](./two-machines)
- you have a cluster account, or need Windows → [3 · A cluster, a Windows VM, and what is running](./cluster-and-vm)

## Moved to the guide

- Running an existing pytest, Catch2 or cargo suite test by test:
  [Adopting a suite](/guide/runners/adopting).
- errand's own entries (`test`, `bench`, `track`, `Param`):
  [Writing entries](/guide/declaring-work).

::: tip In a hurry
Read the [Quickstart](/guide/start), then [Environments](/guide/environments) and
[Results and records](/guide/output). Everything else builds on those three.
:::
