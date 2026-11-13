# Keeping environments current

A layer says what it needs — an interpreter version, a channel list, a `requirements.txt`, a `.def`
or `Dockerfile` recipe, a pip list. Before running anything, `errand` compares a fingerprint of
that against what was last built, and brings it up to date when they have drifted: a new pip spec,
an edited recipe, a changed requirements file.

Creating an environment, installing into it and rebuilding an image are **one operation seen at
three moments**, and it happens on its own.

```bash
errand envs             # what is declared, what state it is in, which is the default
errand setup            # do it now, and nothing else
errand setup --force    # from scratch
errand setup --dry-run  # say what that would run, and run nothing
errand run --no-setup   # skip the check for this run
```

You do not have to act on `stale` or `not built`. The next run that needs one of those environments
builds it first.

## What is already there is adopted, not rebuilt

The first time errand meets an environment there is no record of what it was built from, so every
layer looks out of date — and acting on that reading would mean recreating, on somebody's first
command, an environment that has been working for months.

So: **present and never seen before is recorded as `adopted`**, which is what `errand envs` then says.
Only a declaration that has *changed* since a record errand itself wrote is a reason to touch anything,
and `errand setup --force` is how you say the other thing.

The one exception is an image, which a build cannot harm: found older than its recipe, it is rebuilt.
Anything else older than what it declares is adopted with a warning.

::: danger Why this matters more than it sounds
`micromamba create -n x` on an existing `x` is not a no-op and not an update: it resolves the named
specs into it, and `python=3.13` over a 3.14 environment takes every package installed for 3.14 out
with it.

An environment somebody is working in must never be the collateral of a declaration being read for
the first time.
:::

## What errand remembers

A record lives on the machine that holds what was built, in its `errand-outputs/builds/records/`
( or under `builds_directory` ): one yaml per
artefact, and the output of the last attempt beside it. Both are rewritten every time, there is no
history. The yaml holds the fingerprint of what was declared, and a stamp of what came out: an image's
date and size, a Docker image's id, a conda prefix's `conda-meta/history`, a venv's `site-packages`. An
artefact whose stamp changed behind errand's back is adopted again.

A failed build stops the run and is tried again on the next one, whether or not anything changed.
**An image is built aside**, as `<image>.new`, so the existing one stays whole and
`errand run --no-setup` can still use it; it only goes once the new one is complete, and is then kept
as `<image>.prev` until the next build. Conda and venv environments cannot be moved once built, so
they are updated in place: after a failure they may be half updated.

## What stays on the other machine

`rsync` pushes with `--delete`. What a layer builds in the project ( an image with its `.new`, `.prev`
and `.part`, a uv environment ) is excluded by its exact path, for every environment of the project.
Anything else that exists only over there is deleted by the next push, and `errand` prints what went.
Keep what you put there by hand outside the project's copy.

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
errand run --env gpu python -m mypkg.toolchain  # that command, in that environment
errand run --env cluster nvidia-smi             # on the other machine, through ssh
errand run --driver torch python -c "import torch; print( torch.__version__ )"
errand shell --env gpu                          # a shell there, to type into
```

Everything from the first word that is not one of errand's options is a command to run *in* the
environment rather than arguments to errand.

The environments are already declared here, once, with the layers that lead to them — a venv, a
container, another machine — so being let into one is a smaller thing than a second tool that would
have to describe them all over again. **Entering an environment prepares it too**, by the same rules
as a run: what has drifted is brought up to date first.

A first word that **names an interpreter** is replaced by the interpreter of the place; any other is
a command in its own right, looked for on the place's `PATH`, and is kept. That is why `python -c …`
runs the container's python and `nvidia-smi` runs nvidia-smi.

## Next

[Tags](./tags) — how an environment says what it *is*, and how one environment covers a whole
dimension.

## When something breaks

`-v` says every process errand starts, on stderr, before it starts: the probe that checks an
environment exists, the rsync, the ssh line, the image build, the scheduler submission, the errand
that runs over there. With each, the directory when it is not the current one and the variables it is
handed beyond errand's own; a command that fails says its code and how long it took.

```bash
errand -v run --env lmo ./solve
errand -v setup --env lmo
```

```
  · $ ssh lmo '$SHELL -ic '"'"'cd /home/me/proj && micromamba -n prj run true'"'"''
  · ✗ exit 1 after 0.4 s: ssh lmo '$SHELL -ic ...
```

It crosses with the command: the errand over ssh, in a container or under a scheduler says its own
commands too. The probes that are otherwise silent keep their output, so a check that fails says why.
`errand tui` draws on the terminal and stays quiet itself, but the runs it starts inherit `-v` and say
their commands in their own panes. What the work itself starts is said as well when errand runs it in
its own process — an entry's `subprocess.run`, for instance.

