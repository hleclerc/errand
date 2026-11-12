"""The `Windows` layer: what is declared, what it is built from, and how a command reaches the guest.
"""
from __future__ import annotations

import posixpath
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .. import layers as L
from .common import _backslashed, _sh, VmError, where
from .places import images_dir
from .facts import Facts, need, package_hint
from .datadisk import DATA_DRIVE, FLUSH_SCRIPT, powershell
from .machine import Machine
from .install import install
from .guest import EVALUATION_ISO, VCVARS


REBUILD_AFTER  = 170         # days: rebuilt a little before the 180 run out and Windows starts shutting itself down

# Bumped whenever what an image is made of changes in this file: the recipe is
# part of the declaration, and an edit to it must be noticed like any other.
RECIPE = 2


@dataclass
class Windows:
    """First, or right after the `Ssh` that leads to the machine that boots it.
    Everything after it runs on Windows.

    Every argument has a default that covers the common case -- compiling and
    testing native code -- so most declarations name none of them.
    """
    iso      : str | None = None     # a path or a URL; None is the evaluation
    key      : str | None = None     # a product key; None is the evaluation, which needs none
    index    : int = 1               # which image of the ISO: 1 is Server Core on the evaluation
    cpus     : int = 4
    ram      : str = "8G"
    disk     : str = "64G"           # grows as it is written, up to this
    msvc     : bool = True           # the build tools, and vcvars64 before every command
    python   : str | None = None     # "3.13.1": that python.org release, on PATH
    provision: list = field( default_factory = list )   # PowerShell: a `.ps1` of the project, or a line
    fetch    : list = field( default_factory = list )   # what to bring back after each command
    also     : list = field( default_factory = list )   # sibling checkouts the work needs ( `../loom` ), copied in beside the project
    keep     : str = "0"             # how long it stays up once no errand process holds it any more
    data     : str | None = "32G"    # a disk kept from one boot to the next, as E:, where the project
                                     # lands -- so what a command leaves ( a build ) is there for the next
                                     # one. Grows as it is written, up to this; None: everything is C:, reset
    root     : str | None = None     # where the project goes; C:/errand/<project name>
    when     : str | None = None     # a condition: an expression over the tags and `phase`

    # Not a field: what `layers.vm_of` recognizes, like `Ssh` is recognized by its class.
    is_vm = True

    def wrap( self, cmd: L.Command, ctx: L.Context ) -> L.Command:
        # Never folded: `run` takes over, as for Ssh -- getting there means
        # booting, copying in, and fetching afterwards.
        raise RuntimeError( "Windows must be the first layer of an environment, or follow its Ssh" )

    def describe( self ):
        return "windows"

    def declared( self ) -> dict:
        """What is INSTALLED, as opposed to how it is booted."""
        return { "iso": self.iso, "key": self.key, "index": self.index, "disk": self.disk,
                 "msvc": self.msvc, "python": self.python, "provision": list( self.provision ) }

    def booted( self ) -> dict:
        return { "cpus": self.cpus, "ram": self.ram, "keep": self.keep, "data": self.data }

    # -- kept current, like any other layer ----------------------------------

    def spec( self, ctx ) -> list:
        # Read from the project as this process sees it, wherever it runs.
        return _spec( self.declared(), ctx.origin )

    def image_name( self, ctx ) -> str:
        """Named by what it was installed FROM, so two projects declaring the
        same Windows share one image."""
        return L.fingerprint( *self.spec( ctx ) )

    def image( self, ctx ) -> Path:
        """Where the installed disk lives when QEMU runs on this machine."""
        return images_dir() / self.image_name( ctx )

    def probe_shell( self, ctx ) -> str:
        return ready_line( self.image_name( ctx ), keyed = bool( self.key ) )

    def probe( self, ctx ) -> bool:
        return ctx.host.shell( self.probe_shell( ctx ), quiet = True ).returncode == 0

    def build( self, ctx ) -> list:
        return [ Install( self, ctx ) ]

    # -- being let in ---------------------------------------------------------

    def guest_root( self, ctx ) -> str:
        if self.root:
            return self.root
        # On the disk that is kept, when there is one: a copy there is updated
        # rather than made again, and what was built beside it stays.
        return f"{DATA_DRIVE}:/{ctx.root.name}" if self.data else f"C:/errand/{ctx.root.name}"

    def line( self, cmd: L.Command, guest_root: str ) -> str:
        """`cmd` as one cmd.exe line, run from the project's copy over there."""
        parts = [ f'cd /d "{_backslashed( guest_root )}"' ]
        if self.msvc:
            parts.append( f'call "{VCVARS}" >nul' )
        # The quoted form: `set "K=v"` keeps no trailing blank before the `&&`.
        parts += [ f'set "{k}={v}"' for k, v in cmd.env.items() ]
        parts.append( subprocess.list2cmdline( [ str( a ) for a in cmd.argv ] ) )
        return " && ".join( parts )

    def run( self, inner, cmd: L.Command, ctx: L.Context, pull = None, echo = print ):
        there = self.guest_root( ctx )
        # PYTHONPATH as computed here names directories of THIS machine.
        env = { k: v for k, v in cmd.env.items() if k != "PYTHONPATH" }
        wrapped = L.compose( inner, L.Command( L.under( cmd.argv, "python" ), env ),
                             L.Context( root = Path( there ), tags = ctx.tags, remote = True ) )
        if any( "\n" in str( a ) for a in cmd.argv ):
            # cmd.exe reads one line: the rest would be dropped without a word.
            echo( "  a command for windows is one line: cmd.exe would drop everything after a newline "
                  "-- put the script in a file of the project, and run that" )
            return 1
        name = self.image_name( ctx )
        if ctx.host.shell( ready_line( name, keyed = True ), quiet = True ).returncode:
            echo( f"  windows is not installed yet {where( ctx.host )} -- errand setup <name>" )
            return 1
        try:
            m = Machine( ctx.host, Facts.of( ctx.host ), name )
            need( m.facts, ( "rsync", ), package_hint( m.facts, [ "rsync" ] ) )
            with m.using( self.booted(), echo ):
                echo( f"  copy in -> windows:{there}" )
                m.push( there )
                for other in self.also:
                    m.push( posixpath.normpath( f"{there}/{other}" ), f"{other}/" )
                line = self.line( wrapped, there )
                echo( f"  > {line}" )
                code = m.guest( line ).returncode
                if self.data:
                    m.guest( powershell( FLUSH_SCRIPT ), quiet = True )
                wanted = [ *( pull or [ ] ), *self.fetch ]
                if wanted:
                    echo( f"  fetch <- windows:{there} [{', '.join( wanted )}]" )
                    m.fetch( wanted, there )
                return code
        except VmError as err:
            echo( f"  {err}" )
            return 1
        except subprocess.CalledProcessError as err:
            echo( f"  could not copy the project in: {err}" )
            return 1


