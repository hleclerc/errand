# errand

> **Run it there as if it were here.** Same command, same output in your terminal, Ctrl-C included,
> whether "there" is a container, a server over ssh, a Slurm allocation or a Windows VM. errand
> sets the place up, syncs the files both ways, and cleans up after itself.

Declare a place once:

```python
# errand-envs.py
import errand

errand.envs[ "local" ]   = errand.Env( [ errand.Micromamba( "proj", python = "3.13", requirements = "requirements.txt" ) ] )
errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "gpu-box", root = "~/proj" ),
                                         errand.Slurm( gpus = 1, time = "2:00:00" ),
                                         errand.Apptainer( image = "cuda.sif", recipe = "cuda.def" ) ] )
```

Then run there what you would have typed here:

```bash
errand run --env local pytest                              # the env is created on first use
errand run --env cluster --pull out python train.py        # sync, allocation, container, and out/ back
errand run --batch --env cluster python train.py           # give me the shell back
errand attach                                              # the laptop slept: pick the run up again
errand status                                              # what runs, on every machine I sent work to
errand shell --env cluster                                 # let me in
```

## What it takes off your hands

- **The way in**: ssh, allocation, container, env, as a stack of layers crossed by one `--env`.
- **Setting the place up**: envs and images built from what they declare, updated when that
  changes. What already exists is adopted, never rebuilt.
- **Moving files**: the project is synced there; `--pull DIR` and `-o` bring results back.
- **Watching the connection**: the work goes on when the laptop closes; `errand attach` follows it again.
- **Starting over each time**: connections, allocations, VMs and imports are kept warm for a while.
- **Cleaning up**: `errand status` lists what runs everywhere; Ctrl-C stops it through every layer;
  every machine has an agent that tracks what it started and stops what a dead one left.
- **Taking turns**: a queue per machine; `-x` for a clean timing, `--cpus` / `--gpus` for a share.

It also runs pytest, Catch2 and cargo suites test by test, in every environment.

## You stay in control

What runs is your command. `-v` prints every command errand starts (ssh, sbatch, apptainer).
Everything is plain files: the places are Python, the records are in `errand-outputs/`. Nothing to
install on the other machines.

## Layers

`Micromamba`, `Conda`, `Uv`, `Venv` · `Nix`, `Guix`, `Module` · `Apptainer`, `Docker`, `Podman` ·
`Ssh` · `Slurm` · `Windows` (a QEMU VM errand installs and boots, MSVC included), `WindowsBox` (an
existing Windows machine) · `Mpi` · `Preload` (sessions forked from a process with torch already
imported) · `Vars` · `Missing`.

## Installing

```bash
pip install errand-run
```

The distribution is `errand-run` (`errand` on PyPI is another project); the command and the module
are `errand`. Python 3.8+, Linux or macOS. **No dependencies**: a tool that builds environments
cannot need one first.

## Documentation

**<https://hleclerc.github.io/errand/>**, built from [`docs/`](docs/). Worked examples in
[`examples/`](examples/).

## Status

Everything documented works and is covered by errand's own suite. The API may still move.
