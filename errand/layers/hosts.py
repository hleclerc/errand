"""Where a layer's own work runs on another machine: `Over`, through its agent ( `Here`, this machine, is in `base` ).
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .. import agents
from .base import _how, Here

if TYPE_CHECKING:              # only named: building one is `host_of`'s business
    from .gateways import Ssh


class Over:
    """Another machine, through `Ssh`, from the project's copy over there:
    what the layers after an `Ssh` are handed."""
    remote = True

    def __init__( self, ssh: Ssh, root = None ):
        self.ssh  = ssh
        self.root = Path( root ) if root is not None else None

    def shell( self, line: str, *, quiet = False, tty = False, capture = False, input = None,
               timeout = None ):
        if self.root is not None:
            line = f"cd {shlex.quote( str( self.root ) )} && {line}"
        conn = self._agent()
        if conn is not None:
            # Through the host agent over there ( ADR 0005 ): no new connection per line.
            if tty and not capture and input is None:
                # with a terminal: `errand shell`, a build that asks for a password, a progress bar
                code = agents.interact( conn, [ "sh", "-c", 'exec "${SHELL:-/bin/sh}" -ic "$1"', "sh", line ] )
                return subprocess.CompletedProcess( line, code )
            return agents.shell( conn, line, quiet = quiet, capture = capture, input = input,
                                 timeout = timeout, login = True )
        # ssh runs non-interactively, so the remote shell never reads the rc
        # file that puts micromamba, cargo or nvm on PATH. Force an interactive
        # one, through the user's own $SHELL rather than a hard-coded bash.
        # `-t` when somebody watches: a build can ask for a password, and draws
        # a progress bar nobody sees without a terminal.
        return subprocess.run( [ "ssh", *( [ "-t" ] if tty else [ ] ), *self.ssh.options, self.ssh.host,
                                 f"$SHELL -ic {shlex.quote( line )}" ], timeout = timeout,
                               **_how( quiet, capture, input ) )

    def _agent( self ):
        """The connection to the host agent, or None: agents switched off, or not to be had --
        then a fresh ssh per line, as before, said once."""
        if not agents.enabled():
            return None
        try:
            return agents.open( agents.upstream.ssh_target( self.ssh ) )
        except Exception as err:
            if self.ssh.host not in _NO_AGENT:
                _NO_AGENT.add( self.ssh.host )
                print( f"  warning: no agent on {self.ssh.host} ( {err} ): one ssh per command",
                       file = sys.stderr, flush = True )
            return None

    def describe( self ):
        return self.ssh.host

    def spec( self ) -> dict:
        return { "ssh": { "host": self.ssh.host, "options": list( self.ssh.options ),
                          "python": self.ssh.python },
                 "root": None if self.root is None else str( self.root ) }


_NO_AGENT : set = set()          # hosts where reaching an agent failed, said once each


def host_of( spec: dict ):
    """`spec` the other way round: for another process that must reach the same place."""
    if "here" in spec:
        return Here( spec[ "here" ] )
    from .gateways import Ssh
    return Over( Ssh( **spec[ "ssh" ] ), spec.get( "root" ) )
