"""The keeper of a run's streams: what the process writes to its descriptors 1 and 2, copied to
`stdout.txt` and `stderr.txt` in the run's directory, and passed on to where they went before.

A process of its own ( `streams.raw` starts it ), so that it outlives the run's: a segfault, an
abort, a kill leave in the files everything that was written up to the end -- the very lines that
say why. Then, when the run never said it was over ( its control pipe closed without `done` ), the
keeper writes the record the run could not: `result.yaml`, prepared by the run when it started.

Run as `python -S _keeper.py OUT_FD ERR_FD STDOUT_PATH STDERR_PATH RESULT_PATH`, its control pipe
on stdin. Standard library only, and nothing of errand: it starts in a few milliseconds.
"""
import os
import signal
import sys
import threading

DONE = b"\0done"
LINGER = 5.0          # after the end, what a child left holding the pipes may still say


def copy( src: int, path: str, dst: int, ended: threading.Event ):
    with open( path, "wb", buffering = 0 ) as f:
        while True:
            try:
                chunk = os.read( src, 65536 )
            except OSError:
                break
            if not chunk:
                break
            f.write( chunk )
            try:
                os.write( dst, chunk )
            except OSError:
                pass                       # nobody reads over there any more: the file still keeps it
    ended.set()


def main( argv ) -> int:
    # Ctrl-C goes to the whole group: the run handles it and says so, the keeper keeps copying.
    signal.signal( signal.SIGINT, signal.SIG_IGN )
    out_fd, err_fd, out_path, err_path, result = int( argv[ 0 ] ), int( argv[ 1 ] ), argv[ 2 ], argv[ 3 ], argv[ 4 ]
    ends = [ threading.Event(), threading.Event() ]
    for src, path, dst, ended in ( ( out_fd, out_path, 1, ends[ 0 ] ), ( err_fd, err_path, 2, ends[ 1 ] ) ):
        threading.Thread( target = copy, args = ( src, path, dst, ended ), daemon = True ).start()
    control = b""
    while True:
        chunk = os.read( 0, 65536 )
        if not chunk:
            break
        control += chunk
    for e in ends:
        e.wait( LINGER )
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
