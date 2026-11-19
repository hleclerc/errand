"""A run's raw streams: what its process writes to its descriptors 1 and 2, kept in its directory as
`stdout.txt` and `stderr.txt` -- the C library's writes, a child's, a fault handler's included.

`output.txt` is both of them, interleaved as they came, whoever wrote them ( ADR 0016 ): the keeper
writes it, and Python only where there is no keeper. These two are the streams as the operating system
saw them, apart: what is left to read when the process died without a word of
Python ( a segfault in an extension, an abort ), and the only place a child's stderr is not mixed
with everything else.

On POSIX they are copied by a process of their own ( `_keeper.py` ), which outlives the run's: what
was written before a crash is in the files, and when the run never said it was over, the keeper
writes its record ( `result.yaml` ) -- a FAIL that says so -- so that it comes back like any other.
Where descriptors cannot be redirected ( Windows ), or one of them is a terminal, which a pipe would
take the place of ( colors, progress bars ), what Python writes to `sys.stdout` and `sys.stderr` is
copied instead.
"""
from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from pathlib import Path

from . import results as R

KEEPER = Path( __file__ ).with_name( "_keeper.py" )
DONE = b"\0done"
TAIL = 20             # lines of stderr said when a process failed


def _flush( ):
    for s in ( sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__ ):
        try:
            s.flush()
        except Exception:
            pass


def _redirectable( ) -> bool:
    if os.name != "posix":
        return False
    try:
        return not os.isatty( 1 ) and not os.isatty( 2 )
    except OSError:
        return False


def _on_terminals( ) -> bool:
    """Both descriptors a terminal, on POSIX: the keeper can take them through pseudo-terminals, and
    what runs still sees a terminal ( colors, progress bars )."""
    if os.name != "posix":
        return False
    try:
        return os.isatty( 1 ) and os.isatty( 2 )
    except OSError:
        return False


@contextlib.contextmanager
def raw( leaf: Path, crashed: str | None = None, shows = None ):
    """`stdout.txt` and `stderr.txt` in `leaf` for what runs inside. `crashed`: the record to write
    in `leaf` if the process ends before leaving this block ( its `result.yaml`, rendered ). `shows`: what
    draws the case here ( `render.Renderer`, ADR 0016 ): what is passed on to the terminal goes behind
    its gutter, never what the files keep."""
    leaf = Path( leaf )
    _fault_handler()
    keeper = None
    if _redirectable():
        keeper = _start( leaf, crashed, shows )
    elif shows is not None and _on_terminals():
        keeper = _start( leaf, crashed, shows, terminals = True )
    if keeper is None:
        with _python_level( leaf, shows ):
            yield False                     # `output.txt` is Python's to write ( `style.capture` )
        return
    proc, ctrl, saved = keeper
    try:
        yield True                          # the keeper writes `output.txt`: both streams, whoever wrote them
    finally:
        _flush()
        for fd, old in zip( ( 1, 2 ), saved ):
            os.dup2( old, fd )
            os.close( old )
        try:
            # `done` either way: an exception, a Ctrl-C are said by the run, and it writes its record
            os.write( ctrl, DONE )
        except OSError:
            pass
        os.close( ctrl )
        try:
            proc.wait( timeout = 10 )
        except subprocess.TimeoutExpired:
            proc.kill()


def _fault_handler( ):
    """A crash in an extension says where it was, on descriptor 2: into `stderr.txt`."""
    import faulthandler
    if faulthandler.is_enabled():
        return
    try:
        faulthandler.enable( file = sys.__stderr__, all_threads = True )
    except Exception:
        pass                               # no descriptor to write to: nothing to say it with


def _terminal_pair( like: int, narrower: int ):
    """A pseudo-terminal as wide as the terminal `like` is, less the gutter, that changes no byte
    ( no `\r` added before `\n` ). -> ( the keeper's end, the run's end )."""
    import fcntl
    import struct
    import termios
    master, slave = os.openpty()
    try:
        attrs = termios.tcgetattr( slave )
        attrs[ 1 ] &= ~termios.OPOST
        termios.tcsetattr( slave, termios.TCSANOW, attrs )
        rows, cols, x, y = struct.unpack( "HHHH", fcntl.ioctl( like, termios.TIOCGWINSZ, b"\0" * 8 ) )
        fcntl.ioctl( slave, termios.TIOCSWINSZ, struct.pack( "HHHH", rows, max( 20, cols - narrower ), x, y ) )
    except OSError:
        pass                                 # a size it cannot tell: the default one
    return master, slave


