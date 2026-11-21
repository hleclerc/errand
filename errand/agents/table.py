"""What runs on this machine on errand's behalf, read from disk: `python -m errand.agents table`.

    { "host", "procs": [ … ], "vms": [ … ], "guests": [ { "vm", "error" | "procs" } ] }

Every agent writes what it owns in its directory ( `proc/<id>/meta.json`: the pid, the group and when
it started, ADR 0008 ), so this machine can say what runs here -- started from here or from anywhere
else, through whichever agent -- without asking an agent and without starting one: a lock tells
whether the agent of a directory is alive, a pid and a start time whether what it started still runs.
What still runs under a directory whose agent is gone is an orphan ( the next agent there kills it ).

The machines errand boots are here too ( their keeper's directory, `vm/` ), and what runs in each
guest that is up, asked of the guest the same way, over its ssh.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from .. import bootstrap
from . import endpoint
from .procs import locate, ours, WINDOWS


def agent_dirs( roots ) -> list:
    """Every agent directory under errand's per-user directories: `agents/<name>`, `alloc/<name>/<job>`,
    `vm-agent`, at most two levels down."""
    seen = [ ]
    for base in roots:
        for d in [ *base.glob( "*" ), *base.glob( "*/*" ), *base.glob( "*/*/*" ) ]:
            if d.is_dir() and ( d / "lock" ).exists() and ( d / "proc" ).is_dir() and d not in seen:
                seen.append( d )
    return seen


def served( d: Path ) -> bool:
    """Is the agent of `d` alive: it holds its lock. Taken for an instant otherwise, as `sweep` does."""
    held = endpoint.hold( d / "lock" )
    if held is None:
        return True
    held.close()
    return False


def pid_runs( pid ) -> bool:
    if not pid:
        return False
    if WINDOWS:
        import ctypes
        k = ctypes.WinDLL( "kernel32" )
        k.OpenProcess.restype = ctypes.c_void_p
        h = k.OpenProcess( 0x1000, False, int( pid ) )          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess( ctypes.c_void_p( h ), ctypes.byref( code ) )
        k.CloseHandle( ctypes.c_void_p( h ) )
        return code.value == 259                                # STILL_ACTIVE
    try:
        os.kill( int( pid ), 0 )
        return True
    except ( ProcessLookupError, PermissionError, OSError ):
        return False


ALLOCATION_MARK = "errand-allocation"


def allocation_mark( **said ) -> str:
    """The first line of a login node's hold on an allocation: who it is for, readable from its argv."""
    import base64
    return f": {ALLOCATION_MARK} {base64.urlsafe_b64encode( json.dumps( said ).encode() ).decode()}"


def _allocation_mark( text: str ) -> dict:
    import base64
    got = re.search( ALLOCATION_MARK + r" ([A-Za-z0-9_=-]+)", text )
    try:
        return json.loads( base64.urlsafe_b64decode( got.group( 1 ).encode() ).decode() ) if got else { }
    except ValueError:
        return { }


