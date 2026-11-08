---
status: accepted
date: 2026-11-04
---

# What was built is recorded where it lives, and described from both ends

A rebuild of the wheels found `manylinux.sif` from 2026-10-13 on the build machine, without the
`jax` pin its recipe has had since 2026-10-14, while `.errand/env-lin_wheels.yaml` held the
fingerprint of the pinned recipe: errand called it up to date. The most likely path is adoption.
The environment had just been renamed, so it had no record, the image was present, and adopting it
wrote the fingerprint it *wanted*, as if it had been built from it. Three things were wrong: an
adoption claimed something nobody knew, the record was keyed by the environment's name and kept on
the laptop while the image lived elsewhere, and "is it there" was the only question ever asked of
the image.

**A record lives with the artefact, one per artefact.** In the `.errand/` of the machine that holds
the artefact: `.errand/builds/<layer>-<name>-<hash>.yaml`, the hash covering the artefact's full
identity because two images may share a file name. Renaming an environment or changing checkout no
longer forgets anything. The `env-<name>.yaml` files are abandoned: everything is adopted once.

**Both ends of a build are recorded, the same way for every layer.** The inputs by the fingerprint
of what the layer declares, as before: recipes are small and read locally, so a checksum costs
nothing and no date is needed. The artefact by a **stamp**, read right after the build: a cheap
observation, since hashing 4 GB on every run is out of the question and a conda prefix has no
single content. File size and date for an image, the id for a Docker image, `conda-meta/history` for
a conda environment, `site-packages` for a venv. Then, for every layer:

| situation | verdict |
|---|---|
| no record | adopted |
| fingerprint differs | stale, rebuilt |
| stamp differs alone | the record no longer describes this artefact: adopted again |
| both the same | ok |

The fingerprint comes first: a `site-packages` directory changes for reasons of its own, and that
must not turn a new requirement into an adoption that leaves it uninstalled.

**Dates only matter where nothing else is known.** Replacing the fingerprint by a comparison of
dates would lose what is not a file ( flags, pip lists ) and rebuild on every `git checkout`. But
at adoption the fingerprint knows nothing, so that is where an input newer than the artefact is
used: what can be rebuilt without risk is rebuilt, the rest gets a warning. The cost of a false
alarm is one needless build, once; the cost of a miss is a published wheel with the wrong `jax`.

**An adoption says it is one.** `origin: adopted` in the record, with the fingerprint seen at that
moment only as the base for later changes, and `adopted` in `errand envs`. The rule that an
environment somebody works in is never the collateral of a first reading still holds.

**An image is built aside, and the one it replaces is kept.** Built as `<image>.new`, renamed once
everything succeeded; a failed `.new` is removed. The image it replaces becomes `<image>.prev`,
overwritten by the next build, because a recipe that downloads what it likes cannot always rebuild
the old one. Docker and the Windows image already work that way. Conda and venv environments
cannot: a prefix is not relocatable, so they stay built in place, and a failure shows in the record.

**A failed build stops the run and is tried again the next time.** Going on with the old image
under a warning is how a wrong image gets used without anyone noticing: the message says the
existing one is untouched and that `--no-setup` uses it, and that stays a decision somebody makes.
The next run tries again, whether or not anything changed: failures are often passing ones.

**Two files at most per artefact.** The yaml says what the artefact is ( `built` ) and how the last
attempt failed, if it did ( `last_attempt` ); the log holds the output of the last attempt. Both are
rewritten every time, there is no history, so the count does not grow with the number of builds.

**`push` protects exact names, not extensions.** `rsync --delete` used to spare `*.sif`, which also
erased a hand-made `manylinux.sif.2026-10-13.bak` without a word, and would have erased a `.new`
mid-build. Each layer now says which paths are its own ( the image, its `.new`, `.prev` and `.part` ),
and `push` excludes the union over all the project's environments, anchored at the root: two
environments share a remote root, and one must not delete the other's image. `*.sif` leaves the
list. `push` prints what it deleted over there: a hand-made file in the remote root is still not
protected, but it no longer goes silently.

**Consequences.** Reading a record costs one more `ssh` per layer before a run. `errand envs` still
says `unknown` over ssh: it stays a command that does not reach for other machines.
