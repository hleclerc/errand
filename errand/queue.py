"""Sharing the machine.

A timing taken while something else was running is not a timing, so an entry
that says it needs the machine gets it -- not just against its own siblings,
but against every other `errand` on the host, in another terminal, on another
project. That means state outside the process, and the smallest honest form of
it is a directory of claims.

    <queue>/claims/<host>-<pid>-<n>.yaml    one file per held claim
    <queue>/lock                            held only while deciding

A claim is TOUCHED while the work lives. One whose timestamp has gone stale is
reclaimed, and its owner, if it ever comes back, is told it lost it. That is
the only honest way to tell a killed run from a long one: a benchmark that has
been running for six hours is indistinguishable from a corpse except by
whether anything is still breathing.

WHEN SOMEBODY ELSE OWNS THE MACHINE, ERRAND DOES NOT QUEUE. Inside a Slurm,
PBS, OAR or LSF allocation the scheduler has already decided what this process
may have, and a second queue on top of it would only wait for itself. See
`someone_else_is_scheduling`.
"""
from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import yamlish

HEARTBEAT   = 5.0      # seconds between touches
STALE_AFTER = 30.0     # a claim older than this has nobody breathing for it
POLL        = 0.25

# Every batch system announces itself in the environment of the job it starts.
ALLOCATION_VARS = ( "SLURM_JOB_ID", "PBS_JOBID", "OAR_JOB_ID", "LSB_JOBID",
                    "SGE_TASK_ID", "FLUX_JOB_ID" )


def someone_else_is_scheduling( ) -> str | None:
    """The name of the scheduler that already owns this process, if any."""
    for var in ALLOCATION_VARS:
        if os.environ.get( var ):
            return var.split( "_" )[ 0 ].lower()
    return None


def host( ) -> str:
    return socket.gethostname().split( "." )[ 0 ] or "localhost"


def queue_dir( ) -> Path:
    """Per user AND per host.

    Per host matters more than it looks: a home directory shared over NFS is
    normal on a cluster, and a queue under it would merge machines that share
    nothing but a filesystem -- one host would wait on another's benchmark.
    """
    base = os.environ.get( "XDG_RUNTIME_DIR" )
    # Set is not the same as usable: a service, a container or a cron job can
    # inherit the variable without the directory existing, and creating it
    # would mean creating /run/user, which is not ours to create.
    if not ( base and os.path.isdir( base ) and os.access( base, os.W_OK ) ):
        base = tempfile.gettempdir()
    uid = os.getuid() if hasattr( os, "getuid" ) else 0
    return Path( base ) / f"errand-queue-{uid}-{host()}"


# ── what the machine has ─────────────────────────────────────────────────────