def describe( meta: dict ) -> dict:
    """What a person reads of a process: its project, what it does."""
    argv = [ str( a ) for a in meta.get( "argv" ) or [ ] ]
    line = " ".join( argv )
    out = { "project": None, "what": line[ : 160 ] }
    if "errand.agents.ops" in argv and argv[ -2 : -1 ] == [ "session" ]:
        try:
            req = json.loads( argv[ -1 ] )
        except ValueError:
            req = { }
        known = req.get( "known" ) or { }
        target = " ".join( str( a ) for a in [ known.get( "pattern" ) or "", *( known.get( "target_args" ) or [ ] ) ] if a )
        label = f" [{known[ 'label' ]}]" if known.get( "label" ) else ""
        out.update( project = req.get( "root" ), env = req.get( "env" ),
                    what = f"{req.get( 'verb', 'run' )} {target}{label}".strip() )
    elif ALLOCATION_MARK in line:
        # The login node's hold on a Slurm allocation ( `alive.Allocation.script` ), started through
        # `rsh` with no directory: its first line says whose it is.
        said = _allocation_mark( line )
        out.update( project = said.get( "project" ), env = said.get( "env" ), kind = "allocation",
                    what = f"slurm allocation {str( said.get( 'name' ) or '' )[ : 8 ]}".strip() )
    elif "errand.agents connect " in line:
        # A bridge to an environment agent ( `envs.py`, `alive.env_target` ): `cd <root> && … connect DIR`.
        root = re.search( r"cd ('[^']*'|\S+) &&", line )
        where = re.search( r"errand\.agents connect (\S+)", line )
        name = Path( where.group( 1 ).strip( "'\"" ) ).name if where else ""
        out.update( project = root.group( 1 ).strip( "'" ) if root else None, kind = "agent",
                    what = f"environment agent {name}".strip() )
    elif "errand.vm" in argv:
        verb = argv[ argv.index( "errand.vm" ) + 1 ] if argv.index( "errand.vm" ) + 1 < len( argv ) else ""
        # The keeper is the machine's own ( shown with the machines ); a command's hold is that
        # command's, under its project, with what it waits for.
        out.update( what = { "keep": "windows vm keeper", "use": "a command's hold on a windows vm" }.get( verb, f"errand.vm {verb}" ),
                    vm = verb == "keep" )
    if not out[ "project" ] and meta.get( "store" ):
        store = Path( meta[ "store" ] )                         # <root>/errand-outputs/state/procs, or under builds_directory
        out[ "project" ] = str( store.parent.parent.parent ) if store.parent.name == "state" else str( store )
    if not out[ "project" ]:
        out[ "project" ] = meta.get( "cwd" )
    return out


def procs_of( d: Path, alive: bool ) -> list:
    rows = [ ]
    for m in sorted( ( d / "proc" ).glob( "*" ) ):
        where = locate( d, m.name ) or m
        try:
            meta = json.loads( ( where / "meta.json" ).read_text() )
        except ( OSError, ValueError ):
            continue
        if ( where / "exit" ).exists():
            continue
        if meta.get( "pgid" ) and not WINDOWS:
            runs = ours( meta[ "pgid" ], meta.get( "since" ) )
        elif meta.get( "pid" ):
            runs = pid_runs( meta[ "pid" ] )
        else:
            runs = alive            # an older errand's record: its agent knows, and is there or not
        if not runs:
            continue
        from .arrival import read as waits
        rows.append( { "agent": d.name, "agent_alive": alive, "id": m.name, "pid": meta.get( "pid" ) or meta.get( "pgid" ),
                       "started": meta.get( "started" ), "keep": bool( meta.get( "keep" ) ),
                       "state": "running" if alive else "orphaned", "waiting": waits( m ), **describe( meta ),
                       "dir": str( where ), "mark": str( m ), "leaf": _leaf( m ), "step": _step( m ), "pgid": meta.get( "pgid" ), "since": meta.get( "since" ),
                       "cwd": meta.get( "cwd" ) } )
    return rows


def _leaf( mark: Path ) -> str | None:
    """The directory of the case it runs now ( `seen.note` ), if it said."""
    try:
        return ( mark / "leaf" ).read_text().strip() or None
    except OSError:
        return None


def _step( mark: Path ) -> dict | None:
    """Where the case running now is, from its journal ( ADR 0010 ): `steps.summary`."""
    leaf = _leaf( mark )
    if not leaf:
        return None
    from .. import steps
    return steps.summary( Path( leaf ) / steps.FILE )


def zygotes( dirs ) -> list:
    """What keeps imports warm beside an agent ( `warm` ), by the pid it writes once it holds its
    lock -- never by taking that lock, which a zygote starting must find free."""
    rows = [ ]
    for d in dirs:
        try:
            pid = int( ( d / "warm" / "pid" ).read_text() )
        except ( OSError, ValueError ):
            continue
        if pid_runs( pid ):
            rows.append( { "agent": d.name, "pid": pid, "agent_alive": served( d ) } )
    return rows


