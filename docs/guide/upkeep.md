# Keeping environments current

```bash
errand envs             # what is declared, and what state it is in
errand setup            # build or update now, and nothing else
errand setup gpu cluster   # those two
errand setup --force    # from scratch
errand setup --dry-run  # say what it would run, and run nothing
errand run --no-setup …  # skip the check for this command
```

A layer says what it is made from: a Python version, channels, a `requirements.txt`, a `.def` or a
`Dockerfile`, a pip list. Before a command, errand compares a fingerprint of that with what it last
built, and brings the environment up to date when they differ: a new pip package, an edited recipe,
a changed requirements file.

You do not have to act on `stale` or `not built` in `errand envs`. The next command that needs the
environment builds it first, and `errand shell` does too.

## What is already there is adopted, not rebuilt

The first time errand meets an environment, it has no record of how it was built, so every layer
looks out of date. Acting on that would mean recreating, on somebody's first command, an environment
that has worked for months.

So **an environment that is there and was never seen before is recorded as `adopted`**, and left as
it is. Only a declaration that has *changed* since a record errand wrote itself is a reason to touch
anything. `errand setup --force` is how you ask for the rest.

The one exception is an image, which a build cannot harm: found older than its recipe, it is rebuilt.
Anything else older than what it declares is adopted, with a warning.

::: danger Why this matters
`micromamba create -n x` on an existing `x` is not a no-op and not an update: it resolves the named
specs into it, and `python=3.13` over a 3.14 environment takes every package installed for 3.14 out
with it. An environment somebody works in must never be damaged by a declaration being read for the
first time.
:::

## What errand remembers

A record lives on the machine that holds what was built, in its `errand-outputs/builds/records/`
( or under `builds_directory` ): one yaml per artefact, with the output of the last attempt beside
it. Both are rewritten each time; there is no history. The yaml holds the fingerprint of the
declaration and a stamp of the result: an image's date and size, a Docker image's id, a conda
prefix's `conda-meta/history`, a venv's `site-packages`. An artefact whose stamp changed behind
errand's back is adopted again.

## When a build fails

A failed build stops the command, and is tried again by the next one, changed or not.

**An image is built aside**, as `<image>.new`: the existing one stays whole, and
`errand run --no-setup` can still use it. It is replaced once the new one is complete, and kept as
`<image>.prev` until the next build. Conda environments and venvs cannot be moved once built, so they
are updated in place: after a failure they may be half updated.

## What stays on the other machine

The push to another machine deletes what is only over there. What a layer builds in the project
( an image with its `.new`, `.prev` and `.part`, a uv environment ) is excluded by its exact path, for
every environment of the project. Anything else that exists only over there goes at the next push,
and errand prints what went. Keep what you put there by hand outside the project's copy, or declare
it as a [zone](./layers/ssh#what-gets-pushed).

## Where an image gets built

An image is built **where it is used**. With an `Ssh` layer in front, the recipe — a file here — is
copied over, and `apptainer build` runs on that host, with `fakeroot` and `scratch` as declared:

```python
Apptainer( image = "containers/cuda.sif", recipe = "containers/cuda.def",
           fakeroot = True, scratch = "/scratch/me/apptainer" )
```

`fakeroot` builds without root on a host that allows it. `scratch` is a directory with room:
apptainer unpacks whole layers, and the default `/tmp` is where a build dies halfway, out of space,
on a shared machine. For a host without internet, see
[`build_on`](./layers/containers#a-cluster-without-internet).

This is also why [errand has no dependencies](./installing#no-dependencies): it has to work before
any environment exists.

## When something breaks

`-v` prints every process errand starts, on stderr, before it starts: the probe that checks an
environment exists, the rsync, the ssh line, the image build, the scheduler submission, the errand
that runs over there. Each comes with its directory, when it is not the current one, and the
variables it is handed beyond errand's own. A command that fails says its exit code and how long it
took.

```bash
errand -v run --env lmo ./solve
errand -v setup --env lmo
```

```text
  · $ ssh lmo '$SHELL -ic '"'"'cd /home/me/proj && micromamba -n prj run true'"'"''
  · ✗ exit 1 after 0.4 s: ssh lmo '$SHELL -ic ...
```

It crosses with the command: the errand over ssh, in a container or under a scheduler prints its
own commands too. Probes that are otherwise silent keep their output, so a failed check says why.
What the work itself starts is printed as well when errand runs it in its own process, an entry's
`subprocess.run` for instance.

To look around by hand, `errand shell --env lmo` opens a shell in the same place, through the same
layers. → [Running a command](./running#a-shell-in-an-environment-errand-shell)

## Next

[Choosing among environments (tags)](./tags), for projects with many environments.