def parse_size( value ) -> float:
    """`8G`, `512M`, `2048` (MB) -> MB."""
    if value is None:
        return 0.0
    if isinstance( value, ( int, float ) ):
        return float( value )
    text = str( value ).strip().upper().rstrip( "B" )
    scale = { "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024 }
    if text and text[ -1 ] in scale:
        return float( text[ : -1 ] ) * scale[ text[ -1 ] ]
    return float( text )


def _total_ram_mb( ) -> float:
    try:
        return os.sysconf( "SC_PAGE_SIZE" ) * os.sysconf( "SC_PHYS_PAGES" ) / ( 1024 * 1024 )
    except ( ValueError, OSError, AttributeError ):
        return 0.0


def _gpu_count( ) -> int:
    try:
        got = subprocess.run( [ "nvidia-smi", "-L" ], capture_output = True, text = True,
                              timeout = 10 )
        return len( [ l for l in got.stdout.splitlines() if l.strip() ] ) if not got.returncode else 0
    except ( OSError, subprocess.SubprocessError ):
        return 0


_capacity: dict | None = None


def capacity( ) -> dict:
    global _capacity
    if _capacity is None:
        _capacity = { "cpus": float( os.cpu_count() or 1 ),
                      "ram" : _total_ram_mb(),
                      "gpus": float( _gpu_count() ) }
    return dict( _capacity )


def normalize( needs: dict ) -> dict:
    """An entry's `cpus=4, ram="8G"` as numbers in the machine's own units."""
    out = { }
    for key, value in ( needs or { } ).items():
        out[ key ] = parse_size( value ) if key == "ram" else float( value )
    return out


# ── the claims ───────────────────────────────────────────────────────────────

def _claims_dir( ) -> Path:
    d = queue_dir() / "claims"
    d.mkdir( parents = True, exist_ok = True )
    return d


def held( ) -> list:
    """Every live claim, stale ones cleared away as they are noticed."""
    out, now = [ ], time.time()
    for path in sorted( _claims_dir().glob( "*.yaml" ) ):
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age > STALE_AFTER:
            # Nobody has breathed for it. Reclaim it; its owner, if it ever
            # comes back, finds its own claim gone and is told so.
            path.unlink( missing_ok = True )
            continue
        row = yamlish.read( path )
        if row:
            row[ "path" ] = str( path )
            out.append( row )
    return out


@contextlib.contextmanager
def _lock( ):
    """Held only while deciding, never while working."""
    try:
        import fcntl
    except ImportError:                     # a platform without flock: decide unguarded
        yield
        return
    path = queue_dir() / "lock"
    path.parent.mkdir( parents = True, exist_ok = True )
    handle = os.open( path, os.O_CREAT | os.O_RDWR, 0o600 )
    try:
        fcntl.flock( handle, fcntl.LOCK_EX )
        yield
    finally:
        os.close( handle )


def _fits( needs: dict, exclusive: bool, others: list ) -> str | None:
    """None when it fits, else what it is waiting for."""
    if exclusive and others:
        return f"the machine to itself ({len( others )} running)"
    if any( o.get( "exclusive" ) for o in others ):
        owner = next( o for o in others if o.get( "exclusive" ) )
        return f"{owner.get( 'label', 'something' )}, which has the machine to itself"

    have = capacity()
    for key, wanted in needs.items():
        used = sum( float( o.get( key, 0 ) or 0 ) for o in others )
        total = have.get( key, 0.0 )
        if total and wanted > total:
            # Asking for more than exists would wait for ever. Let it through
            # alone rather than deadlock on an impossible promise.
            return None if not others else f"the machine to itself (needs {key}={wanted:g} of {total:g})"
        if total and used + wanted > total:
            return f"{key} ({used:g} of {total:g} taken, needs {wanted:g})"
    return None


@contextlib.contextmanager
def claim( needs: dict, *, exclusive = False, label = "", enabled = True, echo = None ):
    """Hold a share of the machine for the duration of the block."""
    scheduler = someone_else_is_scheduling()
    if not enabled or os.environ.get( "ERRAND_NO_QUEUE" ) or scheduler:
        if scheduler and echo:
            echo( f"  ({scheduler} already decided what this process may have)" )
        yield None
        return

    needs = normalize( needs )
    mine = _claims_dir() / f"{host()}-{os.getpid()}-{time.time_ns()}.yaml"
    waited_for = None

    while True:
        with _lock():
            others = [ o for o in held() if o[ "path" ] != str( mine ) ]
            waiting = _fits( needs, exclusive, others )
            if waiting is None:
                yamlish.write( mine, { "label": label, "pid": os.getpid(), "host": host(),
                                       "exclusive": exclusive, "since": time.time(), **needs } )
                break
        if echo and waiting != waited_for:
            echo( f"  waiting for {waiting}" )
            waited_for = waiting
        time.sleep( POLL )

    stop = threading.Event()
    beat = threading.Thread( target = _heartbeat, args = ( mine, stop ), daemon = True )
    beat.start()
    try:
        yield mine
    finally:
        stop.set()
        beat.join( timeout = 1.0 )
        mine.unlink( missing_ok = True )


def _heartbeat( path: Path, stop: threading.Event ):
    while not stop.wait( HEARTBEAT ):
        try:
            os.utime( path, None )
        except OSError:
            return      # reclaimed while we were away; nothing to keep alive


def describe( ) -> list:
    """One line per live claim, for a banner or a monitor."""
    out = [ ]
    for row in held():
        what = "the whole machine" if row.get( "exclusive" ) else ", ".join(
            f"{k}={row[ k ]:g}" for k in ( "cpus", "ram", "gpus" ) if row.get( k ) ) or "a slot"
        age = time.time() - float( row.get( "since", time.time() ) )
        out.append( f"{row.get( 'label', '?' )}  {what}  {age:.0f}s  pid {row.get( 'pid' )}" )
    return out
