"""One installed image, and the machine booted from it: doing things where QEMU runs, and talking
to the guest. A command's side, the keeper's side and installing's needs are mixed in.
"""
from __future__ import annotations

import contextlib
import os
import posixpath
import random
import re
import signal
import subprocess
import time

from .. import layers as L
from .common import _alive, _backslashed, _lock, _read, _sh, GUEST_OPTIONS, USER, VmError
from .places import images_rel, live_dir
from .facts import accel, Facts
from .qemu import qemu_argv
from .transfer import rsync_failed, rsync_line
from .caller import Caller
from .keeping import Keeping
from .supplies import Supplies


class Machine( Caller, Keeping, Supplies ):
    """One installed image, and the machine booted from it.

    Over there -- wherever `host` leads -- are the disks, the guest's key and
    QEMU; they are only ever touched through `host`, a line at a time. Here are
    the state, the locks and the keeper, under `live_dir()`.

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
        self.live  = live_dir() / f"{re.sub( r'[^A-Za-z0-9._-]', '_', host.describe() )}-{name}"
        self._port = None
        sweep( keep = self.live )

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
        """QEMU started over there and let go of -> ( port, pid ). The port is
        drawn at random and tried: only that machine knows which ones are free."""
        how, pidfile = accel( self.facts ), f"{log}.pid"
        for _ in range( 5 ):
            port = random.randint( 20000, 60000 )
            argv = qemu_argv( disk, accel = how, port = port, cpus = cpus, ram = ram, iso = iso, media = media,
                              data = data )
            # QEMU lets go by itself, and only once the machine is set up: a
            # port taken or a disk locked is its exit code, now, not a death
            # to notice later -- and the pid is the one IT writes, not a guess
            # at which process a shell put in the background.
            got = self.host.shell( _sh( 'p=$1 l=$2; shift 2; rm -f "$p"; "$@" > "$l" 2>&1 < /dev/null; code=$?; '
                                        'cat "$l"; [ $code -eq 0 ] && echo "errand-pid=$( cat "$p" )"; exit $code',
                                        pidfile, log, *argv, "-daemonize", "-pidfile", pidfile ),
                                   capture = True )
            out = ( got.stdout or "" ) + ( got.stderr or "" )
            found = re.search( r"errand-pid=(\d+)", out )
            if got.returncode == 0 and found:
                self._port = port
                return port, int( found.group( 1 ) )
            if "hostfwd" not in out and "host forwarding" not in out:
                raise VmError( f"QEMU did not start {self.facts.where}:\n{out.strip()[ -800 : ]}" )
        raise VmError( f"no free port for ssh into the machine {self.facts.where}, five tries" )

    def alive_there( self, pid ):
        """-> True, False, or None when the question could not be put ( ssh down )."""
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
        self.host.shell( _sh( 'kill "$1" 2>/dev/null; i=0; '
                              'while kill -0 "$1" 2>/dev/null && [ $i -lt 30 ]; do sleep 1; i=$(( i + 1 )); done; '
                              'kill -9 "$1" 2>/dev/null; true', pid ), quiet = True )

    # -- talking to the guest, from the machine that runs it ------------------

    def _reach( self, tool: str, port_flag: str ) -> list:
        return [ tool, port_flag, str( self.port ), "-i", f"{self.image}/key", *GUEST_OPTIONS ]

    def guest( self, line: str, **kw ):
        """`line`, run by cmd.exe in Windows."""
        return self.host.shell( L.sh( [ *self._reach( "ssh", "-p" ), f"{USER}@127.0.0.1", line ] ), **kw )

    def scp( self, src: str, dst: str ) -> int:
        """Between the machine that runs QEMU and the guest; one side is `Administrator@127.0.0.1:…`."""
        return self.host.shell( L.sh( [ *self._reach( "scp", "-P" ), "-q", src, dst ] ) ).returncode

    def answers( self ) -> bool:
        try:
            got = self.guest( "echo errand-ok", capture = True, timeout = 40 )
        except subprocess.TimeoutExpired:
            return False
        return got.returncode == 0 and "errand-ok" in ( got.stdout or "" )

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

    def push( self, there: str, source: str = "./" ):
        """The project as the machine that runs QEMU has it, into the guest:
        what changed since the last time, when `there` is on the kept disk.
        `source`: another directory of that machine, relative to the project's -- a sibling checkout."""
        win = _backslashed( there )
        code = self.guest( f'if not exist "{win}" mkdir "{win}"' ).returncode
        if code:
            raise subprocess.CalledProcessError( code, "copy into windows" )
        got = self.host.shell( rsync_line( self._reach( "ssh", "-p" ), there, source ), capture = True )
        if rsync_failed( got ):
            raise VmError( f"could not copy the project into windows ( rsync: {got.returncode} ):\n"
                           f"{( got.stderr or '' ).strip()[ -800 : ]}" )

    def fetch( self, paths, there: str ):
        """Into the project as the machine that runs QEMU has it -- from where an
        `Ssh` before it brings them back in turn. Best effort, as over ssh: what
        the command never produced is nothing to bring back."""
        win, archive = _backslashed( there ), f"{self.spot}/out.tar"
        for p in paths:
            p = str( p ).strip( "/" )
            # The old archive deleted first, and a missing path an error: never
            # bring back what an earlier command left.
            made = self.guest( f'del "{win}.out.tar" 2>nul & cd /d "{win}" && '
                               f'if exist "{_backslashed( p )}" ( tar -c -f "{there}.out.tar" "{p}" ) else exit 1',
                               quiet = True )
            if made.returncode or self.scp( f"{USER}@127.0.0.1:{there}.out.tar", archive ):
                continue
            self.host.shell( L.sh( [ "tar", "-x", "-f", archive ] ) + " && " + L.sh( [ "rm", "-f", archive ] ) )


def sweep( keep = None, older = 86400.0 ):
    """The live directories of machines nobody used for a day: no keeper, no lock held -- they go.
    The per-user cache holds only what is live; the images are the projects'."""
    import shutil
    now = time.time()
    for d in live_dir().iterdir() if live_dir().is_dir() else [ ]:
        if d == keep or not d.is_dir() or _alive( _read( d / "keeper.pid" ) ):
            continue
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
    """-> [ live directory ] whose keeper is alive."""
    if not live_dir().is_dir():
        return [ ]
    return [ d for d in sorted( live_dir().iterdir() )
             if d.is_dir() and _alive( _read( d / "keeper.pid" ) ) ]


def stop_all( echo = print ) -> int:
    """`errand vm stop`: every warm machine, now -- here or elsewhere, since
    every keeper is here."""
    machines = running()
    for live in machines:
        echo( f"  stopping windows vm {live.name}" )
        with contextlib.suppress( OSError, ValueError ):
            os.kill( int( _read( live / "keeper.pid" ) ), signal.SIGTERM )
    if not machines:
        echo( "  no virtual machine is running" )
    return 0
