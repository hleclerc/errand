"""One installed image, and the machine booted from it: doing things where QEMU runs, and talking
to the guest. A command's side, the keeper's side and installing's needs are mixed in.
"""
from __future__ import annotations

import contextlib
import os
import posixpath
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

from .. import layers as L
from .common import _alive, _backslashed, _lock, _read, _sh, GUEST_OPTIONS, USER, VmError
from .places import images_rel, live_dir
from .facts import accel, Facts
from .qemu import qemu_argv
from .caller import Caller
from .talk import Talk
from .keeping import Keeping
from .supplies import Supplies


class Machine( Caller, Keeping, Supplies, Talk ):
    """One installed image, and the machine booted from it.

    Wherever `host` leads are the disks, the guest's key and QEMU. A command
    touches them through `host`, a line at a time, and holds the machine through
    the agent there ( `Caller.using` ). The state, the locks and the keeper are
    there too, under that machine's `live_dir()`: the keeper runs with
    `host` = that machine itself ( ADR 0008 ).

    Two locks, always taken in this order:

        start.lock   held while deciding whether a keeper must be started, and
                     by a keeper while it stops -- so nobody decides "it is up"
                     about a machine that is going down
        use.lock     held for as long as a command uses the machine -- which
                     is how commands take turns, and how the keeper knows that
                     nobody is about to
    """

    def __init__( self, host, facts: Facts, name: str ):
        self.host, self.facts, self.name = host, facts, name
        self.image = posixpath.join( facts.root, images_rel(), name )   # over there, the project's
        self.spot  = f"{self.image}/live"                        # over there: overlay, tars, log
        self._port, self._qemu, self._held = None, None, None
        self.at( self.image )

    def at( self, image: str ):
        """The image is `image`, over there: and so is where the machine's state lives, on the
        machine that runs QEMU ( `live_dir()` there, named after the image: two projects' copies
        of one declaration are two machines )."""
        import hashlib
        self.image = image
        self.spot  = f"{image}/live"
        self.key   = f"{self.name[ : 16 ]}-{hashlib.sha1( image.encode() ).hexdigest()[ : 8 ]}"
        self.live  = live_dir() / self.key

    # -- doing things over there ----------------------------------------------

    def there( self, script: str, *args, what = "" ):
        """A POSIX script over there, which must work: -> its output."""
        got = self.host.shell( _sh( script, *args ), capture = True )
        if got.returncode:
            raise VmError( f"{what or 'a step'} failed {self.facts.where}: "
                           f"{( got.stderr or got.stdout or '' ).strip()[ -600 : ]}" )
        return got.stdout

    def write( self, path: str, text: str ):
        got = self.host.shell( _sh( 'cat > "$1"', path ), input = text, capture = True )
        if got.returncode:
            raise VmError( f"could not write {path} {self.facts.where}: {got.stderr.strip()[ -300 : ]}" )

    def start( self, disk: str, *, cpus, ram, iso = None, media = None, data = None, log: str ) -> tuple:
        """QEMU started -> ( port, pid ). The port is drawn at random and tried: only that machine
        knows which ones are free.

        On this machine ( a keeper, ADR 0008 ), QEMU is this process's child, in its group, and
        dies with it. Over there ( an install driven from elsewhere ), it is a process of that
        machine's agent, held by this command, stopped if this command goes."""
        how = accel( self.facts )
        for _ in range( 5 ):
            port = random.randint( 20000, 60000 )
            argv = qemu_argv( disk, accel = how, port = port, cpus = cpus, ram = ram, iso = iso, media = media,
                              data = data )
            got = self._owned_there( argv, log ) if self.host.remote else self._child( argv, log )
            if got is not None:
                self._port = port
                return port, got
        raise VmError( f"no free port for ssh into the machine {self.facts.where}, five tries" )

    def _owned_there( self, argv, log: str ):
        """QEMU over there as a process of that machine's agent, held by this command ( an install
        driven from here ): if this command dies or its connection is lost, the agent stops it
        ( ADR 0008 ). -> its pid, or None when its port was taken."""
        from .. import agents
        from ..agents import upstream as U
        conn = agents.open( U.ssh_target( self.host.ssh ) )
        call = conn.open( { "op": "spawn", "keep": False, "cwd": str( self.host.root ),
                            "argv": [ "sh", "-c", 'l=$1; shift; exec "$@" > "$l" 2>&1 < /dev/null', "sh", log, *argv ] } )
        pid = int( call.reply( 60 )[ "pid" ] )
        time.sleep( 3.0 )                          # a port taken or a disk locked: QEMU says so at once
        if self.alive_there( pid ):
            self._held = call
            return pid
        call.close()
        said = self.host.shell( L.sh( [ "cat", log ] ), capture = True, quiet = True ).stdout or ""
        if "hostfwd" in said or "host forwarding" in said:
            return None
        raise VmError( f"QEMU did not start {self.facts.where}:\n{said.strip()[ -800 : ]}" )

    def _child( self, argv, log: str ):
        """QEMU as this process's child -> its pid, or None when its port was taken. Its death is
        tied to this process's: same process group ( a stop of the keeper's group takes it ), and
        on Linux the kernel kills it if this process dies, however it dies."""
        preexec = _die_with_parent if sys.platform.startswith( "linux" ) else None
        with open( log, "w" ) as out:
            self._qemu = subprocess.Popen( argv, stdin = subprocess.DEVNULL, stdout = out, stderr = subprocess.STDOUT,
                                           cwd = str( self.host.root ), preexec_fn = preexec )
        deadline = time.monotonic() + 3.0          # a port taken or a disk locked: QEMU says so at once
        while time.monotonic() < deadline and self._qemu.poll() is None:
            time.sleep( 0.1 )
        if self._qemu.poll() is None:
            return self._qemu.pid
        said = Path( log ).read_text( errors = "replace" )
        if "hostfwd" in said or "host forwarding" in said:
            return None
        raise VmError( f"QEMU did not start {self.facts.where}:\n{said.strip()[ -800 : ]}" )

    def alive_there( self, pid ):
        """-> True, False, or None when the question could not be put ( ssh down )."""
        if self._qemu is not None and self._qemu.pid == int( pid ):
            return self._qemu.poll() is None             # a child: asked of the kernel, and reaped
        got = self.host.shell( L.sh( [ "kill", "-0", str( pid ) ] ), quiet = True )
        if got.returncode == 0:
            return True
        return None if self.host.remote and got.returncode == 255 else False

    def gone( self, pid ) -> bool:
        """Dead, asked twice a few seconds apart: a machine's disk is renamed, or
        its claim let go, on this answer -- one stray `no` must not do that."""
        if self.alive_there( pid ) is not False:
            return False
        time.sleep( 3.0 )
        return self.alive_there( pid ) is False

    def stop_there( self, pid ):
        """Thrown away rather than shut down: the next boot starts from the image
        again, so there is nothing in this one worth a clean exit."""
        if self._qemu is not None and self._qemu.pid == int( pid ):
            # A child: waited for itself -- `kill -0` would take its zombie for a live QEMU.
            self._qemu.terminate()
            try:
                self._qemu.wait( 30 )
            except subprocess.TimeoutExpired:
                self._qemu.kill()
                self._qemu.wait()
            return
        if self._held is not None:
            # Its owner over there stops it, group and all, once this command lets go of it.
            from ..agents import client
            client.stop( self._held )
        self.host.shell( _sh( 'kill "$1" 2>/dev/null; i=0; '
                              'while kill -0 "$1" 2>/dev/null && [ $i -lt 30 ]; do sleep 1; i=$(( i + 1 )); done; '
                              'kill -9 "$1" 2>/dev/null; true', pid ), quiet = True )

    # -- talking to the guest, from the machine that runs it ------------------

    def _reach( self, tool: str, port_flag: str ) -> list:
        return [ tool, port_flag, str( self.port ), "-i", f"{self.image}/key", *GUEST_OPTIONS ]

    def wait_for( self, pid, timeout: float ) -> bool:
        """Until sshd answers, QEMU dies, or `timeout`."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.gone( pid ):
                return False
            if self.answers():
                return True
            time.sleep( 3.0 )
        return False

    @property
    def address( self ) -> str:
        return f"{USER}@127.0.0.1"

    @property
    def scratch( self ) -> str:
        return self.spot


def _die_with_parent():
    """In the child, before exec: SIGKILL when the process that started it dies ( PR_SET_PDEATHSIG )."""
    import ctypes
    ctypes.CDLL( None, use_errno = True ).prctl( 1, signal.SIGKILL, 0, 0, 0 )


def sweep( keep = None, older = 86400.0 ):
    """The live directories of machines nobody used for a day: no keeper, no lock held -- they go.
    The per-user cache holds only what is live; the images are the projects'."""
    import shutil
    now = time.time()
    for d in live_dir().iterdir() if live_dir().is_dir() else [ ]:
        if d == keep or not d.is_dir() or _alive( _read( d / "keeper.pid" ) ):
            continue
        if _alive( _read( d / "qemu.pid" ) ):
            continue                     # a QEMU its keeper left: the next keeper ( or `vm stop` ) ends it
        try:
            if now - max( p.stat().st_mtime for p in [ d, *d.iterdir() ] ) < older:
                continue
        except ( OSError, ValueError ):
            continue
        held = [ _lock( d / n, block = False ) for n in ( "start.lock", "use.lock" ) ]
        try:
            if all( h is not None for h in held ):
                shutil.rmtree( d, ignore_errors = True )
        finally:
            for h in held:
                if h is not None:
                    h.close()


