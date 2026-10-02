"""What a test needs from THIS machine, and cannot ask of anyone else's.

Testing an ssh layer wants a host you can reach. Testing a Slurm layer wants a
partition you are allowed to submit to. Neither can be committed, and neither
can be invented -- so they live in a file that is not versioned, beside the
project's others: any `errand-*.py`, conventionally `errand-envs.py`:

    # errand-envs.py -- not tracked
    ssh_host  = "gpu-box"
    ssh_root  = "/home/me/scratch/errand"
    slurm     = { "partition": "gpu", "time": "00:10:00" }

Every plain value a project file defines ( not its imports, functions or
classes ) is readable by the files read after it, and by entries.

An entry asks for what it needs and is SKIPPED, loudly, when it is not there:

    if test( "it runs over ssh" ):
        host = need( "ssh_host", "a machine you can ssh to without a password" )

A skip is not a pass. It is reported as its own status, it says exactly what
was missing and what to write where, and the run ends with a block listing
every one of them -- so that a suite which silently tested nothing cannot be
mistaken for a suite that passed.
"""
from __future__ import annotations

import inspect
from pathlib import Path

ENVS_FILE = "errand-envs.py"

_cache: dict = { }
_files: list = [ ]
_missing_root: Path | None = None


class Skipped( Exception ):
    """Raised by `skip` / `need`; turned into a SKIP status by the runner."""

    def __init__( self, reason, hint = None ):
        super().__init__( reason )
        self.reason = reason
        self.hint   = hint


def reset( files = ( ), root: Path | None = None ):
    """Forget everything, and note which files are about to be read."""
    global _files, _missing_root
    _cache.clear()
    _files = list( files )
    _missing_root = None if files else root


def offer( module ):
    """Keep what a project file defined that is plain data."""
    _cache.update( { k: v for k, v in vars( module ).items()
                     if not k.startswith( "_" )
                     and not inspect.ismodule( v ) and not inspect.isclass( v )
                     and not inspect.isroutine( v ) } )


def skip( reason, hint = None ):
    """Stop this entry, and say why. Not a failure, and not a pass."""
    raise Skipped( reason, hint )


def have( key: str ) -> bool:
    return key in _cache


def value( key: str, default = None ):
    """The local value of `key`, or `default` -- WITHOUT skipping.

    `need` is for an entry, which has the option of not running. A project file
    has no such option: it is read once, before anything, and what it does not
    find it must simply do without. That is what lets a host name, a remote
    root or a scratch directory stay out of git while the declaration that uses
    them is committed, with a default that works here.
    """
    return _cache.get( key, default )


def need( key: str, what: str = "", *, example = None ):
    """The value of `key` from the local file, or skip saying what is missing."""
    if key in _cache:
        return _cache[ key ]

    shown = f"{key} = {example!r}" if example is not None else f"{key} = ..."
    where = next( ( f for f in _files if f.name == ENVS_FILE ), None ) \
        or ( _files[ 0 ].parent if _files else ( _missing_root or Path( "." ) ) ) / ENVS_FILE
    if where.is_file():
        hint = f"add it to {where}:\n    {shown}"
    else:
        hint = ( f"{where} does not exist yet. Create it (it is not tracked) with:\n"
                 f"    {shown}" )
    raise Skipped( f"needs `{key}`" + ( f" -- {what}" if what else "" ), hint )


def status( ) -> str:
    """One line for the banner: which project files were read, and what they gave."""
    if _files:
        return f"{', '.join( f.name for f in _files )}: {', '.join( sorted( _cache ) ) or 'no values'}"
    return "no errand-*.py (entries needing local settings will be skipped)"
