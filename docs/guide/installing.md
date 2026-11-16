# Installing

```bash
pip install errand-run
```

The *distribution* is called `errand-run` — `errand` on PyPI is somebody else's project — but what
you type, and what you import, is `errand`:

```bash
errand --version
```

Python 3.8 or later, on Linux or macOS. Only on the machine you type on: on a machine reached over
[`Ssh`](./layers/ssh#nothing-to-install-over-there), in a container, in a Windows guest, errand
brings itself.

## No dependencies

errand's job is to build the environment the work runs in, so it has to be able to run *before any
environment exists* — including before its own dependencies could have been installed. It writes
YAML without pyyaml for that reason alone. A tool that builds environments cannot need one first.

## From a checkout

Nothing needs installing to *use* errand from a checkout — it runs as a module:

```bash
git clone https://github.com/hleclerc/errand
cd errand
python -m errand --help
```

## Working on errand itself

```bash
make venv       # a virtual environment with errand installed in it, editable
make test       # the suite -- which is written with errand, and is its longest worked example
make dev        # pip install -e . into the interpreter you are using now
make            # the help, including the release order
```

## The examples

[`examples/`](https://github.com/hleclerc/errand/tree/main/examples) ships in the sdist and in the
checkout:

```bash
cd examples/01-environments   && errand envs        # four environments over three machines
cd examples/02-existing-suite && errand run '**::*' # pytest + Catch2 + cargo, unmodified
cd examples/03-entries        && errand run '**::*' # errand's own entries, no configuration
```

The first two name micromamba environments, Apptainer images, ssh hosts and a Slurm partition that
do not exist on your machine: read them, adapt them, and `errand envs` tells you none is built yet.
They go with [Four environments](/tutorials/environments),
[Adopting a suite](/guide/runners/adopting) and [Writing entries](/guide/declaring-work).