def running( ) -> list:
    """-> [ live directory ] of this machine whose keeper, or a QEMU left by one, is alive."""
    if not live_dir().is_dir():
        return [ ]
    return [ d for d in sorted( live_dir().iterdir() )
             if d.is_dir() and ( _alive( _read( d / "keeper.pid" ) ) or _alive( _read( d / "qemu.pid" ) ) ) ]


def stop_all( echo = print ) -> int:
    """`python -m errand.vm stop`: every machine kept on THIS machine, now. A keeper is stopped
    ( it flushes the guest's disk, then stops QEMU ); a QEMU whose keeper is gone is stopped
    directly."""
    from .keeping import _command_of
    machines = running()
    for live in machines:
        keeper, qemu = _read( live / "keeper.pid" ), _read( live / "qemu.pid" )
        if _alive( keeper ):
            echo( f"  stopping windows vm {live.name}" )
            with contextlib.suppress( OSError, ValueError ):
                os.kill( int( keeper ), signal.SIGTERM )
        elif qemu and "qemu" in _command_of( qemu ):
            echo( f"  stopping windows vm {live.name} ( its keeper was gone )" )
            with contextlib.suppress( OSError, ValueError ):
                os.kill( int( qemu ), signal.SIGTERM )
            ( live / "qemu.pid" ).unlink( missing_ok = True )
    if not machines:
        echo( "  no virtual machine is running here" )
    return 0


