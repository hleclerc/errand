"""Where the images, the live machines and their state live.

The images are the project's: under its `errand-outputs/builds/windows/` on the
machine that runs QEMU, beside the project's copy there ( or wherever
`builds_directory` says ) -- what accumulates belongs to a project, never to the
per-user cache, which holds only what is live.
"""
from __future__ import annotations

from pathlib import Path


def cache_dir( ) -> Path:
    """errand's per-user directory here: `ERRAND_CACHE_DIR`, else `~/.cache/errand`."""
    from .. import bootstrap
    return bootstrap.local_cache()


def images_rel( ) -> str:
    """The project's images, from its root on any machine ( or absolute )."""
    from .. import config
    return f"{config.builds_rel( Path( '.' ) )}/windows"


def images_dir( root ) -> Path:
    """The images of the project at `root`, when QEMU runs on this machine."""
    return Path( root ) / images_rel()


def live_dir( ) -> Path:
    """The state, the locks and the keeper of every machine this one has
    booted, here or elsewhere: on this machine, where the deciding is. Live
    only: a machine nobody has used for a day leaves nothing here ( `sweep` )."""
    return cache_dir() / "vm"
