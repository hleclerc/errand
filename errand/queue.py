"""Sharing the machine.

A timing taken while something else was running is not a timing, so an entry
that says it needs the machine gets it -- not just against its own siblings,
but against every other `errand` on the host, in another terminal, on another
project. That means state outside the process, and the smallest honest form of
it is a directory of claims.

    <queue>/claims/<host>-<pid>-<n>.yaml    one file per held claim
    <queue>/lock-<host>                     held only while deciding

Every name carries the host, so a file is readable on its own and a queue
directory that somehow ends up shared -- a TMPDIR on a network mount, an
XDG_RUNTIME_DIR someone pointed at a home -- separates machines instead of
merging them. The directory name carries it too; the belt is cheap enough to
wear with the braces.

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
from dataclasses import dataclass
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
    # What the caller can already see, when somebody upstream narrowed it.
    visible = os.environ.get( "CUDA_VISIBLE_DEVICES" )
    if visible is not None:
        return len( [ v for v in visible.split( "," ) if v.strip() ] )
    try:
        got = subprocess.run( [ "nvidia-smi", "-L" ], capture_output = True, text = True,
                              timeout = 10 )
        return len( [ l for l in got.stdout.splitlines() if l.strip() ] ) if not got.returncode else 0
    except ( OSError, subprocess.SubprocessError ):
        return 0


def devices( ) -> list:
    """The device indices this process may use, in the caller's own numbering.

    `CUDA_VISIBLE_DEVICES` renumbers from zero for whoever it is set on, so a
    process that was itself given devices 2 and 5 sees 0 and 1 -- and must hand
    0 and 1 down, not 2 and 5.
    """
    visible = os.environ.get( "CUDA_VISIBLE_DEVICES" )
    if visible is not None:
        return list( range( len( [ v for v in visible.split( "," ) if v.strip() ] ) ) )
    return list( range( int( capacity()[ "gpus" ] ) ) )


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
    path = queue_dir() / f"lock-{host()}"
    path.parent.mkdir( parents = True, exist_ok = True )
    handle = os.open( path, os.O_CREAT | os.O_RDWR, 0o600 )
    try:
        fcntl.flock( handle, fcntl.LOCK_EX )
        yield
    finally:
        os.close( handle )


def taken_devices( others: list ) -> set:
    out = set()
    for o in others:
        for d in ( o.get( "devices" ) or [ ] ):
            out.add( int( d ) )
    return out


def _fits( needs: dict, exclusive: bool, others: list ):
    """( waiting_for, devices ). `waiting_for` is None when it fits."""
    if exclusive and others:
        return f"the machine to itself ({len( others )} running)", [ ]
    if any( o.get( "exclusive" ) for o in others ):
        owner = next( o for o in others if o.get( "exclusive" ) )
        return f"{owner.get( 'label', 'something' )}, which has the machine to itself", [ ]

    have = capacity()
    for key, wanted in needs.items():
        if key == "gpus":
            continue                            # counted by naming them, below
        used = sum( float( o.get( key, 0 ) or 0 ) for o in others )
        total = have.get( key, 0.0 )
        if total and wanted > total:
            # Asking for more than exists would wait for ever. Let it through
            # alone rather than deadlock on an impossible promise.
            if others:
                return f"the machine to itself (needs {key}={wanted:g} of {total:g})", [ ]
            continue
        if total and used + wanted > total:
            return f"{key} ({used:g} of {total:g} taken, needs {wanted:g})", [ ]

    # Devices are ASSIGNED, not merely counted: an entry that asked for one GPU
    # has to be told which, or two of them pick the same card and the numbers
    # mean nothing.
    wanted_gpus = int( needs.get( "gpus", 0 ) )
    if exclusive:
        return None, devices()
    if not wanted_gpus:
        return None, [ ]
    free = [ d for d in devices() if d not in taken_devices( others ) ]
    if len( free ) < wanted_gpus:
        if not others:
            return None, free       # more than exists: run alone with what there is
        return f"gpus ({len( free )} free of {len( devices() )}, needs {wanted_gpus})", [ ]
    return None, free[ : wanted_gpus ]


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
            waiting, got = _fits( needs, exclusive, others )
            if waiting is None:
                yamlish.write( mine, { "label": label, "pid": os.getpid(), "host": host(),
                                       "exclusive": exclusive, "since": time.time(),
                                       "devices": got, **needs } )
                break
        if echo and waiting != waited_for:
            echo( f"  waiting for {waiting}" )
            waited_for = waiting
        time.sleep( POLL )

    stop = threading.Event()
    beat = threading.Thread( target = _heartbeat, args = ( mine, stop ), daemon = True )
    beat.start()
    try:
        yield Granted( path = mine, devices = got )
    finally:
        stop.set()
        beat.join( timeout = 1.0 )
        mine.unlink( missing_ok = True )


@dataclass
class Granted:
    """What the machine gave: where the claim is, and which devices are ours."""
    path   : Path
    devices: list

    def env( self ) -> dict:
        """What a child has to be told so it uses the cards it was given.

        Every framework reads one of these, and each renumbers from zero for
        whoever it is set on -- which is why a nested claim hands down its own
        0..n-1 rather than the indices it was itself given.
        """
        if not self.devices:
            return { }
        listed = ",".join( str( d ) for d in self.devices )
        return { "CUDA_VISIBLE_DEVICES": listed, "HIP_VISIBLE_DEVICES": listed,
                 "ROCR_VISIBLE_DEVICES": listed }


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
        if row.get( "devices" ):
            what += "  gpu " + ",".join( str( d ) for d in row[ "devices" ] )
        age = time.time() - float( row.get( "since", time.time() ) )
        out.append( f"{row.get( 'label', '?' )}  {what}  {age:.0f}s  pid {row.get( 'pid' )}" )
    return out
