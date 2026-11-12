"""What every layer works with: a command, the context it is composed in, folding a stack,
fingerprints, and replacing the interpreter ( `under` ).
"""
from __future__ import annotations

import hashlib
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .. import trace


@dataclass
class Command:
    argv: list
    env : dict = field( default_factory = dict )

    def shell( self ) -> str:
        assigns = [ f"{k}={shlex.quote( str( v ) )}" for k, v in self.env.items() ]
        return " ".join( assigns + [ shlex.quote( str( a ) ) for a in self.argv ] )


@dataclass
class Context:
    """What a layer needs to know that is not its own business."""
    root  : Path
    tags  : dict = field( default_factory = dict )   # the SELECTED tags
    remote: bool = False
    # What the work about to run asks of a machine, aggregated over the entries
    # this command carries. Only a layer that can ASK somebody for it -- a batch
    # system -- has any use for it.
    needs : dict = field( default_factory = dict )
    # `--batch`: let go rather than wait. Only a layer that has two ways of
    # starting something -- a batch system -- has anything to do with it.
    batch : bool = False
    # `errand shell` with no command: somebody types into it. Only a layer that
    # stands between the terminal and the command -- ssh, a container engine, a
    # batch system -- has to be told to hand the terminal on.
    interactive: bool = False
    # Which pass this is: `prepare` resolves, builds and collects, `run` runs.
    # A scheduler sizes the second from the plan the first wrote.
    phase : str = "run"
    # Where a layer's OWN work runs -- booting a machine, copying into it --
    # as opposed to the command it wraps: whatever the layers before it lead
    # to. `Here` for the first layer; `Ssh` hands the next ones `Over`.
    host  : object = None
    # The project as THIS process sees it, wherever `root` is: what a layer
    # reads to know what it was declared with ( a script, a recipe ), since the
    # reading is done here even when the doing is not.
    origin: Path | None = None

    def __post_init__( self ):
        if self.host is None:
            self.host = Here( self.root )
        if self.origin is None:
            self.origin = self.root


def compose( stack, cmd: Command, ctx: Context ) -> Command:
    """Fold innermost-first: [ A, B, C ] -> A( B( C( cmd ) ) )."""
    for layer in reversed( stack ):
        cmd = layer.wrap( cmd, ctx )
    return cmd


def fingerprint( *parts ) -> str:
    """What a built environment is compared against to notice it has drifted."""
    h = hashlib.sha256()
    for part in parts:
        if isinstance( part, Path ):
            try:
                h.update( part.read_bytes() )
                continue
            except OSError:
                part = f"<missing {part}>"
        h.update( repr( part ).encode() )
    return h.hexdigest()[ : 16 ]


def sh( argv ) -> str:
    return " ".join( shlex.quote( str( a ) ) for a in argv )


# A stamp is what a built thing looks like from outside, read right after its
# build and compared later: the fingerprint says what it was built FROM, the
# stamp that it is still the thing that was built. A cheap observation rather
# than a checksum -- hashing 4 GB on every run is not an option, and a conda
# prefix has no single content. By convention it starts with the date it was
# last written, as an epoch; a layer whose stamp does not has a `made( stamp )`.

def file_stamp( word ) -> str:
    """A shell line printing the date and size of a file, `word` being how the
    shell is to read its name: GNU's stat, else BSD's."""
    return f"stat -c '%Y %s' {word} || stat -f '%m %z' {word}"


# An environment's packages all land in one directory, whichever installed them.
SITE_STAMP = ( "import os, sysconfig; s = os.stat( sysconfig.get_paths()[ 'purelib' ] ); "
               "print( int( s.st_mtime ), s.st_nlink )" )


# Every step a layer asks for is run FROM THE PROJECT ROOT -- this one when it
# is built here, the remote one when it is built over there. So a step names
# what it needs the way the project declares it: `containers/cuda.sif`, not
# `/home/me/proj/containers/cuda.sif`, which is a path that exists on exactly
# one of the two machines.


INTERPRETERS = ( "python", "python3", "python2" )


def under( argv, python ):
    """`argv` with its interpreter replaced by `python`, when it HAS one.

    Every layer's job is to run the work with the interpreter of the place it
    describes -- a venv's python, the one inside the container. But a command
    is not always an interpreter call ( `errand shell --env gpu -- nvidia-smi` ), and
    substituting the first word blindly turns that one into `python
    nvidia-smi`. So: a first word that names an interpreter is replaced; any
    other is a command in its own right and is kept.
    """
    first = str( argv[ 0 ] ) if argv else ""
    if Path( first ).name in INTERPRETERS or first == sys.executable:
        return [ python, *argv[ 1 : ] ]
    return list( argv )


def _install_steps( pip_argv, layer, ctx ):
    steps = [ ]
    if layer.requirements:
        steps.append( sh( [ *pip_argv, "-r", layer.requirements ] ) )
    if layer.pip:
        steps.append( sh( [ *pip_argv, *layer.pip ] ) )
    return steps


def _quiet( argv ) -> bool:
    try:
        silent = { } if trace.enabled() else dict( stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL )
        return subprocess.run( argv, **silent ).returncode == 0
    except OSError:
        return False


#
# Most layers only rewrite the command. A few must DO something before it can
# run -- build an image, boot a machine, copy the project into it -- and where
# that happens is not their business: it is wherever the layers before them
# lead. So it is handed down, as `ctx.host`: a way to run a shell line THERE
# and read what it answered. The deciding stays in this process; only the
# doing goes over there, one line at a time, as many as it takes.
#
#     shell( line, capture =, quiet =, input =, timeout =, tty = )
#                     -> a CompletedProcess, from the project root of that place

def _how( quiet, capture, input ) -> dict:
    how = { }
    if capture:
        how.update( capture_output = True, text = True )
    elif quiet and not trace.enabled():
        # `-v` keeps what a probe says: when it fails, that is the why.
        how.update( stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL )
    if input is not None:
        how.update( input = input, text = True )
    elif capture or quiet:
        # Asked, not watched: it must not read the terminal's keystrokes --
        # ssh would, and swallow what was typed for something else.
        how.update( stdin = subprocess.DEVNULL )
    return how


class Here:
    """This machine, from the project root: what the first layer is handed."""
    remote = False

    def __init__( self, root ):
        self.root = Path( root )

    def shell( self, line: str, *, quiet = False, tty = False, capture = False, input = None,
               timeout = None ):
        return subprocess.run( [ "sh", "-c", line ], cwd = str( self.root ), timeout = timeout,
                               **_how( quiet, capture, input ) )

    def describe( self ):
        return "here"

    def spec( self ) -> dict:
        return { "here": str( self.root ) }
