"""errand -- run work somewhere, and bring back what it produced.

Entry files import from here and nothing else, and finding entries means
importing EVERY candidate file, so this module must stay cheap: the names
below come from `errand.entries`, which imports only the standard library.
Everything heavier -- the command line, environments, layers -- is reached
through the lazy `__getattr__` at the bottom.
"""
from __future__ import annotations

__version__ = "0.1.0.dev0"

from .entries import (          # noqa: F401  -- the public surface of a file of work
    Args,
    Param,
    bench,
    entry,
    experiment,
    has_tag,
    out_dir,
    tag,
    test,
    track,
)
from .local import Skipped, have, need, skip, value   # noqa: F401

# Read by errand when it needs a default: `errand.default_env = "gpu"` in an `errand-*.py`.
default_env: str | None = None

__all__ = [
    "Args", "Param", "Skipped", "bench", "entry", "experiment", "has_tag", "have",
    "need", "out_dir", "skip", "tag", "test", "track",
    "configure", "default_env", "Env", "envs", "provider", "main", "value",
    "Vars", "Venv", "Micromamba", "Conda", "Uv", "Nix", "Guix", "Module",
    "Apptainer", "Docker", "Podman", "Ssh", "Slurm",
    "Provider", "Outcome", "RunContext", "Pytest", "Catch2", "Cargo",
]

# Everything past the declaration surface is reached lazily: an entry file
# imports from here, and finding entries means importing EVERY candidate file,
# so that path must stay as cheap as a couple of stdlib modules.
_LAZY = {
    "main"      : "errand.cli",
    "configure" : "errand.config",
    "Env"       : "errand.config",
    "envs"      : "errand.config",
    "provider"  : "errand.config",
    "Vars"      : "errand.layers",
    "Venv"      : "errand.layers",
    "Micromamba": "errand.layers",
    "Conda"     : "errand.layers",
    "Uv"        : "errand.layers",
    "Nix"       : "errand.layers",
    "Guix"      : "errand.layers",
    "Module"    : "errand.layers",
    "Apptainer" : "errand.layers",
    "Docker"    : "errand.layers",
    "Podman"    : "errand.layers",
    "Ssh"       : "errand.layers",
    "Slurm"     : "errand.layers",
    "Provider"  : "errand.providers",
    "Outcome"   : "errand.providers",
    "RunContext": "errand.providers",
    "Pytest"    : "errand.providers",
    "Catch2"    : "errand.providers",
    "Cargo"     : "errand.providers",
}

# The same names, spelled out for type checkers and editors, which cannot follow
# `__getattr__`. Never executed, so the import above stays cheap.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .cli import main
    from .config import Env, configure, envs, provider
    from .layers import (
        Apptainer, Conda, Docker, Guix, Micromamba, Module, Nix, Podman, Slurm, Ssh, Uv, Vars, Venv,
    )
    from .providers import Cargo, Catch2, Outcome, Provider, Pytest, RunContext


def __getattr__( name ):
    if name in _LAZY:
        import importlib
        return getattr( importlib.import_module( _LAZY[ name ] ), name )
    raise AttributeError( f"module {__name__!r} has no attribute {name!r}" )


def __dir__( ):
    return sorted( set( __all__ ) | set( globals() ) )
