"""Where the images, the live machines and their state live, on this machine.
"""
from __future__ import annotations

import os
from pathlib import Path


def cache_dir( ) -> Path:
    return Path( os.environ.get( "XDG_CACHE_HOME" ) or Path.home() / ".cache" ) / "errand"


def images_dir( ) -> Path:
    """The images, when QEMU runs on this machine. Over there, the same place in THAT cache."""
    return cache_dir() / "windows"


def live_dir( ) -> Path:
    """The state, the locks and the keeper of every machine this one has
    booted, here or elsewhere: on this machine, where the deciding is."""
    return cache_dir() / "vm"