def vms( cache: Path ) -> list:
    """The machines whose keeper is on this machine, up or left over."""
    from ..vm.common import _alive, _read
    rows = [ ]
    for d in sorted( ( cache / "vm" ).glob( "*" ) ) if ( cache / "vm" ).is_dir() else [ ]:
        keeper, qemu = _read( d / "keeper.pid" ), _read( d / "qemu.pid" )
        keeper_up, qemu_up = _alive( keeper ), _alive( qemu )
        if not ( keeper_up or qemu_up ):
            continue
        try:
            config = json.loads( ( d / "config.json" ).read_text() )
        except ( OSError, ValueError ):
            config = { }
        rows.append( { "dir": str( d ), "name": d.name, "state": _read( d / "state", "?" ) if keeper_up else "orphaned",
                       "keeper": keeper, "qemu": qemu, "image": config.get( "image" ), "port": _read( d / "port" ),
                       "cpus": config.get( "cpus" ), "ram": config.get( "ram" ) } )
    return rows


def guest_table( vm: dict, timeout = 40 ) -> dict:
    """Asked of a guest that is up, over its ssh: the same table, from the errand copied in there."""
    from ..vm.common import GUEST_OPTIONS, USER
    boot = f"C:/errand/src/{bootstrap.sources_key()}/errand/_boot.py"
    argv = [ "ssh", "-p", str( vm[ "port" ] ), "-i", f"{vm[ 'image' ]}/key", *GUEST_OPTIONS, f"{USER}@127.0.0.1",
             f'if exist "{boot}" ( python "{boot}" -m errand.agents table ) else ( echo errand-none )' ]
    try:
        got = subprocess.run( argv, capture_output = True, text = True, timeout = timeout, stdin = subprocess.DEVNULL )
    except subprocess.TimeoutExpired:
        return { "error": "the guest did not answer" }
    if "errand-none" in got.stdout:
        return { "procs": [ ], "note": "no errand of these sources in it" }
    return _parsed( got ) or { "error": ( got.stderr or got.stdout or "" ).strip()[ -300 : ] or f"exit {got.returncode}" }


def guest_caches( vm: dict, req: dict, timeout = 120 ) -> dict:
    """A `caches` op asked of a guest that is up, over its ssh ( `python -m errand.agents caches REQUEST` ), as
    `guest_table` asks its table ( ADR 0022 )."""
    from ..vm.common import GUEST_OPTIONS, USER
    boot = f"C:/errand/src/{bootstrap.sources_key()}/errand/_boot.py"
    said = json.dumps( req ).replace( '"', '\\"' )
    argv = [ "ssh", "-p", str( vm[ "port" ] ), "-i", f"{vm[ 'image' ]}/key", *GUEST_OPTIONS, f"{USER}@127.0.0.1",
             f'if exist "{boot}" ( python "{boot}" -m errand.agents caches "{said}" ) else ( echo errand-none )' ]
    try:
        got = subprocess.run( argv, capture_output = True, text = True, timeout = timeout, stdin = subprocess.DEVNULL )
    except subprocess.TimeoutExpired:
        return { "error": "the guest did not answer" }
    if "errand-none" in got.stdout:
        return { "dirs": [ ], "note": "no errand of these sources in it" }
    return _parsed( got, "errand-caches " ) or { "error": ( got.stderr or got.stdout or "" ).strip()[ -300 : ] or f"exit {got.returncode}" }


def _parsed( got, mark = "errand-table " ):
    for line in reversed( ( got.stdout or "" ).splitlines() ):
        if line.startswith( mark ):
            try:
                return json.loads( line[ len( mark ) : ] )
            except ValueError:
                return None
    return None


