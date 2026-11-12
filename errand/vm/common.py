"""What the parts of a machine share: its state files here ( locks, pids ), the guest's login and
the timeouts, the error a machine raises, and the small helpers everything here uses.
"""
from __future__ import annotations

import os
from pathlib import Path

from .. import layers as L


USER     = "Administrator"

INSTALL_TIMEOUT = 4 * 3600
BOOT_TIMEOUT    = 20 * 60


def _lock( path: Path, block = True ):
    """An exclusive flock on `path` -> the open file, or None if not now."""
    handle = open( path, "a" )
    try:
        import fcntl            # here: the layer is also declared, never run, where there is no fcntl
        fcntl.flock( handle, fcntl.LOCK_EX | ( 0 if block else fcntl.LOCK_NB ) )
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _alive( pid ) -> bool:
    try:
        os.kill( int( pid ), 0 )
        return True
    except ( OSError, ValueError ):
        return False


def _read( path: Path, default = "" ) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return default


GUEST_OPTIONS = [ "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=no",
                  "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
                  "-o", "BatchMode=yes", "-o", "ConnectTimeout=5" ]


class VmError( RuntimeError ):
    """Something about this machine cannot run one: said once, plainly."""


def _backslashed( path: str ) -> str:
    return path.replace( "/", "\\" )


def _seconds( text ) -> float:
    """`15m`, `2h`, `30s`, `0`, 90 -> seconds."""
    text = str( text ).strip().lower()
    scale = { "s": 1, "m": 60, "h": 3600, "d": 86400 }
    if text and text[ -1 ] in scale:
        return float( text[ : -1 ] ) * scale[ text[ -1 ] ]
    return float( text )


def where( host ) -> str:
    return "here" if not host.remote else f"on {host.describe()}"


def _sh( script: str, *args ) -> str:
    """A POSIX script as one line for `host.shell`: whatever the login shell
    over there is ( zsh, fish ), the script is read by `sh`."""
    return L.sh( [ "sh", "-c", script, "errand", *[ str( a ) for a in args ] ] )