class Install:
    """`errand setup` for a `Windows` layer, as one step: what it says it would do,
    and the doing -- many lines through `ctx.host`, decided here between them."""

    def __init__( self, layer: Windows, ctx: L.Context ):
        self.layer, self.ctx = layer, ctx

    def __str__( self ):
        return f"install windows {self.layer.image_name( self.ctx )[ : 8 ]} {where( self.ctx.host )}"

    def __call__( self, echo = print ) -> int:
        return install( self.ctx.host, self.layer.image_name( self.ctx ), self.layer.declared(),
                        self.layer.booted(), echo )


def _iso_identity( iso, root: Path ):
    """What an ISO is, for the fingerprint, without reading five gigabytes of it."""
    if not iso:
        return EVALUATION_ISO
    if "://" in iso:
        return iso
    path = Path( iso ).expanduser()
    path = path if path.is_absolute() else root / path
    try:
        st = path.stat()
        return f"{path}:{st.st_size}:{int( st.st_mtime )}"
    except OSError:
        return f"<missing {path}>"


def _provision_part( p: str, root: Path, as_path = False ):
    """A `.ps1` of the project is hashed by content ( or handed over by path ); a
    line of PowerShell is itself."""
    if str( p ).endswith( ".ps1" ):
        path = Path( p ) if Path( p ).is_absolute() else root / p
        return str( path ) if as_path else path
    return { "line": p } if as_path else p


def _spec( declared: dict, root: Path ) -> list:
    # Flat: `fingerprint` reads the CONTENT of a path only at the top level,
    # and a script edited is a script that must be run again.
    return [ RECIPE, _iso_identity( declared[ "iso" ], root ), declared[ "key" ], declared[ "index" ],
             declared[ "disk" ], declared[ "msvc" ], declared[ "python" ],
             *[ _provision_part( p, root ) for p in declared[ "provision" ] ] ]


def ready_line( name: str, keyed: bool ) -> str:
    """A line whose exit code says whether that image is installed -- and, for an
    evaluation, not about to run out -- on the machine that runs it."""
    script = f'r="${{XDG_CACHE_HOME:-$HOME/.cache}}/errand/windows/{name}/ready"; test -f "$r"'
    if not keyed:
        # An evaluation counts down from the day it was installed, and shuts
        # itself down every hour once it has run out -- which would look like a
        # flaky build rather than an expired licence. Rebuilt before that.
        script += f' && test -n "$( find "$r" -mtime -{REBUILD_AFTER} )"'
    return _sh( script )
