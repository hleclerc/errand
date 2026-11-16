"""Where a layer's own work runs on another machine: `Over`, through its agent ( `Here`, this machine, is in `base` ).
"""
from __future__ import annotations

import shlex
import subprocess

from typing import TYPE_CHECKING

from .. import agents
from .base import Here, remote_path

if TYPE_CHECKING:              # only named: building one is `host_of`'s business
    from .gateways import Ssh


class Over:
    """Another machine, through `Ssh`, from the project's copy over there:
    what the layers after an `Ssh` are handed."""
    remote = True

    def __init__( self, ssh: Ssh, root = None ):
        self.ssh  = ssh
        self.root = remote_path( root )

    def shell( self, line: str, *, quiet = False, tty = False, capture = False, input = None,
               timeout = None ):
        if self.root is not None:
            line = f"cd {shlex.quote( str( self.root ) )} && {line}"
        # Through the host agent over there ( ADR 0005 ): no new connection per line.
        conn = self._agent()
        if tty and not capture and input is None:
            # with a terminal: `errand shell`, a build that asks for a password, a progress bar
            code = agents.interact( conn, [ "sh", "-c", 'exec "${SHELL:-/bin/sh}" -ic "$1"', "sh", line ] )
            return subprocess.CompletedProcess( line, code )
        return agents.shell( conn, line, quiet = quiet, capture = capture, input = input,
                             timeout = timeout, login = True )

    def _agent( self ):
        """The connection to the host agent: every line goes through it ( ADR 0009: there is no way
        without one )."""
        try:
            return agents.open( agents.upstream.ssh_target( self.ssh ) )
        except Exception as err:
            if "the agent: cannot reach " in str( err ):          # ssh itself fails
                from .gateways import Unreachable
                raise Unreachable( str( err ).split( "the agent: ", 1 )[ -1 ] ) from None
            raise RuntimeError( f"no agent on {self.ssh.host}: {err}" ) from None

    def describe( self ):
        return self.ssh.host

    def spec( self ) -> dict:
        return { "ssh": { "host": self.ssh.host, "options": list( self.ssh.options ),
                          "python": self.ssh.python },
                 "root": None if self.root is None else str( self.root ) }




def host_of( spec: dict ):
    """`spec` the other way round: for another process that must reach the same place."""
    if "here" in spec:
        return Here( spec[ "here" ] )
    from .gateways import Ssh
    return Over( Ssh( **spec[ "ssh" ] ), spec.get( "root" ) )
