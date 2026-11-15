"""Talking to a Windows over ssh, from the machine that reaches it: cmd.exe lines, copies in and out.

Shared by a machine errand boots ( `Machine`, reached as `Administrator@127.0.0.1` from the machine that runs QEMU ) and
a Windows that is just there ( `Box`, reached from here by the `Ssh` before its `WindowsBox` ). What differs is said by
`_reach( tool, port_flag )` ( ssh or scp, with what it needs ), `address` ( `user@host` ), `host` ( where those run )
and `scratch` ( a directory of that machine for what transits ).
"""
from __future__ import annotations

import subprocess

from .. import layers as L
from .common import _backslashed, VmError
from .transfer import rsync_failed, rsync_line


class Talk:
    def guest( self, line: str, **kw ):
        """`line`, run by cmd.exe in Windows."""
        return self.host.shell( L.sh( [ *self._reach( "ssh", "-p" ), self.address, line ] ), **kw )

    def scp( self, src: str, dst: str ) -> int:
        """Between the machine that reaches Windows and it; one side is `<address>:…`."""
        return self.host.shell( L.sh( [ *self._reach( "scp", "-P" ), "-q", src, dst ] ) ).returncode

    def answers( self ) -> bool:
        try:
            got = self.guest( "echo errand-ok", capture = True, timeout = 40 )
        except subprocess.TimeoutExpired:
            return False
        return got.returncode == 0 and "errand-ok" in ( got.stdout or "" )

    def push( self, there: str, source: str = "./" ):
        """The project as the machine that runs QEMU has it, into the guest:
        what changed since the last time, when `there` is on the kept disk.
        `source`: another directory of that machine, relative to the project's -- a sibling checkout."""
        win = _backslashed( there )
        code = self.guest( f'if not exist "{win}" mkdir "{win}"' ).returncode
        if code:
            raise subprocess.CalledProcessError( code, "copy into windows" )
        got = self.host.shell( rsync_line( self._reach( "ssh", "-p" ), there, source, self.address ), capture = True )
        if rsync_failed( got ):
            raise VmError( f"could not copy the project into windows ( rsync: {got.returncode} ):\n"
                           f"{( got.stderr or '' ).strip()[ -800 : ]}" )

    def fetch( self, paths, there: str ):
        """Into the project as the machine that runs QEMU has it -- from where an
        `Ssh` before it brings them back in turn. Best effort, as over ssh: what
        the command never produced is nothing to bring back."""
        win, archive = _backslashed( there ), f"{self.scratch}/out.tar"
        for p in paths:
            p = str( p ).strip( "/" )
            # The old archive deleted first, and a missing path an error: never
            # bring back what an earlier command left.
            made = self.guest( f'del "{win}.out.tar" 2>nul & cd /d "{win}" && '
                               f'if exist "{_backslashed( p )}" ( tar -c -f "{there}.out.tar" "{p}" ) else exit 1',
                               quiet = True )
            if made.returncode or self.scp( f"{self.address}:{there}.out.tar", archive ):
                continue
            self.host.shell( L.sh( [ "tar", "-x", "-f", archive ] ) + " && " + L.sh( [ "rm", "-f", archive ] ) )
