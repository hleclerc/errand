# Containers: Apptainer, Docker, Podman

A container layer wraps the command with the engine's `exec`, and runs the container's own
interpreter. The image is [built from its recipe](../upkeep) when it is missing or the recipe changed.

## Apptainer

```python
Apptainer( image, recipe = None, flags = [ ], mounts = { }, pip = [ ],
           fakeroot = False, scratch = None, build_flags = [ ],
           build_on = None, install = None, run_from = None, exe = "apptainer" )
```

Wraps with `apptainer exec`, using the container's own interpreter.

| | |
|---|---|
| `image` | the `.sif` |
| `recipe` | the `.def` it is built from. A change to it is a reason to rebuild |
| `flags` | passed to `apptainer exec` — `--nv`, `--nvccli` |
| `mounts` | `{ host: container }` |
| `pip` | installed **into** the container |

The last three are about *building* the image rather than entering it:

- `fakeroot` — build without root on a host that allows it.
- `scratch` — a directory with room. Apptainer unpacks whole layers, and the default `/tmp` is where
  a build dies halfway, out of space, on a shared machine.
- `build_flags` — passed to `apptainer build`.

For a machine without internet — a national cluster, where a recipe that downloads anything cannot
be built:

- `build_on` — an `Ssh` to a machine that can build it ( same architecture ). The project is pushed
  there, the image built there, then streamed through this process to where it runs: the two
  machines need not reach each other. Where it is built is not part of what makes it stale.
- `install` — a shell line run where it runs once the image is there ( `{image}`: its path in the
  project ), for a site that only executes images from a place of its own
  ( `idrcontmgr cp {image}` at IDRIS ).
- `run_from` — the image as entered when not `image`, expanded by the shell where it runs
  ( `$SINGULARITY_ALLOWED_DIR/main.sif` ).
- `exe` — the command, `singularity` where that is what the site calls it.

An image is built **where it is used**: an [`Ssh`](./ssh) layer in front means the recipe is rsynced
over and the build happens there — see [Where an image gets built](../upkeep#where-an-image-gets-built).

## Docker / Podman

```python
Docker( image, recipe = None, flags = [ ], mounts = { }, pip = [ ], user = "caller" )
Podman( … )     # the same, rootless
```

`user` defaults to the caller's own, and this matters: a run writes its results into the project, and
a daemon-backed container writes them as root unless told otherwise — so the output tree of a
containerized run would come out owned by somebody who is not you, and the next run *outside* the
container could not clear it. Podman, being rootless, already maps the caller.
