"""Warm imports ( ADR 0005, step 7 ): a session forked from a process that has already imported.

    python <errand> -m errand.agents.warm session '<request>'     what an environment agent starts
    python <errand> -m errand.agents.warm zygote <dir> <keep>      started by the first of those

A **zygote** lives beside an environment agent, in its environment. It never
runs anybody's code: it imports, and it forks. A session asks it for a fork,
handing over its stdin, stdout and stderr; the fork becomes the session, with
everything the zygote had imported already in memory -- torch, jax, a C++
extension -- and its own copy of all of it: nothing it does reaches the zygote
or the next session.

What to import is learned: a session that ends says which modules it used,
the project's own aside ( those are read again by every session, as they may
have changed ), and the zygote imports them between two requests. Never a
module whose import starts threads: forking a process with threads leaves the
fork with locks held by threads it does not have. A module whose file changes
under it makes the zygote go, once nothing it forked is still running; the
next session starts another.

A fork's random generators are its own: numpy's and torch's are seeded again.

The client ( `session` ) passes signals on to the fork's process group, and
when it is killed outright the zygote sees its connection close and kills the
fork. Anywhere this cannot work -- no fork, no zygote that will start,
`ERRAND_WARM=0` -- the session runs here, cold, as before.
"""
from __future__ import annotations

import array
import json
import os
import select
import signal
import socket
import sys
import time
from pathlib import Path

WAIT = 20.0                 # seconds a session waits for a zygote it started
MARK_FDS = 3


# ── the session's side ───────────────────────────────────────────────────────

def _cold( request: dict ) -> int:
    from .ops import session
    return session( request )


def _send_fds( sock, data: bytes, fds ):
    sock.sendmsg( [ data ], [ ( socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array( "i", fds ) ) ] )


def _recv_fds( sock, size: int, count: int ):
    fds = array.array( "i" )
    data, anc, _, _ = sock.recvmsg( size, socket.CMSG_SPACE( count * fds.itemsize ) )
    for level, kind, payload in anc:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            fds.frombytes( payload[ : len( payload ) - ( len( payload ) % fds.itemsize ) ] )
    return data, list( fds )


def _lines( sock ):
    buf = b""
    while True:
        while b"\n" in buf:
            line, buf = buf.split( b"\n", 1 )
            yield json.loads( line.decode() )
        got = sock.recv( 4096 )
        if not got:
            return
        buf += got


def _reach( where: Path ):
    s = socket.socket( socket.AF_UNIX, socket.SOCK_STREAM )
    try:
        s.connect( str( where / "sock" ) )
        return s
    except OSError:
        s.close()
        return None


def _start_zygote( where: Path, keep: float ):
    """Detached, like an agent: a session of its own, its output in a log."""
    where.mkdir( parents = True, exist_ok = True )
    if os.fork():
        return
    os.setsid()
    if os.fork():
        os._exit( 0 )
    log = os.open( str( where / "log" ), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600 )
    null = os.open( os.devnull, os.O_RDONLY )
    for fd, to in ( ( null, 0 ), ( log, 1 ), ( log, 2 ) ):
        os.dup2( fd, to )
    os.execv( sys.executable, [ sys.executable, *_boot(), "zygote", str( where ), str( keep ) ] )


def _boot() -> list:
    """How this process was started, to start the zygote the same way: `_boot.py -m errand.agents.warm`."""
    boot = Path( __file__ ).resolve().parent.parent / "_boot.py"
    return [ str( boot ), "-m", "errand.agents.warm" ]