def strays( owned_groups: set ) -> list:
    """Linux: the processes errand started ( `ERRAND_AGENT_DIR` in their environment ) whose agent is
    gone and that no record holds -- an agent's directory removed under them, an errand from before
    records said who they are. One row per process group, said by its most telling member."""
    if not sys.platform.startswith( "linux" ):
        return [ ]
    groups = { }
    me = os.getuid()
    for p in Path( "/proc" ).glob( "[0-9]*" ):
        try:
            if p.stat().st_uid != me:
                continue
            env = ( p / "environ" ).read_bytes()
            if b"ERRAND_AGENT_DIR=" not in env:
                continue
            agent = next( v.split( b"=", 1 )[ 1 ].decode() for v in env.split( b"\0" ) if v.startswith( b"ERRAND_AGENT_DIR=" ) )
            argv = [ a.decode( errors = "replace" ) for a in ( p / "cmdline" ).read_bytes().split( b"\0" ) if a ]
            stat = ( p / "stat" ).read_text().rsplit( ")", 1 )[ 1 ].split()
            pgid, start = int( stat[ 2 ] ), stat[ 19 ]
        except ( OSError, ValueError, StopIteration, IndexError ):
            continue
        if pgid in owned_groups or any( "errand.agents" == a for a in argv ) and ( "serve" in argv or "connect" in argv ):
            continue
        groups.setdefault( pgid, [ ] ).append( ( int( p.name ), agent, argv, start ) )
    rows = [ ]
    tick = os.sysconf( "SC_CLK_TCK" )
    with open( "/proc/uptime" ) as f:
        boot = time.time() - float( f.read().split()[ 0 ] )
    alive = { }
    for pgid, members in groups.items():
        agent = members[ 0 ][ 1 ]
        if agent not in alive:
            alive[ agent ] = Path( agent ).is_dir() and ( Path( agent ) / "lock" ).exists() and served( Path( agent ) )
        if alive[ agent ]:
            continue                 # an agent there owns it, recorded or not ( a zygote's work )
        pid, _, argv, start = min( members, key = lambda m: ( "errand.agents.ops" not in m[ 2 ], m[ 0 ] ) )
        rows.append( { "agent": Path( agent ).name, "agent_alive": False, "id": f"pgid-{pgid}", "pid": pid, "pgid": pgid,
                       "started": boot + int( min( m[ 3 ] for m in members ) ) / tick, "keep": False,
                       "state": "unowned", **describe( { "argv": argv, "cwd": os.readlink( f"/proc/{pid}/cwd" ) if os.path.exists( f"/proc/{pid}/cwd" ) else None } ) } )
    return rows


def roots() -> list:
    out = [ bootstrap.local_cache() ]
    if WINDOWS and Path( "C:/errand" ).is_dir():
        out.append( Path( "C:/errand" ) )                      # a guest's agents: C:/errand/agents/<name>
    return out


def allocations( cache: Path ) -> list:
    """The allocations kept warm from this machine whose job runs now: ( agent directory, job, first
    node ). Their agents run on a compute node, where neither their locks nor their pids can be read
    from here: each is asked there ( `node_table` )."""
    import shutil
    jobs = [ d for d in ( cache / "alloc" ).glob( "*/[0-9]*" ) if d.is_dir() and ( d / "proc" ).is_dir() ] \
        if ( cache / "alloc" ).is_dir() else [ ]
    if not jobs or not shutil.which( "squeue" ):
        return [ ]
    try:
        got = subprocess.run( [ "squeue", "-h", "-t", "RUNNING", "-o", "%i %N", "-j", ",".join( d.name for d in jobs ) ],
                              capture_output = True, text = True, timeout = 30, stdin = subprocess.DEVNULL )
        running = dict( line.split( None, 1 ) for line in got.stdout.splitlines() if len( line.split() ) == 2 )
    except ( OSError, subprocess.TimeoutExpired ):
        return [ ]
    out = [ ]
    for d in jobs:
        nodes = running.get( d.name )
        if nodes:
            try:
                first = subprocess.run( [ "scontrol", "show", "hostnames", nodes ], capture_output = True, text = True,
                                        timeout = 30, stdin = subprocess.DEVNULL ).stdout.split()[ 0 ]
            except ( OSError, subprocess.TimeoutExpired, IndexError ):
                first = nodes
            out.append( ( d, d.name, first ) )
    return out


