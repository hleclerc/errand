"""`-v`: every process errand starts, said on stderr before it starts.

When something breaks three layers down -- a probe over ssh, an image build,
a scheduler that refuses the job -- the question is always the same: what was
actually run, where, with what. Rather than teach each of the ~40 places that
start a process to say so, the one door they all go through is watched:
`subprocess.Popen` ( `subprocess.run` opens it too ). A place added tomorrow is
covered without anybody remembering to.

What is said, on stderr so a parsed stdout stays parseable:

    · $ ssh lmo '$SHELL -ic '"'"'cd /x && python -m errand run ...'"'"''
    ·   in /Users/me/proj   + ERRAND_IN_ENV=lmo-jax ERRAND_TAGS=...
    · ✗ exit 1 after 0.4 s: ssh lmo ...

The directory only when it is not the current one, and only the variables that
differ from errand's own environment. A failure is said too, with the command
it came from; a success is not, it would be noise.

It crosses into the processes errand starts through `ERRAND_VERBOSE`: the
errand that runs over ssh, in a container or as a `-j` child says its own
commands as well. And with it, the probes that are otherwise silenced
( `quiet` in `layers` ) keep their output: a probe that fails says why.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time

ENV = "ERRAND_VERBOSE"

_original = subprocess.Popen


def enabled() -> bool:
    return bool( os.environ.get( ENV ) )


def enable():
    """From now on, in this process and the ones it starts."""
    os.environ[ ENV ] = "1"
    install()


def install():
    """Watch the door, if `-v` was asked here or by the errand that started this one."""
    if enabled() and subprocess.Popen is _original:
        subprocess.Popen = _Traced


def _say( s: str ):
    try:
        tty = sys.stderr.isatty()
    except ( AttributeError, ValueError ):
        tty = False
    line = f"  · {s}"
    print( f"\033[2m{line}\033[0m" if tty else line, file = sys.stderr, flush = True )


def _shown( args ) -> str:
    if isinstance( args, ( str, bytes ) ):
        return args if isinstance( args, str ) else args.decode( errors = "replace" )
    return " ".join( shlex.quote( os.fspath( a ) if not isinstance( a, bytes ) else a.decode( errors = "replace" ) )
                     for a in args )


def _context( cwd, env ) -> str:
    parts = [ ]
    if cwd is not None:
        here = os.path.abspath( os.fspath( cwd ) )
        if here != os.getcwd():
            parts.append( f"in {here}" )
    if env is not None:
        changed = [ f"{k}={shlex.quote( str( v ) )}" for k, v in env.items()
                    if os.environ.get( k ) != v ]
        gone = [ k for k in os.environ if k not in env ]
        if changed:
            parts.append( "+ " + " ".join( sorted( changed ) ) )
        if gone and len( gone ) <= 8:
            parts.append( "- " + " ".join( sorted( gone ) ) )
        elif gone:
            parts.append( f"( {len( gone )} variables dropped )" )
    return "   ".join( parts )


class _Traced( _original ):
    def __init__( self, args, *rest, **kw ):
        self._errand_cmd = _shown( args )
        _say( f"$ {self._errand_cmd}" )
        extra = _context( kw.get( "cwd" ), kw.get( "env" ) )
        if extra:
            _say( f"  {extra}" )
        self._errand_t0 = time.monotonic()
        self._errand_told = False
        super().__init__( args, *rest, **kw )

    def _errand_tell( self ):
        rc = self.returncode
        if rc and not self._errand_told:
            self._errand_told = True
            took = time.monotonic() - self._errand_t0
            cmd = self._errand_cmd if len( self._errand_cmd ) <= 160 else self._errand_cmd[ : 157 ] + "..."
            _say( f"✗ exit {rc} after {took:.1f} s: {cmd}" )

    def wait( self, timeout = None ):
        rc = super().wait( timeout )
        self._errand_tell()
        return rc

    def poll( self ):
        rc = super().poll()
        if rc is not None:
            self._errand_tell()
        return rc