def session( request: dict ) -> int:
    agent = os.environ.get( "ERRAND_AGENT_DIR" )
    if not request.get( "warm", True ) or os.environ.get( "ERRAND_WARM" ) == "0" or not agent \
            or not hasattr( os, "fork" ) or not hasattr( socket, "AF_UNIX" ):
        return _cold( request )
    where = Path( agent ) / "warm"
    sock = _reach( where )
    if sock is None:
        _start_zygote( where, float( request.get( "keep_alive" ) or 900 ) )
        deadline = time.monotonic() + WAIT
        while sock is None and time.monotonic() < deadline:
            time.sleep( 0.05 )
            sock = _reach( where )
        if sock is None:
            return _cold( request )
    try:
        _send_fds( sock, json.dumps( { "request": request, "cwd": os.getcwd(),
                                       "env": dict( os.environ ) } ).encode() + b"\n", [ 0, 1, 2 ] )
        said = _lines( sock )
        pid = next( said ).get( "pid" )
    except ( OSError, StopIteration, ValueError ):
        sock.close()
        return _cold( request )

    def forward( sig, _ ):
        try:
            os.killpg( pid, sig )
        except ( ProcessLookupError, PermissionError ):
            pass

    for sig in ( signal.SIGINT, signal.SIGTERM, signal.SIGHUP ):
        signal.signal( sig, forward )
    try:
        for m in said:
            if "code" in m:
                return int( m[ "code" ] )
    except OSError:
        pass
    forward( signal.SIGKILL, None )             # the zygote went: so does what it forked
    return 1


# ── the zygote ───────────────────────────────────────────────────────────────

def _rss_mb() -> float:
    """What this process holds in memory, in MB."""
    try:
        pages = int( Path( "/proc/self/statm" ).read_text().split()[ 1 ] )
        return pages * os.sysconf( "SC_PAGE_SIZE" ) / ( 1 << 20 )
    except ( OSError, ValueError, IndexError ):
        import resource
        peak = resource.getrusage( resource.RUSAGE_SELF ).ru_maxrss
        return peak / ( 1 << 20 ) if sys.platform == "darwin" else peak / 1024


def _blas() -> bool:
    """Is an OpenBLAS mapped in this process? Its thread pool, started when it is loaded, survives a
    fork: OpenBLAS stops it before one and starts it again after ( pthread_atfork ), which is what
    `multiprocessing` has relied on all along."""
    try:
        return "openblas" in Path( "/proc/self/maps" ).read_text().lower()
    except OSError:
        return False


def _threads() -> int:
    """Native threads of this process: what makes a fork unsafe."""
    task = Path( "/proc/self/task" )
    if task.is_dir():
        return len( list( task.iterdir() ) )
    import threading
    return threading.active_count()


