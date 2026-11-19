"""The keeper of a run's streams: what the process writes to its descriptors 1 and 2, copied to
`stdout.txt` and `stderr.txt` in the run's directory, and passed on to where they went before.

A process of its own ( `streams.raw` starts it ), so that it outlives the run's: a segfault, an
abort, a kill leave in the files everything that was written up to the end -- the very lines that
say why. Then, when the run never said it was over ( its control pipe closed without `done` ), the
keeper writes the record the run could not: `result.yaml`, prepared by the run when it started.

Run as `python -S _keeper.py OUT_FD ERR_FD STDOUT_PATH STDERR_PATH RESULT_PATH [OUTPUT_PATH OUT_GUTTER ERR_GUTTER]`,
its control pipe on stdin. `OUTPUT_PATH` ( `output.txt` ), when not empty, gets both streams as they
came, interleaved ( ADR 0016 ). The gutters are put before each line it passes on, never in the files.
The descriptors may be a pipe's or a pseudo-terminal's ( `streams._start` ): one ends with EOF, the other
with an error once every writer is gone; both end the copy. Standard library only, and nothing of
errand: it starts in a few milliseconds.
"""
import os
import re
import signal
import sys
import threading

DONE = b"\0done"
LINGER = 5.0          # after the end, what a child left holding the pipes may still say


_SGR = re.compile( rb"\x1b\[[0-9;]*m" )
_MARK = b"\x1eerrand-op "                         # `agents.ops.MARK`
_MARKS = re.compile( rb"\x1eerrand-op [^\n]*\n?" )


def guttered( chunk: bytes, gutter: bytes, state: list ) -> bytes:
    """`chunk` with `gutter` at the start of each line ( after a `\r` too: a bar redrawn in place ).
    `state`: [ whether the last chunk ended a line, the program's color in force ], the color put back
    after the gutter, which ends with its own reset."""
    out = bytearray()
    for piece in re.split( rb"(\r\n|\n|\r)", chunk ):
        if not piece:
            continue
        if piece in ( b"\n", b"\r\n", b"\r" ):
            if state[ 0 ] and piece != b"\r":
                out += gutter.rstrip()     # an empty line keeps the column of its block
            state[ 0 ] = True
        else:
            if state[ 0 ]:
                out += gutter + state[ 1 ]
                state[ 0 ] = False
            for m in _SGR.finditer( piece ):
                state[ 1 ] = b"" if m.group() in ( b"\x1b[0m", b"\x1b[m" ) else state[ 1 ] + m.group()
        out += piece
    return bytes( out )


class _Stream:
    """One of the two: its file, where it is passed on, behind which gutter, and where its line is."""

    def __init__( self, path: str, dst: int, gutter: bytes ):
        self.file, self.dst, self.gutter = open( path, "wb", buffering = 0 ), dst, gutter
        self.state = [ True, b"" ]          # ( at the start of a line, the program's color in force )


def pump( streams: dict, ended: threading.Event, merged = None ):
    """Both streams in one loop, in the order they come: into their files ( and `merged`, both as they
    came ), on to where they went behind their gutters ( ADR 0016 ). With gutters, a line the other
    stream left open is ended first: a stderr line never lands at the end of a progress bar."""
    import select
    last = None
    open_fds = set( streams )
    while open_fds:
        try:
            ready, _, _ = select.select( list( open_fds ), [ ], [ ] )
        except InterruptedError:
            continue
        for fd in ready:
            try:
                chunk = os.read( fd, 65536 )
            except OSError:
                chunk = b""                # a pseudo-terminal whose writers are all gone
            if not chunk:
                open_fds.discard( fd )
                continue
            s = streams[ fd ]
            kept = _MARKS.sub( b"", chunk ) if _MARK in chunk else chunk      # a session's marks: not output
            s.file.write( kept )
            if merged is not None:
                merged.write( kept )
            out = chunk
            if s.gutter:
                other = streams.get( last )
                lead = b""
                if other is not None and other is not s and not other.state[ 0 ]:
                    lead, other.state[ 0 ] = b"\n", True
                out = lead + guttered( chunk, s.gutter, s.state )
            last = fd
            try:
                os.write( s.dst, out )
            except OSError:
                pass                       # nobody reads over there any more: the file still keeps it
    for s in streams.values():
        s.file.close()
    ended.set()


def main( argv ) -> int:
    # Ctrl-C goes to the whole group: the run handles it and says so, the keeper keeps copying.
    signal.signal( signal.SIGINT, signal.SIG_IGN )
    out_fd, err_fd, out_path, err_path, result = int( argv[ 0 ] ), int( argv[ 1 ] ), argv[ 2 ], argv[ 3 ], argv[ 4 ]
    merged = None
    if len( argv ) > 5 and argv[ 5 ]:
        try:
            merged = open( argv[ 5 ], "wb", buffering = 0 )
        except OSError:
            merged = None              # the two files still keep everything
    gutters = [ g.encode() for g in argv[ 6 : 8 ] ] + [ b"", b"" ]      # optional: the gutter of each stream
    ended = threading.Event()
    streams = { out_fd: _Stream( out_path, 1, gutters[ 0 ] ), err_fd: _Stream( err_path, 2, gutters[ 1 ] ) }
    threading.Thread( target = pump, args = ( streams, ended, merged ), daemon = True ).start()
    control = b""
    while True:
        chunk = os.read( 0, 65536 )
        if not chunk:
            break
        control += chunk
    ended.wait( LINGER )
    if control.endswith( DONE ) or not control:
        return 0
    # The run ended without a word: its record, so that it reads as what it was.
    if not os.path.exists( result ):
        part = os.path.join( os.path.dirname( result ), "." + os.path.basename( result ) + ".part" )
        with open( part, "wb" ) as f:
            f.write( control )
        os.replace( part, result )
    return 0


if __name__ == "__main__":
    sys.exit( main( sys.argv[ 1 : ] ) )
