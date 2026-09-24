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
)

__all__ = [
    "Args", "Param", "bench", "entry", "experiment", "has_tag", "out_dir", "tag", "test",
    "main",
]

_LAZY = { "main": "errand.cli" }


def __getattr__( name ):
    if name in _LAZY:
        import importlib
        return getattr( importlib.import_module( _LAZY[ name ] ), name )
    raise AttributeError( f"module {__name__!r} has no attribute {name!r}" )


def __dir__( ):
    return sorted( set( __all__ ) | set( globals() ) )