class Zygote:
    def __init__( self, where: Path, keep: float ):
        self.where, self.keep = where, keep
        self.children : dict = { }        # pid -> the connection that asked for it
        self.idle_since = time.monotonic()
        self.loaded : dict = { }          # module -> ( file, mtime ) at import
        self.state = self._read_state()
        self.claim, self.claimed, self.touched, self.claim_lost = None, 0.0, 0.0, False

    def _read_state( self ) -> dict:
        try:
            return json.loads( ( self.where / "modules.json" ).read_text() )
        except ( OSError, ValueError ):
            return { "want": [ ], "never": [ ] }

    def _save_state( self ):
        ( self.where / "modules.json" ).write_text( json.dumps( self.state ) )

    # -- learning what to import --------------------------------------------

    def _learn( self ):
        for f in sorted( self.where.glob( "learned-*.json" ) ):
            try:
                names = json.loads( f.read_text() )
            except ( OSError, ValueError ):
                names = [ ]
            f.unlink()
            known = set( self.state[ "want" ] ) | set( self.state[ "never" ] )
            self.state[ "want" ] += [ n for n in names if n not in known ]
        self._save_state()

    def _preload_one( self ) -> bool:
        """Import the next wanted module. -> False when this zygote may no longer fork."""
        for name in self.state[ "want" ]:
            if name in self.loaded or name in self.state[ "never" ]:
                continue
            before, blas = _threads(), _blas()
            try:
                __import__( name )
            except BaseException:
                self.state[ "never" ].append( name )
                self._save_state()
                return True
            module = sys.modules.get( name )
            path = getattr( module, "__file__", None )
            try:
                self.loaded[ name ] = ( path, os.stat( path ).st_mtime if path else None )
            except OSError:
                self.loaded[ name ] = ( None, None )
            if _threads() > before and not ( _blas() and not blas ):
                # it started threads -- other than an OpenBLAS's, which a fork handles: never again,
                # and this zygote, which has them now, goes
                self.state[ "never" ].append( name )
                self._save_state()
                return False
            return True
        return True

    def _wanting( self ) -> bool:
        return any( n not in self.loaded and n not in self.state[ "never" ] for n in self.state[ "want" ] )

    def _stale( self ) -> bool:
        for name, ( path, mtime ) in self.loaded.items():
            if path and mtime is not None:
                try:
                    if os.stat( path ).st_mtime != mtime:
                        return True
                except OSError:
                    return True
        return False

    # -- forking ------------------------------------------------------------

    def _fork( self, conn ):
        data, fds = _recv_fds( conn, 1 << 20, MARK_FDS )
        while not data.endswith( b"\n" ):
            more = conn.recv( 1 << 20 )
            if not more:
                break
            data += more
        asked = json.loads( data.decode() )
        named = [ n for n in asked[ "request" ].get( "preload" ) or [ ]
                  if n not in self.state[ "want" ] and n not in self.state[ "never" ] ]
        if named:                          # what the layer names is wanted from now on
            self.state[ "want" ] = named + self.state[ "want" ]
            self._save_state()
        pid = os.fork()
        if pid == 0:
            self._child( asked, fds )
        for fd in fds:
            os.close( fd )
        self.children[ pid ] = conn
        conn.sendall( json.dumps( { "pid": pid } ).encode() + b"\n" )

    def _child( self, asked, fds ):
        code = 1
        try:
            os.setsid()
            for fd, to in zip( fds, ( 0, 1, 2 ) ):
                os.dup2( fd, to )
            for fd in fds:
                os.close( fd )
            self.server.close()
            for c in self.children.values():
                c.close()
            signal.set_wakeup_fd( -1 )
            for sig in ( signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGCHLD ):
                signal.signal( sig, signal.SIG_DFL )
            signal.signal( signal.SIGINT, signal.default_int_handler )
            os.chdir( asked[ "cwd" ] )
            os.environ.clear()
            os.environ.update( asked[ "env" ] )
            sys.stdout = os.fdopen( 1, "w", buffering = 1 )
            sys.stderr = os.fdopen( 2, "w", buffering = 1 )
            _reseed()
            from .ops import session
            code = session( asked[ "request" ] )
        except SystemExit as e:
            code = e.code if isinstance( e.code, int ) else 1
        except KeyboardInterrupt:
            code = 130
        except BaseException:
            import traceback
            traceback.print_exc()
        finally:
            try:
                if asked[ "request" ].get( "learn", True ):
                    _tell( self.where, asked[ "cwd" ] )
                sys.stdout.flush()
                sys.stderr.flush()
            except BaseException:
                pass
            os._exit( code )

    def _reap( self ):
        while self.children:
            try:
                pid, status = os.waitpid( -1, os.WNOHANG )
            except ChildProcessError:
                return
            if pid == 0:
                return
            conn = self.children.pop( pid, None )
            code = os.waitstatus_to_exitcode( status ) if hasattr( os, "waitstatus_to_exitcode" ) else \
                ( os.WEXITSTATUS( status ) if os.WIFEXITED( status ) else -os.WTERMSIG( status ) )
            if conn is not None:
                try:
                    conn.sendall( json.dumps( { "code": code } ).encode() + b"\n" )
                except OSError:
                    pass
                conn.close()

    def run( self ) -> int:
        from .endpoint import hold
        self.where.mkdir( parents = True, exist_ok = True )
        held = hold( self.where / "lock" )
        if held is None:
            return 0
        path = self.where / "sock"
        if path.exists():
            path.unlink()
        self.server = socket.socket( socket.AF_UNIX, socket.SOCK_STREAM )
        self.server.bind( str( path ) )
        os.chmod( path, 0o600 )
        self.server.listen( 16 )
        # A child that ends wakes the loop at once: its code is somebody's command waiting to end.
        self.wake, w = os.pipe()
        os.set_blocking( w, False )
        signal.set_wakeup_fd( w )
        signal.signal( signal.SIGCHLD, lambda *_: None )
        self._learn()
        try:
            while True:
                conns = [ c for c in self.children.values() ]
                ready, _, _ = select.select( [ self.server, self.wake, *conns ], [ ], [ ], 1.0 )
                for r in ready:
                    if r == self.wake:
                        os.read( self.wake, 512 )
                    elif r is self.server:
                        conn, _ = self.server.accept()
                        self.idle_since = time.monotonic()
                        self._fork( conn )
                    else:
                        # a client that went before its fork: Ctrl-C's last word, SIGKILL
                        try:
                            gone = not r.recv( 1, socket.MSG_PEEK )
                        except OSError:
                            gone = True
                        if gone:
                            for pid, c in list( self.children.items() ):
                                if c is r:
                                    try:
                                        os.killpg( pid, signal.SIGKILL )
                                    except ( ProcessLookupError, PermissionError ):
                                        pass
                self._reap()
                self._breathe()
                if self.children:
                    self.idle_since = time.monotonic()
                    continue
                if [ r for r in ready if r != self.wake ]:
                    continue
                # What it holds is only kept warm: counted in the machine's queue, and given up
                # as soon as somebody needs the room.
                if not self._hold_room():
                    break
                # idle: learn, import what is wanted -- until somebody asks for a fork -- or go
                self._learn()
                if self._stale():
                    break
                fit = True
                while fit and self._wanting() and not select.select( [ self.server ], [ ], [ ], 0 )[ 0 ]:
                    fit = self._preload_one()
                if not fit:
                    break
                if time.monotonic() - self.idle_since > self.keep:
                    break
        finally:
            self.server.close()
            if path.exists():
                path.unlink()
            if self.claim is not None:
                from .. import queue
                queue.release( self.claim )
            held.close()
        return 0

    def _hold_room( self ) -> bool:
        """-> False when this zygote should go: no room for it, or somebody asked for the room."""
        from .. import queue
        rss = _rss_mb()
        if self.claim is None:
            self.claim = queue.try_claim( { "ram": f"{int( rss )}M" }, label = f"zygote {self.where.parent.name}" )
            if self.claim is None and not queue.someone_else_is_scheduling() and not os.environ.get( queue.CLAIM ) \
                    and not os.environ.get( "ERRAND_NO_QUEUE" ):
                return False                       # no room to keep anything warm
            self.claimed = rss
        elif rss > self.claimed * 1.1 + 50:
            queue.resize( self.claim, ram = f"{int( rss )}M" )
            self.claimed = rss
        if self.claim is not None and ( self.claim_lost or queue.evicted( self.claim ) ):
            return False                           # taken for dead meanwhile, or asked for the room
        return True

    def _breathe( self ):
        """The claim is touched every turn of the loop, sessions running or not: a claim nobody
        touches for half a minute is taken for dead."""
        if self.claim is None:
            return
        from .. import queue
        now = time.monotonic()
        if now - self.touched > 5:
            self.touched = now
            self.claim_lost = not queue.touch( self.claim )