def node_table( d: Path, job: str, node: str, timeout = 60 ) -> dict:
    """What the agents of an allocation run, read on its first node ( `table --only DIR` ) through
    `srun --overlap`: no agent asked, none started, and nothing new asked of Slurm."""
    if node.split( "." )[ 0 ] == socket.gethostname().split( "." )[ 0 ]:
        return scan( guests = False, only = d )
    import shlex
    cache = bootstrap.local_cache()
    boot = cache / bootstrap.boot_rel()
    then = f"exec \"$py\" {shlex.quote( str( boot ) )} -m errand.agents table --only {shlex.quote( str( d ) )}\n"
    reader = [ "sh", "-c", bootstrap._script( then, "python3" ) ] if boot.exists() else \
             [ sys.executable, "-m", "errand.agents", "table", "--only", str( d ) ]
    argv = [ "srun", "-u", f"--jobid={job}", "--overlap", "-N1", "-n1", "-w", node, *reader ]
    try:
        got = subprocess.run( argv, capture_output = True, text = True, timeout = timeout, stdin = subprocess.DEVNULL )
    except ( OSError, subprocess.TimeoutExpired ) as err:
        return { "error": f"node {node} did not answer ( {type( err ).__name__} )" }
    return _parsed( got ) or { "error": ( got.stderr or got.stdout or "" ).strip()[ -300 : ] or f"exit {got.returncode}" }


def scan( guests = True, only: Path | None = None, resources = True ) -> dict:
    """What runs on this machine. `only`: the agents under one directory ( an allocation's, read on its
    node ), and nothing else. `resources`: what they are doing too ( `resources.measure` ); a subscription
    measures them at its own pace ( `look.Watch` )."""
    procs = [ ]
    if only is not None:
        dirs = [ only ] if ( only / "lock" ).exists() and ( only / "proc" ).is_dir() else [ ]
        dirs += [ d for d in agent_dirs( [ only ] ) if d not in dirs ]
        for d in dirs:
            procs += procs_of( d, served( d ) )
        return { "host": socket.gethostname(), "time": time.time(), "procs": procs, "vms": [ ], "guests": [ ],
                 "nodes": [ ], "zygotes": zygotes( dirs ), "resources": _resources() if resources else None }
    cache = bootstrap.local_cache()
    held = allocations( cache )
    elsewhere = { d for d, _, _ in held }
    dirs = [ d for d in agent_dirs( roots() ) if d not in elsewhere ]
    for d in dirs:
        procs += procs_of( d, served( d ) )
    procs += strays( { int( p[ "pid" ] ) for p in procs if p.get( "pid" ) } )
    machines = vms( cache )
    asked = [ ]
    if guests:
        for vm in machines:
            if vm[ "state" ] == "ready" and vm.get( "port" ) and vm.get( "image" ):
                asked.append( { "vm": vm[ "name" ], **guest_table( vm ) } )
    nodes = [ { "node": node, "job": job, **node_table( d, job, node ) } for d, job, node in held ]
    return { "host": socket.gethostname(), "time": time.time(), "procs": procs, "vms": machines, "guests": asked,
             "nodes": nodes, "zygotes": zygotes( dirs ), "services": _services(),
             "resources": _resources() if resources else None }


def _services( ) -> list:
    """The services this machine keeps ( `errand serve`, ADR 0018 ): what each does."""
    try:
        from .. import serve
        return [ { k: s.get( k ) for k in ( "name", "state", "detail", "address", "ports", "connections", "waiting", "label",
                                            "source" ) }
                 for s in serve.listed() ]
    except Exception:
        return [ ]


def caches_summary( ) -> dict | None:
    """The library caches this machine holds, read as they are ( `caches.report`, ADR 0022 ): `errand status`."""
    try:
        from .. import caches
        return caches.report( compacted = False )
    except Exception as err:
        return { "error": f"{type( err ).__name__}: {err}" }


def _resources( ) -> dict | None:
    """What the machine's resources are doing ( `resources` ): never the table's failure."""
    try:
        from . import resources
        return resources.measure()
    except Exception:
        return None


def main() -> int:
    args = sys.argv[ 1 : ]
    only = Path( args[ args.index( "--only" ) + 1 ] ) if "--only" in args[ : -1 ] else None
    got = scan( guests = "--no-guests" not in args, only = only )
    if "--caches" in args:
        got[ "caches" ] = caches_summary()
    print( "errand-table " + json.dumps( got ), flush = True )
    return 0
