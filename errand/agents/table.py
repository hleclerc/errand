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


def describe( meta: dict ) -> dict:
    """What a person reads of a process: its project, what it does."""
    argv = [ str( a ) for a in meta.get( "argv" ) or [ ] ]
    out = { "project": None, "what": " ".join( argv )[ : 160 ] }
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
    elif "errand.vm" in argv:
        verb = argv[ argv.index( "errand.vm" ) + 1 ] if argv.index( "errand.vm" ) + 1 < len( argv ) else ""
        out.update( what = { "keep": "windows vm keeper", "use": "a command's hold on a windows vm" }.get( verb, f"errand.vm {verb}" ),
                    vm = True )
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
        rows.append( { "agent": d.name, "agent_alive": alive, "id": m.name, "pid": meta.get( "pid" ) or meta.get( "pgid" ),
                       "started": meta.get( "started" ), "keep": bool( meta.get( "keep" ) ),
                       "state": "running" if alive else "orphaned", **describe( meta ) } )
    return rows


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


def _parsed( got ):
    for line in reversed( ( got.stdout or "" ).splitlines() ):
        if line.startswith( "errand-table " ):
            try:
                return json.loads( line[ len( "errand-table " ) : ] )
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


def scan( guests = True ) -> dict:
    procs = [ ]
    dirs = agent_dirs( roots() )
    for d in dirs:
        procs += procs_of( d, served( d ) )
    procs += strays( { int( p[ "pid" ] ) for p in procs if p.get( "pid" ) } )
    cache = bootstrap.local_cache()
    machines = vms( cache )
    asked = [ ]
    if guests:
        for vm in machines:
            if vm[ "state" ] == "ready" and vm.get( "port" ) and vm.get( "image" ):
                asked.append( { "vm": vm[ "name" ], **guest_table( vm ) } )
    return { "host": socket.gethostname(), "time": time.time(), "procs": procs, "vms": machines, "guests": asked,
             "zygotes": zygotes( dirs ) }


def main() -> int:
    print( "errand-table " + json.dumps( scan( guests = "--no-guests" not in sys.argv ) ), flush = True )
    return 0
