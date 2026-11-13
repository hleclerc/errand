"""A Windows virtual machine as a Gateway ( ADR 0005, step 5 ): sessions in the guest, through an agent there.

While a command uses it, the machine is held ( `Machine.using`: booted if it is
not, kept up as long as somebody holds it ); the project and errand's own
sources are copied in; an agent is started in the guest THROUGH the layer --
`cd`, vcvars, the variables of the layers after it, as `Windows.line` writes
them for cmd.exe -- so that what it starts has all of that; and sessions run
there like anywhere else. What they write comes back to the machine that runs
QEMU, then here.

The stream to the guest agent goes through the host agent of the machine that
runs QEMU, as `ssh -p <port> Administrator@127.0.0.1 …` from there: no new
login on that machine, one on the guest's sshd per stream.

Only for a Windows with a Python ( `Windows( python = … )` ): without one,
`errand run` hands it the command itself, as before.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
from pathlib import Path

from .. import agents, bootstrap, config, layers as L
from ..agents import upstream as U
from .sessions import Session


def usable( env ) -> bool:
    return env.vm is not None and bool( getattr( env.vm, "python", None ) )


class Guest:
    def __init__( self, env, tags, where, echo ):
        from ..vm.windows import where as where_of
        self.env, self.tags, self.where, self.echo = env, tags, where, echo
        self.layer = env.vm
        stack = env.stack_for( "run", tags )
        self.inner = stack[ stack.index( self.layer ) + 1 : ]
        self.host = L.Over( where.ssh, where.there ) if where.ssh is not None else L.Here( where.root )
        self.ctx = L.Context( root = where.there, tags = tags, remote = where.ssh is not None, host = self.host,
                              origin = where.root )
        self.name = self.layer.image_name( self.ctx )
        self.there = self.layer.guest_root( self.ctx )
        self.said_where = where_of( self.host )
        self.key = bootstrap.sources_key()
        self.src = f"C:/errand/src/{self.key}"
        self.boot = f"{self.src}/errand/_boot.py"

    # -- holding the machine ---------------------------------------------------

    def __enter__( self ):
        from ..vm.common import VmError
        from ..vm.facts import Facts, need, package_hint
        from ..vm.machine import Machine
        from ..vm.windows import ready_line
        if self.host.shell( ready_line( self.name, keyed = True ), quiet = True ).returncode:
            raise VmError( f"windows is not installed yet {self.said_where} -- errand setup <name>" )
        self.m = Machine( self.host, Facts.of( self.host ), self.name )
        need( self.m.facts, ( "rsync", ), package_hint( self.m.facts, [ "rsync" ] ) )
        self._held = self.m.using( self.layer.booted(), self.echo )
        self._held.__enter__()
        try:
            self.echo( f"  copy in -> windows:{self.there}" )
            self.m.push( self.there )
            for other in self.layer.also:
                self.m.push( posixpath.normpath( f"{self.there}/{other}" ), f"{other}/" )
            self._ship()
        except BaseException:
            self._held.__exit__( None, None, None )
            raise
        return self

    def __exit__( self, *exc ):
        from ..vm.datadisk import FLUSH_SCRIPT, powershell
        try:
            if self.layer.data:
                self.m.guest( powershell( FLUSH_SCRIPT ), quiet = True )
        finally:
            self._held.__exit__( *exc )

    def _ship( self ):
        """errand's sources into the guest, from their copy on the machine that runs QEMU."""
        from ..vm.common import VmError
        from ..vm.transfer import rsync_failed, rsync_line
        if self.where.ssh is not None:          # ~/.cache/errand/src/<key>/ holds `errand/`
            source, dest = f"{self.where.cache}/{bootstrap.src_rel()}/", self.src
        else:                                   # this checkout's own package
            source, dest = f"{bootstrap.PACKAGE}/", f"{self.src}/errand"
        win = dest.replace( "/", "\\" )
        self.m.guest( f'if not exist "{win}" mkdir "{win}"', quiet = True )
        got = self.host.shell( rsync_line( self.m._reach( "ssh", "-p" ), dest, source ), capture = True )
        if rsync_failed( got ):
            raise VmError( f"could not copy errand into windows:\n{( got.stderr or '' ).strip()[ -800 : ]}" )

    # -- the agent there, and sessions ------------------------------------------

    def target( self ) -> dict:
        keep = int( getattr( self.env, "keep_alive", None ) or U.KEEP_ALIVE )
        ctx = L.Context( root = Path( self.there ), tags = self.tags, remote = True )

        def line_for( where_ ):
            cmd = L.Command( [ "python", self.boot, "-m", "errand.agents", "connect", where_, str( keep ) ] )
            return self.layer.line( L.compose( self.inner, cmd, ctx ), self.there )

        digest = hashlib.sha1( f"{self.env.name}\0{line_for( '@' )}".encode() ).hexdigest()[ : 10 ]
        name = f"env-{self.key}-{digest}"
        guest = line_for( f"C:/errand/agents/{name}" )
        on_host = L.sh( [ *self.m._reach( "ssh", "-p" ), "-T", "Administrator@127.0.0.1", guest ] )
        ssh = self.where.ssh
        if ssh is None:
            argv = [ "sh", "-c", on_host ]
        elif agents.mode() == "hub":
            argv = [ *U.rsh_argv( ssh.host, ssh.options ), ssh.host, on_host ]
        else:
            argv = [ "ssh", "-T", *L.ssh_options( ssh.options ), ssh.host, on_host ]
        return { "kind": "cmd", "id": f"{self.said_where}:{name}:{self.m.port}", "argv": argv, "keep_alive": keep }

    def start( self, request: dict, child: dict ):
        request = { **request, "root": self.there }
        self.target_ = self.target()
        conn = agents.open( self.target_ )
        python = conn.ping()[ "python" ]
        return Session.start( conn, [ python, self.boot, "-m", "errand.agents.ops", "session", json.dumps( request ) ],
                              cwd = self.there, env = child, store = f"{self.there}/{config.state_rel( Path( self.there ) )}/procs" )

    def fetch( self, paths ):
        if paths:
            self.echo( f"  fetch <- windows:{self.there} [{', '.join( paths )}]" )
            self.m.fetch( list( paths ), self.there )

