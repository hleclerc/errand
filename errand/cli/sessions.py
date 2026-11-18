"""Sessions as this side sees them: what one prints is shown, what it marks is read, and Ctrl-C stops it.

A session ( `agents/ops.py` ) runs where the environment is, and is reached in
one of three ways, which only differ in how its output arrives:

    Session         started by an agent ( an environment's, or a host's for a scheduler
                    in the foreground ): its output streamed over the agent's channel
    LocalSession    a process here ( a scheduler on this machine ): its pipes
    WatchedSession  a job submitted and then asked about ( `Slurm( watch = … )` ): its log

All three hand the marks to `follow`, which keeps the report.
"""
from __future__ import annotations

import json
import os
import queue as Q
import signal
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

from .. import agents, layers as L
from ..agents import frames as F
from ..agents.ops import MARK
from .here import tally
from .style import bad

_MARK = MARK.encode()
INTERRUPTED = 130
STDERR_KEPT = 64 * 1024


class Marked:
    """Output with marks in it: the marks are taken out and queued, the rest is shown."""

    def __init__( self ):
        self.marks = Q.Queue()
        self._held = b""
        self.stderr_tail = b""         # the last of what it wrote on stderr: said if it dies

    def _out( self, payload: bytes, end = False ):
        data = self._held + payload
        self._held = b""
        while data:
            at = data.find( _MARK )
            if at < 0:
                # a mark may begin at the very end of this chunk: hold that much back
                keep = next( ( k for k in range( min( len( _MARK ) - 1, len( data ) ), 0, -1 )
                               if _MARK.startswith( data[ -k : ] ) ), 0 ) if not end else 0
                self._show( data[ : len( data ) - keep ] )
                self._held = data[ len( data ) - keep : ]
                return
            self._show( data[ : at ] )
            nl = data.find( b"\n", at )
            if nl < 0:
                self._held = data[ at : ]
                return
            self.marks.put( json.loads( data[ at + len( _MARK ) : nl ].decode() ) )
            data = data[ nl + 1 : ]

    @staticmethod
    def _show( data: bytes ):
        if data:
            sys.stdout.buffer.write( data )
            sys.stdout.flush()

    def _err( self, data: bytes ):
        self.stderr_tail = ( self.stderr_tail + data )[ -STDERR_KEPT : ]
        sys.stderr.buffer.write( data )
        sys.stderr.flush()

    def next( self ) -> dict:
        return self.marks.get()


class Session( Marked ):
    """Started by an agent, and kept: it outlives this process ( `agents.start` )."""

    def __init__( self, conn, pid: str, store = None ):
        super().__init__()
        self.conn, self.pid = conn, pid
        self.call = agents.attach( conn, pid, store = store )
        threading.Thread( target = self._pump, daemon = True ).start()

    @classmethod
    def start( cls, conn, argv, *, cwd = None, env = None, store = None ):
        return cls( conn, agents.start( conn, argv, cwd = cwd, env = env, store = store ), store )

    def _pump( self ):
        try:
            while True:
                kind, payload = self.call.next()
                if kind == F.OUT:
                    self._out( payload )
                elif kind == F.ERR:
                    self._err( payload )
                elif kind == F.EXIT:
                    self._out( b"", end = True )
                    self.marks.put( { "op": "exit", **F.load( payload ) } )
                    return
        except agents.Lost:
            self.marks.put( { "op": "lost" } )

    def stop( self ):
        self.stop_delivered = agents.client.stop( self.call )


class LocalSession( Marked ):
    """A process of this machine: it goes with this one."""

    def __init__( self, argv, *, cwd = None, env = None ):
        super().__init__()
        self.pid = None
        self.proc = subprocess.Popen( argv, cwd = cwd, env = { **os.environ, **( env or { } ) },
                                      stdout = subprocess.PIPE, stderr = subprocess.PIPE,
                                      stdin = subprocess.DEVNULL, start_new_session = True )
        threading.Thread( target = self._pump_err, daemon = True ).start()
        threading.Thread( target = self._pump, daemon = True ).start()

    def _pump_err( self ):
        for chunk in iter( lambda: os.read( self.proc.stderr.fileno(), 65536 ), b"" ):
            self._err( chunk )

    def _pump( self ):
        for chunk in iter( lambda: os.read( self.proc.stdout.fileno(), 65536 ), b"" ):
            self._out( chunk )
        self._out( b"", end = True )
        self.marks.put( { "op": "exit", "code": self.proc.wait() } )

    def stop( self ):
        def send( sig ):
            try:
                os.killpg( self.proc.pid, sig )
            except ( ProcessLookupError, PermissionError ):
                pass
        send( signal.SIGINT )
        for after, sig in zip( agents.client.GRACE, ( signal.SIGTERM, signal.SIGKILL ) ):
            threading.Timer( after, send, args = ( sig, ) ).start()