def _reseed():
    """A fork's random generators are its own: Python's `random` is reseeded by the fork itself."""
    np = sys.modules.get( "numpy" )
    if np is not None:
        try:
            np.random.seed()
        except Exception:
            pass
    torch = sys.modules.get( "torch" )
    if torch is not None:
        try:
            torch.seed()
        except Exception:
            pass


def _tell( where: Path, root: str ):
    """What this session imported that a zygote could import ahead: not the project's own, not errand's
    scan of it, not what was already there."""
    root = os.path.realpath( root )
    names = [ ]
    for name, module in list( sys.modules.items() ):
        if name.startswith( ( "_errand_scan", "__main__" ) ) or module is None:
            continue
        path = getattr( module, "__file__", None )
        if path and os.path.realpath( path ).startswith( root + os.sep ):
            continue
        names.append( name )
    ( where / f"learned-{os.getpid()}.json" ).write_text( json.dumps( sorted( names ) ) )


def main( argv = None ) -> int:
    argv = list( sys.argv[ 1 : ] if argv is None else argv )
    if len( argv ) == 2 and argv[ 0 ] == "session":
        return session( json.loads( argv[ 1 ] ) )
    if len( argv ) == 3 and argv[ 0 ] == "zygote":
        return Zygote( Path( argv[ 1 ] ), float( argv[ 2 ] ) ).run()
    print( "usage: python -m errand.agents.warm session REQUEST | zygote DIR KEEP", file = sys.stderr )
    return 2


if __name__ == "__main__":
    sys.exit( main() )