def _start( leaf: Path, crashed, shows = None, terminals = False ):
    """The keeper started, and descriptors 1 and 2 handed to it -- through pipes, or `terminals`: two
    pseudo-terminals, for a run drawn on a terminal here. -> ( process, control fd, saved fds ), or None
    when it cannot be: the run goes on without."""
    try:
        if terminals:
            import re
            narrower = len( re.sub( r"\x1b\[[0-9;]*m", "", shows.gutter( False ) ) )
            r_out, w_out = _terminal_pair( 1, narrower )
            r_err, w_err = _terminal_pair( 2, narrower )
        else:
            r_out, w_out = os.pipe()
            r_err, w_err = os.pipe()
        r_ctl, w_ctl = os.pipe()
    except OSError:
        return None
    try:
        proc = subprocess.Popen( [ sys.executable, "-S", "-E", str( KEEPER ), str( r_out ), str( r_err ),
                                   str( leaf / R.STDOUT ), str( leaf / R.STDERR ), str( leaf / R.RESULT ),
                                   str( leaf / R.OUTPUT ),
                                   *( [ shows.gutter( False ), shows.gutter( True ) ] if shows is not None else [ ] ) ],
                                 # a Ctrl-C to the group leaves it copying to the end: it ignores SIGINT
                                 stdin = r_ctl, pass_fds = ( r_out, r_err ), close_fds = True )
    except OSError:
        for fd in ( r_out, w_out, r_err, w_err, r_ctl, w_ctl ):
            os.close( fd )
        return None
    for fd in ( r_out, r_err, r_ctl ):
        os.close( fd )
    if crashed:
        try:
            os.write( w_ctl, crashed.encode() )
        except OSError:
            pass
    _flush()
    saved = ( os.dup( 1 ), os.dup( 2 ) )
    for fd, w in ( ( 1, w_out ), ( 2, w_err ) ):
        os.dup2( w, fd )
        os.close( w )
    return proc, w_ctl, saved


class _Copy:
    """A stream that also writes to a file: where descriptors stay as they are. `shows`: the terminal's
    copy goes behind its gutter ( ADR 0016 )."""

    def __init__( self, stream, f, shows = None, err = False ):
        self._stream, self._f, self._shows, self._err = stream, f, shows, err

    def write( self, s ):
        try:
            self._f.write( s )
        except Exception:
            pass
        if self._shows is not None:
            self._shows.write( s, err = self._err )
            return len( s )
        return self._stream.write( s )

    def flush( self ):
        try:
            self._f.flush()
        except Exception:
            pass
        self._stream.flush()

    def __getattr__( self, name ):
        return getattr( self._stream, name )


@contextlib.contextmanager
def _python_level( leaf: Path, shows = None ):
    files = [ ]
    try:
        files = [ open( leaf / R.STDOUT, "w", buffering = 1, errors = "replace" ),
                  open( leaf / R.STDERR, "w", buffering = 1, errors = "replace" ) ]
    except OSError:
        for f in files:
            f.close()
        yield
        return
    old = sys.stdout, sys.stderr
    if shows is not None:
        shows.out_.stream, shows.err_.stream = old
    sys.stdout, sys.stderr = _Copy( old[ 0 ], files[ 0 ], shows ), _Copy( old[ 1 ], files[ 1 ], shows, True )
    try:
        yield
    finally:
        sys.stdout, sys.stderr = old
        for f in files:
            f.close()


# ── saying how a process ended ──────────────────────────────────────────────

def ended( code: int ) -> str:
    """`exit 3`, or `signal SIGSEGV` for a process a signal ended ( a negative code, as Python has it;
    128 + n, as a shell has it )."""
    n = -code if code < 0 else ( code - 128 if 128 < code < 128 + 65 and os.name == "posix" else 0 )
    if n:
        try:
            return f"signal {signal.Signals( n ).name}"
        except ValueError:
            return f"signal {n}"
    return f"exit {code}"


def tail( path: Path, lines: int = TAIL ) -> str:
    """The last lines of a file, as text: what a failure is said with."""
    try:
        with open( path, "rb" ) as f:
            f.seek( 0, os.SEEK_END )
            size = f.tell()
            f.seek( max( 0, size - 64 * 1024 ) )
            data = f.read()
    except OSError:
        return ""
    return tail_of( data.decode( errors = "replace" ), lines )


# The C stack a fault handler adds ( Python 3.14 on ): in the file whole, in a tail it would push out
# the Python frames that say where.
_C_STACK = ( "Binary file ", "Current thread's C stack trace", "<truncated rest of calls>" )


def tail_of( text: str, lines: int = TAIL ) -> str:
    kept = [ l.rstrip() for l in text.splitlines() if l.strip() and not l.strip().startswith( _C_STACK ) ]
    return "\n".join( kept[ -lines : ] )


def with_tail( error: str, stderr: str ) -> str:
    """A failure's reason, with the last lines of stderr under it."""
    if not stderr:
        return error
    return f"{error}\n  last lines of stderr:\n" + "\n".join( f"    {l}" for l in stderr.splitlines() )
