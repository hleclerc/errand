"""What a test needs from THIS machine, and cannot ask of anyone else's.

Testing an ssh layer wants a host you can reach. Testing a Slurm layer wants a
partition you are allowed to submit to. Neither can be committed, and neither
can be invented -- so they live in an untracked file beside the project's
`errand.py`:

    # errand.local.py -- not tracked
    ssh_host  = "gpu-box"
    ssh_root  = "/home/me/scratch/errand"
    slurm     = { "partition": "gpu", "time": "00:10:00" }

An entry asks for what it needs and is SKIPPED, loudly, when it is not there:

    if test( "it runs over ssh" ):
        host = need( "ssh_host", "a machine you can ssh to without a password" )

A skip is not a pass. It is reported as its own status, it says exactly what
was missing and what to write where, and the run ends with a block listing
every one of them -- so that a suite which silently tested nothing cannot be
mistaken for a suite that passed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

LOCAL_FILE = "errand.local.py"

_cache: dict = { }
_loaded_from: Path | None = None
_missing_root: Path | None = None


class Skipped( Exception ):
    """Raised by `skip` / `need`; turned into a SKIP status by the runner."""

    def __init__( self, reason, hint = None ):
        super().__init__( reason )
        self.reason = reason
        self.hint   = hint


def find( root: Path ):
    """`errand.local.py` at `root` or above it.

    Walking up matters: a suite often runs with its own subdirectory as the
    root, while the file belongs to the checkout as a whole -- there is one per
    machine, not one per directory.
    """
    for directory in [ root, *root.parents ]:
        path = directory / LOCAL_FILE
        if path.is_file():
            return path
    return None


def load( root: Path ):
    """Read `errand.local.py` at `root` or above. Never an error."""
    global _loaded_from, _missing_root
    _cache.clear()
    _loaded_from = None
    _missing_root = root

    path = find( root )
    if path is None:
        return { }

    spec = importlib.util.spec_from_file_location( "_errand_local", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    _cache.update( { k: v for k, v in vars( module ).items() if not k.startswith( "_" ) } )
    _loaded_from = path
    _missing_root = None
    return dict( _cache )


def skip( reason, hint = None ):
    """Stop this entry, and say why. Not a failure, and not a pass."""
    raise Skipped( reason, hint )


def have( key: str ) -> bool:
    return key in _cache


def need( key: str, what: str = "", *, example = None ):
    """The value of `key` from the local file, or skip saying what is missing."""
    if key in _cache:
        return _cache[ key ]

    shown = f"{key} = {example!r}" if example is not None else f"{key} = ..."
    where = _loaded_from or ( ( _missing_root or Path( "." ) ) / LOCAL_FILE )
    hint = ( f"add it to {where}:\n"
             f"    {shown}" )
    if _loaded_from is None:
        hint = ( f"{where} does not exist yet. Create it (it is not tracked) with:\n"
                 f"    {shown}" )
    raise Skipped( f"needs `{key}`" + ( f" -- {what}" if what else "" ), hint )


def status( ) -> str:
    """One line for the banner: where the local file is, or that there is none."""
    if _loaded_from:
        return f"{_loaded_from.name}: {', '.join( sorted( _cache ) ) or 'empty'}"
    return f"no {LOCAL_FILE} (entries needing local settings will be skipped)"
