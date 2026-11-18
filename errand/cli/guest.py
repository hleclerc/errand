"""A Windows virtual machine as a Gateway ( ADR 0005, step 5 ): sessions in the guest, through an agent there.

While a command uses it, the machine is held ( `Machine.using`: booted if it is
not, kept up as long as somebody holds it ); the project and errand's own
sources are copied in; an agent is started in the guest THROUGH the layer --
`cd`, vcvars, the variables of the layers after it, as `Windows.line` writes
them for cmd.exe -- so that what it starts has all of that; and sessions run
there like anywhere else. What they write comes back to the machine that runs
QEMU, then here.

The project crosses by manifest ( ADR 0006 ), from here straight into the guest and back, through an
agent of the guest that no layer starts ( `host_target` ): the copy on the machine that runs QEMU
plays no part, and the guest needs no rsync. errand's sources go first, as a tar on the stdin of one
cmd.exe line.

The stream to the guest agent goes through the host agent of the machine that
runs QEMU, as `ssh -p <port> Administrator@127.0.0.1 …` from there: no new
login on that machine, one on the guest's sshd per stream.

Every Windows has a Python ( `Windows.python`, a pinned release by default; a box's, found or
installed by uv ), so this is how errand reaches every guest ( ADR 0008 ). With agents off, `errand
run` hands the guest the command itself instead.
"""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import subprocess
from pathlib import Path

from .. import agents, bootstrap, config, layers as L
from ..agents import upstream as U
from .sessions import Session