def stop_everywhere( envs, echo = print ) -> int:
    """`errand vm stop`: every machine kept here, and on each machine an `Ssh` of `envs` leads to
    where a `Windows` follows -- each keeper is on the machine that runs its QEMU ( ADR 0008 ),
    asked there through its agent."""
    from .. import agents, bootstrap
    from ..agents import upstream as U
    from ..layers.gateways import Ssh
    from .windows import Windows
    stop_all( echo )
    seen = set()
    for env in envs:
        stack = list( getattr( env, "stack", [ ] ) )
        for i, layer in enumerate( stack[ : -1 ] ):
            if not isinstance( layer, Ssh ) or not isinstance( stack[ i + 1 ], Windows ) or layer.host in seen:
                continue
            seen.add( layer.host )
            try:
                conn = agents.open( U.ssh_target( layer ) )
                said = conn.ping()
                boot = f"{said.get( 'cache' ) or said[ 'home' ] + '/' + bootstrap.BASE}/{bootstrap.boot_rel()}"
                got = agents.shell( conn, L.sh( [ said[ "python" ], boot, "-m", "errand.vm", "stop" ] ), capture = True )
                for line in ( got.stdout or "" ).splitlines():
                    echo( f"  {layer.host}: {line.strip()}" )
            except Exception as err:
                echo( f"  {layer.host}: could not be asked ( {err} )" )
    return 0
