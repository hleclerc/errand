"""An agent: a process that stays, starts processes when asked, and outlives its clients.

It listens on a unix socket in its directory. Clients come and go, through the
`connect` bridge ( `daemon.py` ) or directly; what it started keeps running and
keeps writing to disk whoever is listening ( `procs.py` ). With no client and
nothing running for `keep_alive` seconds, it goes, and takes its socket with it.

One agent per directory: a lock held for its whole life says so.
"""
from __future__ import annotations

import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

from . import endpoint, frames as F, look
from .procs import finished, locate, Proc, sweep


class Agent:
    def __init__( self, root: Path, keep_alive: float ):
        self.root       = Path( root )
        self.keep_alive = keep_alive
        self.procs      : dict = { }        # id -> Proc
        self.clients    = 0
        self.idle_since = time.monotonic()
        self.lock       = threading.Lock()
        self.web        = None              # the page it serves, a host agent only ( `errand.web` )
        # The agent that started this one's bridge, outside the layers this one entered ( a container ):
        # what this one starts can ask it to start something out there ( the ranks, `errand.mpi` ).
        outer = os.environ.get( "ERRAND_AGENT_DIR" )
        self.outer      = outer if outer and outer != str( self.root ) else None

    # -- one client -----------------------------------------------------------

    def serve_client( self, conn: socket.socket ):
        writer = F.Writer( conn.sendall )
        channels : dict = { }               # channel -> Proc, on this connection
        try:
            while True:
                channel, kind, payload = F.read_frame( conn.recv )
                self.idle_since = time.monotonic()     # asked something: in use
                if kind == F.OPEN:
                    self.open( writer, channels, channel, F.load( payload ) )
                    continue
                proc = channels.get( channel )
                if proc is None:
                    continue
                if kind == F.IN:
                    proc.write( payload )
                elif kind == F.EOF:
                    proc.close_input()
                elif kind == F.SIGNAL:
                    said = F.load( payload )
                    if said.get( "stop" ):
                        proc.stop()                 # Ctrl-C: INT, TERM, KILL, run here ( `Proc.stop` )
                    else:
                        proc.signal( int( said.get( "sig", 15 ) ) )
                elif kind == F.RESIZE:
                    size = F.load( payload )
                    proc.resize( size.get( "cols", 80 ), size.get( "rows", 24 ) )
                elif kind == F.CLOSE:
                    channels.pop( channel, None )
                    proc.detach( writer, channel )
        except ( F.Broken, OSError ):
            pass
        finally:
            for proc in set( channels.values() ):
                proc.detach( writer )
            with self.lock:
                self.clients -= 1
                self.idle_since = time.monotonic()
            conn.close()

    def open( self, writer, channels, channel, req ):
        op = req.get( "op" )
        try:
            if op == "ping":
                writer.send( channel, F.REPLY, { "ok": True, "pid": os.getpid(), "root": str( self.root ),
                                                 "python": sys.executable, "home": os.path.expanduser( "~" ),
                                                 "cache": _cache() } )
            elif op == "spawn":
                # what it starts knows which agent started it: where a zygote beside it lives ( `warm` )
                # ... and how long it stays, and who it is: a zygote beside it keeps as long, and goes
                # with it ( `warm` )
                env = { **( req.get( "env" ) or { } ), "ERRAND_AGENT_DIR": str( self.root ),
                        "ERRAND_AGENT_KEEP": str( self.keep_alive ), "ERRAND_AGENT_PID": str( os.getpid() ),
                        **( { "ERRAND_OUTER_AGENT_DIR": self.outer } if self.outer else { } ) }
                proc = Proc( self.root, req[ "argv" ], env, req.get( "cwd" ), bool( req.get( "keep" ) ),
                             tty = req.get( "tty" ), store = req.get( "store" ) )
                with self.lock:
                    self.procs[ proc.id ] = proc
                channels[ channel ] = proc
                writer.send( channel, F.REPLY, { "ok": True, "id": proc.id, "pid": proc.child.pid } )
                proc.attach( writer, channel )
                look.nudge()                         # its watchers see it now
            elif op == "attach":
                proc = self.procs.get( req[ "id" ] )
                if proc is None or proc.code is not None:
                    with self.lock:
                        self.procs.pop( req[ "id" ], None )
                    self.replay( writer, channel, req )
                else:
                    channels[ channel ] = proc
                    writer.send( channel, F.REPLY, { "ok": True, "id": proc.id } )
                    proc.attach( writer, channel, req.get( "out", 0 ), req.get( "err", 0 ) )
            elif op == "stop":
                # Asked to go now ( `errand agents stop` ): only with nothing running, unless forced.
                with self.lock:
                    running = sum( 1 for p in self.procs.values() if p.code is None )
                if running and not req.get( "force" ):
                    writer.send( channel, F.REPLY, { "ok": False, "running": running } )
                else:
                    # Forced: what runs is stopped first, not left behind without its owner.
                    writer.send( channel, F.REPLY, { "ok": True, "running": running } )
                    threading.Thread( target = self.shut, daemon = True ).start()
            elif op == "download":
                # A file a run over there wants and cannot reach ( ADR 0013 ): this agent tries, from a thread.
                def fetch():
                    from ..downloads import serve_want
                    try:
                        got = serve_want( req[ "want" ] )
                    except Exception as err:
                        got = { "error": f"{type( err ).__name__}: {err}" }
                    # `failed`, not `error`: a reply that names an error is the request's failure, and this one
                    # is an answer the client goes on with.
                    writer.send( channel, F.REPLY, { "ok": "sha256" in got, "sha256": got.get( "sha256" ),
                                                     "failed": got.get( "error" ), "offline": bool( got.get( "offline" ) ) } )
                threading.Thread( target = fetch, daemon = True ).start()
            elif op in ( "sync", "pull", "receive" ):
                from . import syncop
                syncop.serve( self, writer, channels, channel, req )      # its own REPLY, from its thread
            elif op == "watch":
                # A watcher's subscription ( `errand tui` ): events as things change ( `look.Watch` ).
                w = look.Watch( writer, channel, req )
                channels[ channel ] = w
                writer.send( channel, F.REPLY, { "ok": True } )
                w.start()
            elif op in look.OPS:
                # What a watcher asks ( `errand tui` ): from a thread, a table may wait on a guest's ssh.
                threading.Thread( target = lambda: writer.send( channel, F.REPLY, look.answer( req ) ),
                                  daemon = True ).start()
            elif op == "list":
                writer.send( channel, F.REPLY, { "ok": True, "procs": finished( self.root, req.get( "store" ),
                                                                                req.get( "ids" ) ) } )
            else:
                writer.send( channel, F.REPLY, { "error": f"unknown request {op!r}" } )
        except Exception as err:          # said to the client, not fatal to the agent
            if self.unmounted():
                self.stopping = True      # gone with its image: the next command starts a new one
                err = f"{type( err ).__name__}: {err} -- the image this agent ran in was replaced; run the command again"
            else:
                err = f"{type( err ).__name__}: {err}"
            writer.send( channel, F.REPLY, { "error": err } )

    def replay( self, writer, channel, req ):
        """A process no longer running here: what it left on disk, then that goes -- delivered."""
        d = locate( self.root, req[ "id" ], req.get( "store" ) )
        if d is None:
            writer.send( channel, F.REPLY, { "error": f"no process {req[ 'id' ]} here" } )
            return
        writer.send( channel, F.REPLY, { "ok": True, "id": req[ "id" ] } )
        for name, kind in ( ( "out", F.OUT ), ( "err", F.ERR ) ):
            if ( d / name ).exists():
                with open( d / name, "rb" ) as f:
                    f.seek( req.get( name, 0 ) )
                    writer.send( channel, kind, f.read() )
        code = ( d / "exit" ).read_text().strip() if ( d / "exit" ).exists() else ""
        # Started by an agent that is gone, and not finished: nobody can say how it ends.
        writer.send( channel, F.EXIT, { "code": int( code ) if code else -1, "lost": not code } )
        shutil.rmtree( d, ignore_errors = True )
        shutil.rmtree( self.root / "proc" / str( req[ "id" ] ), ignore_errors = True )

    # -- the life of it -------------------------------------------------------

    def idle( self ) -> bool:
        """Nothing running, nothing asked, for `keep_alive`. A client that is merely connected does not
        count: a hub keeps its streams open between commands, and an allocation held warm must still
        be let go of once nobody uses it ( its hub then reaches a new one )."""
        if getattr( self, "stopping", False ) or self.unmounted():
            return True
        with self.lock:
            if any( p.code is None for p in self.procs.values() ):
                self.idle_since = time.monotonic()
                self._said_on_disk( "running" )       # for a keeper that asks ( a Windows guest's )
        if self.web is not None and self.web.used( 30.0 ):
            self.idle_since = time.monotonic()        # a page open on it, asking
        busy = time.monotonic() - self.idle_since <= self.keep_alive
        if busy:
            self._busy()
            return False
        # An agent started under this one's directory ( an environment's, in an allocation whose
        # node agent this is ) that was busy lately keeps this one: going would end what it runs.
        now = time.time()
        for f in self.root.glob( "*/busy" ):
            try:
                if now - f.stat().st_mtime <= self.keep_alive:
                    return False
            except OSError:
                pass
        return True

    def unmounted( self ) -> bool:
        """Whether the files this agent runs from are gone: an image rebuilt under an agent that lives in
        it ( `errand setup` replaced the `.sif` ) unmounts it, and nothing it starts would run any more
        ( `Transport endpoint is not connected` ). It goes, and the next command starts one in the new image."""
        try:
            os.stat( sys.executable )
            return False
        except FileNotFoundError:
            return True
        except OSError as err:
            import errno
            return err.errno in ( errno.ENOTCONN, errno.ESTALE, errno.EIO )

    def _busy( self ):
        """Say so on disk: for an agent above this one ( `idle` )."""
        self._said_on_disk( "busy" )

    def _said_on_disk( self, name: str ):
        """`root/<name>` touched, at most every ten seconds: `busy` -- used lately, within
        `keep_alive` --, `running` -- a process of its own runs now."""
        now = time.time()
        said = self.__dict__.setdefault( "_said", { } )
        if now - said.get( name, 0 ) >= 10:
            said[ name ] = now
            try:
                ( self.root / name ).touch()
            except OSError:
                pass

    def terminate( self, timeout: float = 8.0 ):
        """Everything it started, stopped -- SIGTERM, then SIGKILL -- and waited for, a while: an
        attached agent whose bridge is gone ( `daemon._attached` ), an agent stopped by force or by a
        SIGTERM. What still runs after `timeout` is the next agent's to kill ( `kill_orphans` )."""
        import signal
        with self.lock:
            procs = [ p for p in self.procs.values() if p.code is None ]
        for p in procs:
            try:
                p.stop( first = signal.SIGTERM )
            except OSError:
                pass
        deadline = time.monotonic() + timeout
        for p in procs:
            p.wait_gone( max( 0.0, deadline - time.monotonic() ) )

    def shut( self ):
        """Go now, and take what runs with it."""
        self.terminate()
        self.stopping = True

    def run( self ) -> int:
        def client( conn, threading ):
            with self.lock:
                self.clients += 1          # counted before `idle` can look again
            threading.Thread( target = self.serve_client, args = ( conn, ), daemon = True ).start()

        import signal

        def asked_to_go( *_ ):
            # A SIGTERM from outside ( a logout, a `kill` ): what runs goes with the agent.
            threading.Thread( target = self.shut, daemon = True ).start()

        if threading.current_thread() is threading.main_thread() and \
                signal.getsignal( signal.SIGTERM ) == signal.SIG_DFL:     # an attached agent has its own
            signal.signal( signal.SIGTERM, asked_to_go )
        # Swept once the directory is held: another agent's processes are never this one's to kill.
        from . import syncop
        # Going: the copies it synced are checked once more ( ADR 0006 ), for the next push to say.
        def starting():
            sweep( self.root )
            from .. import web
            self.web = web.start( self.root )

        def closing():
            # After its runs: the copies of errand's sources nothing needs any more go.
            from .endpoint import prune_sources
            prune_sources( self.root )
            if self.web is not None:
                self.web.stop()
            syncop.closing()

        return endpoint.serve( self.root, self.idle, client, starting = starting, closing = closing )


def _cache( ) -> str:
    """errand's per-user directory on this machine, as `ping` reports it."""
    from .. import bootstrap
    return str( bootstrap.local_cache() )