class WatchedSession( Marked ):
    """A job submitted, then asked about ( `layers.watch_job` ): its log is its output."""

    def __init__( self, host, submit, log: str, every: float, echo ):
        super().__init__()
        self.pid = None
        self.cancel = threading.Event()

        def run():
            # Whatever happens to the watcher, its end is said: a thread that dies silently leaves its
            # command waiting for ever, and the job unwatched.
            code = 1
            try:
                code = L.watch_job( host, submit, log, every, echo = echo, show = lambda t: self._out( t.encode() ),
                                    cancel = self.cancel )
            except Exception as err:
                echo( f"  watching the slurm job failed: {err}" )
            finally:
                self._out( b"", end = True )
                self.marks.put( { "op": "exit", "code": code } )

        threading.Thread( target = run, daemon = True ).start()

    def stop( self ):
        self.cancel.set()                  # `watch_job` cancels the job ( scancel )


def _stub( entry: dict ):
    return SimpleNamespace( name = entry[ "name" ], file = Path( entry[ "file" ] ), line = entry[ "line" ] )


# The step of the case running, at the bottom of this terminal ( ADR 0010 ): one line for all
# the sessions followed, the last one that said something.
_footer = None


def _step( text ):
    global _footer
    from .footer import Footer
    if _footer is None:
        if not Footer.usable( sys.stdout ):
            return
        _footer = Footer( sys.stdout )
    _footer.show( text )


def follow( session, report, box: dict, relay = None, views = None ) -> int:
    """Read a session to its end: what it prepared, how each case went. -> its return code. `relay( want )`:
    what fetches a file a case asked up the chain for ( ADR 0013 ), on a thread of its own. `views( mark )`:
    what brings back a file a case shows ( `errand.view`, `views.Views` ) and says where it opens."""
    rc = 0
    running = None                     # the case under way: what a session that dies was doing
    while True:
        m = session.next()
        op = m.get( "op" )
        if op == "step":
            _step( m.get( "line" ) )
        elif op == "want":
            if relay is not None:
                threading.Thread( target = relay, args = ( m, ), daemon = True ).start()
        elif op == "view":
            if views is not None:
                views( m )
        elif op in ( "ran", "exit", "lost" ):
            _step( None )
        if op == "prepared":
            report.broken += [ ( Path( p ), why, "" ) for p, why in m[ "broken" ] ]
            rc |= m[ "rc" ]
            if m.get( "plan" ):
                box.update( m )
        elif op == "start":
            running = m.get( "entry" )
        elif op == "ran":
            running = None
            if m.get( "output" ):
                sys.stdout.write( m[ "output" ] )
                sys.stdout.flush()
            tally( report, _stub( m[ "entry" ] ), m[ "status" ], m[ "error" ], m[ "hint" ] )
        elif op == "done":
            box[ "done" ] = True
        elif op == "exit":
            code = m.get( "code" )
            if code and not box.get( "done" ):
                died( session, report, code, running )
            return rc or ( 1 if code and not box.get( "done" ) else 0 )
        elif op == "lost":
            box[ "lost" ] = True
            print( bad( "  the connection to the environment was lost: the work goes on over there "
                        "( errand attach )" ) )
            return 1


def died( session, report, code: int, running ):
    """A session that ended before its work: how ( its exit code, a signal ), in which case, and the
    last of what it said on stderr -- often all there is ( a segfault prints nothing else )."""
    from ..streams import ended, tail_of, with_tail
    how = ended( code )
    err = tail_of( getattr( session, "stderr_tail", b"" ).decode( errors = "replace" ) )
    where = f" in {running[ 'name' ]} ({running[ 'file' ]}:{running[ 'line' ]})" if running else ""
    print( bad( f"  the session over there ended ( {how} ){where}" ), flush = True )
    if err and not running:            # with a case, the report says it under the case
        print( "\n".join( f"    {l}" for l in [ "last lines of stderr:", *err.splitlines() ] ), flush = True )
    if running:
        tally( report, _stub( running ), "FAIL", with_tail( f"{how}: the process died during the run", err ), None )


def follow_all( sessions, report, boxes, relay = None, views = None ):
    """Every session to its end, each on a thread of its own. -> their return codes, or None after
    Ctrl-C: then each was stopped -- SIGINT, SIGTERM, SIGKILL, whatever it takes -- and is gone."""
    rcs = [ 0 ] * len( sessions )

    def one( i ):
        rcs[ i ] = follow( sessions[ i ], report, boxes[ i ], relay, views )

    threads = [ threading.Thread( target = one, args = ( i, ), daemon = True ) for i in range( len( sessions ) ) ]
    for t in threads:
        t.start()
    try:
        for t in threads:
            while t.is_alive():
                t.join( 0.25 )
    except KeyboardInterrupt:
        print( bad( "\n  interrupted: stopping it over there" ), flush = True )
        for s in sessions:
            s.stop()
        for t in threads:
            t.join( agents.client.GRACE[ -1 ] + 5 )
        return None
    return rcs
