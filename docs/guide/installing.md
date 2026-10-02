# Installing

```bash
pip install errand-run
```

The *distribution* is called `errand-run` — `errand` on PyPI is somebody else's project — but what
you type, and what you import, is `errand`:

```bash
errand --version
```

```python
from errand import test, bench, Param
```

Python 3.10 or later, on a unix.

## No dependencies, and it is not going to get any

errand's job is to build the environment the work runs in, so it has to be able to run *before any
environment exists* — including before its own dependencies could have been installed. It writes
YAML without pyyaml, and draws [its screen](./tui) with the `curses` of the standard library, for
that reason alone.

This is a property worth keeping, not an accident. An environment-building tool that needs an
environment first is a tool you cannot use on the machine where you need it most.

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

The suite is worth knowing about for a second reason: it is the most thorough example of errand
there is. Every behaviour documented on this site is exercised by an entry in `tests/`, written the
way you would write your own.

## The examples

The three worked examples ship in the sdist and in the checkout, and are meant to be read in order:

```bash
cd examples/01-minimal     && errand          # no configuration at all
cd examples/02-environments && errand --envs  # four environments over three machines
cd examples/03-existing-suite && errand       # pytest + Catch2 + cargo, unmodified
```

The first needs nothing but `errand`. The other two name micromamba environments, Apptainer images,
ssh hosts and a Slurm partition that do not exist on your machine — they are there to be read and
adapted, and `errand --envs` will tell you honestly that none of them is built.

Each one has a tutorial on this site: [one](/tutorials/first-entry), [two](/tutorials/environments),
[three](/tutorials/adopt-a-suite).