class Guest:
    def __init__( self, env, tags, where, echo ):
        from ..vm.windows import where as where_of
        self.env, self.tags, self.where, self.echo = env, tags, where, echo
        self.layer = env.vm
        stack = env.stack_for( "run" )
        self.inner = stack[ stack.index( self.layer ) + 1 : ]
        self.host = L.Over( where.ssh, where.there ) if where.ssh is not None else L.Here( where.root )
        self.ctx = L.Context( root = where.there, tags = tags, remote = where.ssh is not None, host = self.host,
                              origin = where.root )
        self.box = getattr( self.layer, "is_box", False )
        self.name = self.layer.image_name( self.ctx )
        self.there = self.layer.guest_root( self.ctx )
        self.said_where = f"on {self.layer.via.host}" if self.box and self.layer.via is not None else where_of( self.host )
        self.key = bootstrap.sources_key()
        self.src = f"C:/errand/src/{self.key}"
        self.boot = f"{self.src}/errand/_boot.py"

    # -- holding the machine ---------------------------------------------------

    def __enter__( self ):
        from ..vm.common import VmError
        from ..vm.facts import Facts
        from ..vm.machine import Machine
        from ..vm.windows import ready_line
        if self.box:
            from ..vm.box import Box
            self.m = Box( self.layer, self.where.root )
            if not self.m.ready( self.name ):
                raise VmError( f"{self.m.said} is not set up for this declaration -- errand setup --env {self.env.name}" )
        else:
            if self.host.shell( ready_line( self.name, keyed = True ), quiet = True ).returncode:
                raise VmError( f"windows is not installed yet {self.said_where} -- errand setup <name>" )
            self.m = Machine( self.host, Facts.of( self.host ), self.name )
        self._held = self.m.using( self.layer.booted(), self.echo )
        self._held.__enter__()
        try:
            self._ship()
            self._push_sync()
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
        """errand's sources into the guest: a tar of this checkout's, on the stdin of one cmd.exe line, unpacked by
        the guest's Python in a directory of this shipping's own, checked against the tar's manifest, then moved
        into place ( `bootstrap.UNPACK_PY` ). Nothing is unpacked when the guest has them already: a sources key
        names one content."""
        from ..vm.common import VmError
        got = self.m.guest( unpack_line( self.src, self.key ), input = bootstrap.package_tar(), capture = True )
        if got.returncode:
            said = ( ( got.stderr or b"" ) + ( got.stdout or b"" ) )
            said = said.decode( errors = "replace" ) if isinstance( said, bytes ) else said
            raise VmError( f"could not copy errand into windows:\n{said.strip()[ -800 : ]}" )

    def _push_sync( self ):
        """The project, and its `also` checkouts, from here into the guest, by manifest through the guest's own agent."""
        from ..agents import syncop
        from ..vm.common import VmError
        from .. import sync as S
        from ..layers import gateways
        conn = self.host_conn()
        cache = config.state( self.where.root ) / "sync"
        for rel in [ None, *self.layer.also ]:
            local = self.where.root if rel is None else Path( os.path.normpath( self.where.root / rel ) )
            there = self.there if rel is None else posixpath.normpath( f"{self.there}/{rel}" )
            self.echo( f"  sync push -> windows:{there}" )
            try:
                r = syncop.push( conn, local, there, gateways.selection( local, follow_links = True ),
                                 src_cache = cache / f"guest-{hashlib.sha1( str( local ).encode() ).hexdigest()[ : 10 ]}.json",
                                 where = "windows", say = self.echo )
            except S.SyncError as err:
                raise VmError( f"could not copy the project into windows: {err}" ) from None
            for name in r.deleted[ : 20 ]:
                self.echo( f"    deleted on windows: {name}" )
            if len( r.deleted ) > 20:
                self.echo( f"    ...and {len( r.deleted ) - 20} more" )
            if r:
                self.echo( f"    {len( r.sent )} sent ( {r.bytes / 1e6:.1f} MB ), {len( r.touched )} touched, "
                           f"{len( r.deleted )} deleted" )

    # -- the agent there, and sessions ------------------------------------------

    def _keep( self ) -> int:
        return int( getattr( self.env, "keep_alive", None ) or U.KEEP_ALIVE )

    def _target( self, name: str, guest: str ) -> dict:
        """The stream to an agent of the guest, started there by `guest` ( a cmd.exe line ), from here."""
        on_host = L.sh( [ *self.m._reach( "ssh", "-p" ), "-T", self.m.address, guest ] )
        ssh = self.where.ssh
        if self.box:
            argv = [ *self.m._reach( "ssh", "-p" ), "-T", self.m.address, guest ]
        elif ssh is None:
            argv = [ "sh", "-c", on_host ]
        else:
            argv = [ *U.rsh_argv( ssh.host, ssh.options, via = None ), ssh.host, on_host ]
        return { "kind": "cmd", "id": f"{self.said_where}:{name}:{self.m.port}", "argv": argv, "keep_alive": self._keep() }

    def target( self ) -> dict:
        """The guest's environment agent: started through the layer and those after it ( `cd`, vcvars, variables )."""
        keep = self._keep()
        ctx = L.Context( root = Path( self.there ), tags = self.tags, remote = True )

        def line_for( where_ ):
            cmd = L.Command( [ "python", self.boot, "-m", "errand.agents", "connect", where_, str( keep ) ] )
            return self.layer.line( L.compose( self.inner, cmd, ctx ), self.there )

        digest = hashlib.sha1( f"{self.env.name}\0{line_for( '@' )}".encode() ).hexdigest()[ : 10 ]
        name = f"env-{self.key}-{digest}"
        return self._target( name, line_for( f"C:/errand/agents/{name}" ) )

    def host_target( self ) -> dict:
        """An agent of the guest that no layer starts, as the host agent of an `Ssh`: what files cross through. It
        needs nothing of the project, which is not there yet when it starts."""
        name = f"host-{self.key}"
        return self._target( name, subprocess.list2cmdline(
            [ "python", self.boot, "-m", "errand.agents", "connect", f"C:/errand/agents/{name}", str( self._keep() ) ] ) )

    def host_conn( self ):
        if getattr( self, "_host_conn", None ) is None:
            self._host_conn = agents.open( self.host_target() )
        return self._host_conn

    def start( self, request: dict, child: dict ):
        request = { **request, "root": self.there }
        self.target_ = self.target()
        conn = agents.open( self.target_ )
        python = conn.ping()[ "python" ]
        return Session.start( conn, [ python, self.boot, "-m", "errand.agents.ops", "session", json.dumps( request ) ],
                              cwd = self.there, env = child, store = f"{self.there}/{config.state_rel( Path( self.there ) )}/procs" )

    def fetch( self, paths, runs = False, keep = False ):
        """`runs`: the paths are run trees, whose runs come back once finished. `keep`: caches ( ADR 0012 )."""
        if not paths:
            return
        from .. import sync as S
        from ..agents import syncop
        from ..layers.base import WINDOWS
        self.echo( f"  sync pull  <- windows:{self.there} [{', '.join( paths )}]" )
        syncop.pull( self.host_conn(), self.there, self.where.root, [ Path( p ).as_posix() for p in paths ],
                     where = "windows", say = self.echo, links = not WINDOWS, finished_only = runs, keep = keep,
                     sel = S.Selection( [ ".errand-work" ] ) if keep else None )


def unpack_line( src: str, key: str ) -> str:
    """cmd.exe: a tar.gz of errand's package on stdin into `<src>/errand`, unless it holds these sources already.
    Two shippings at once each unpack in a directory of their own, and a copy is said whole ( `.sources` ) only
    once every file the tar lists is there: an interrupted copy is never taken for one."""
    return bootstrap.unpack_py_line( "python", f"{src}/errand", key )