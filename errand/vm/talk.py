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
