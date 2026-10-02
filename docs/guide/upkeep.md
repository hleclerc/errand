# Keeping environments current

A layer says what it needs — an interpreter version, a channel list, a `requirements.txt`, a `.def`
or `Dockerfile` recipe, a pip list. Before running anything, `errand` compares a fingerprint of
that against what was last built, and brings it up to date when they have drifted: a new pip spec,
an edited recipe, a changed requirements file.

Creating an environment, installing into it and rebuilding an image are **one operation seen at
three moments**, and it happens on its own.

```bash
errand --envs             # what is declared, what state it is in, which is the default
errand --setup            # do it now, and nothing else
errand --setup=force      # from scratch
errand --setup --dry-run  # say what that would run, and run nothing
errand --no-setup         # skip the check for this run
```

You do not have to act on `stale` or `not built`. The next run that needs one of those environments
builds it first.

## What is already there is adopted, not rebuilt

The first time errand meets an environment there is no record of what it was built from, so every
layer looks out of date — and acting on that reading would mean recreating, on somebody's first
command, an environment that has been working for months.

So: **present and never seen before is recorded as-is.** Only a declaration that has *changed* since
a record errand itself wrote is a reason to touch anything, and `--setup=force` is how you say the
other thing.

::: danger Why this matters more than it sounds
`micromamba create -n x` on an existing `x` is not a no-op and not an update: it resolves the named
specs into it, and `python=3.13` over a 3.14 environment takes every package installed for 3.14 out
with it.

An environment somebody is working in must never be the collateral of a declaration being read for
the first time.
:::

## Where an image gets built

Building an image happens **where the image is used**. An `Ssh` layer in front means the sources are
rsynced over first — the recipe is a file *here*, the build happens *there* — and `apptainer build`
then runs on that host, with `fakeroot` and `scratch` as declared.

`fakeroot` builds without root on a host that allows it. `scratch` is a directory with room:
apptainer unpacks whole layers, and the default `/tmp` is where a build dies halfway, out of space,
on a shared machine.

```python
Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
           fakeroot = True, scratch = "/scratch/me/apptainer" )
```

This is also the reason [errand has no third-party dependencies](./installing#no-dependencies-and-it-is-not-going-to-get-any):
it has to work before any environment exists.

## Being let into one

```bash
errand --env gpu -- python -m mypkg.toolchain   # that command, in that environment
errand --env cluster -- nvidia-smi              # on the other machine, through ssh
errand --driver torch -- python -c "import torch; print( torch.__version__ )"
```

Everything after a bare `--` is a command to run *in* the environment rather than arguments to
errand.

The environments are already declared here, once, with the layers that lead to them — a venv, a
container, another machine — so being let into one is a smaller thing than a second tool that would
have to describe them all over again. **Entering an environment prepares it too**, by the same rules
as a run: what has drifted is brought up to date first.

A first word that **names an interpreter** is replaced by the interpreter of the place; any other is
a command in its own right and is kept. That is why `-- python -c …` runs the container's python and
`-- nvidia-smi` runs nvidia-smi.

## Next

[Tags](./tags) — how an environment says what it *is*, and how one environment covers a whole
dimension.
