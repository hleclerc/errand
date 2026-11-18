"""Sharing the machine.

A timing taken while something else was running is not a timing, so an entry
that says it needs the machine gets it -- not just against its own siblings,
but against every other `errand` on the host, in another terminal, on another
project. That means state outside the process, and the smallest honest form of
it is a directory of claims.

    <queue>/claims/<host>-<pid>-<n>.yaml    one file per held claim
    <queue>/waiting/<host>-<pid>-<n>.yaml   an exclusive request that is queued
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

The same rule applies to errand itself. An entry that runs another errand is
holding a claim while it waits for the child, so a child that queued would
wait for a claim its own parent will not release until the child is done --
a deadlock, and a quiet one. The claim is therefore INHERITED: `ERRAND_CLAIM`
says the machine has already been granted to this process tree.
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

# Set on everything an entry starts: the machine was already granted to this
# process tree, so nothing inside it queues again.
CLAIM = "ERRAND_CLAIM"

# The path of that claim, beside it: what `errand.require` grows ( ADR 0014 ).
CLAIM_FILE = "ERRAND_CLAIM_FILE"


# Set by errand in an allocation it holds ( ADR 0009 ): the allocation is the machine, carved by
# this queue -- what runs in it is not somebody else's scheduling.
ALLOCATION = "ERRAND_ALLOCATION"


def in_allocation( ) -> str | None:
    return os.environ.get( ALLOCATION ) or None


def someone_else_is_scheduling( ) -> str | None:
    """The name of the scheduler that already owns this process, if any: not in an allocation errand
    holds, which errand carves itself."""
    if in_allocation():
        return None
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
    # Two allocations of one user on one node are two machines: one queue each.
    alloc = f"-alloc{in_allocation()}" if in_allocation() else ""
    return Path( base ) / f"errand-queue-{uid}-{host()}{alloc}"


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
    # an allocation's memory, in one: what Slurm gave it on this node
    if in_allocation() and os.environ.get( "SLURM_MEM_PER_NODE", "" ).isdigit():
        return float( os.environ[ "SLURM_MEM_PER_NODE" ] )
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


def _visible( count: int, physical: list ) -> list:
    """What `CUDA_VISIBLE_DEVICES` leaves of a list in the machine's order, in the caller's order."""
    visible = os.environ.get( "CUDA_VISIBLE_DEVICES" )
    if visible is None:
        return physical
    ids = [ v.strip() for v in visible.split( "," ) if v.strip() ]
    if all( i.isdigit() for i in ids ):
        return [ physical[ int( i ) ] if int( i ) < len( physical ) else 0.0 for i in ids ]
    return physical[ : len( ids ) ]             # by UUID: in order, the best there is


def _card_ram( ) -> list:
    """The memory of each card this process may use, in MB, in its own numbering ( `devices` ).
    Empty when nothing says: `gpu_ram` then takes cards whole."""
    sizes = [ ]
    try:
        got = subprocess.run( [ "nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits" ],
                              capture_output = True, text = True, timeout = 10 )
        if not got.returncode:
            sizes = [ float( l.strip() ) for l in got.stdout.splitlines() if l.strip() ]   # MiB
    except ( OSError, subprocess.SubprocessError, ValueError ):
        pass
    if not sizes:
        try:
            import json
            got = subprocess.run( [ "rocm-smi", "--showmeminfo", "vram", "--json" ],
                                  capture_output = True, text = True, timeout = 10 )
            if not got.returncode:
                cards = json.loads( got.stdout )
                for name in sorted( ( k for k in cards if k.startswith( "card" ) ), key = lambda k: int( k[ 4 : ] or 0 ) ):
                    total = next( ( v for k, v in cards[ name ].items() if "Total" in k and "Used" not in k ), 0 )
                    sizes.append( float( total ) / ( 1024 * 1024 ) )
        except ( OSError, subprocess.SubprocessError, ValueError, AttributeError ):
            pass
    return _visible( len( sizes ), sizes ) if sizes else [ ]


def _cpu_count( ) -> int:
    """The cores this process may run on: an allocation's, in one ( its cpuset ), else the machine's."""
    if in_allocation() and hasattr( os, "sched_getaffinity" ):
        return len( os.sched_getaffinity( 0 ) ) or 1
    return os.cpu_count() or 1


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
        _capacity = { "cpus": float( _cpu_count() ),
                      "ram" : _total_ram_mb(),
                      "gpus": float( _gpu_count() ) }
        if _capacity[ "gpus" ]:
            _capacity[ "card_ram" ] = _card_ram()
    return dict( _capacity )


def card_size( d: int ) -> float:
    """The memory of card `d`, in MB, or 0 when nothing says."""
    sizes = capacity().get( "card_ram" ) or [ ]
    return float( sizes[ d ] ) if 0 <= d < len( sizes ) and sizes[ d ] else 0.0


def parse_share( value ):
    """`gpu_ram`: a size ( `40G` -> MB ) or a share of the card ( `75%`, kept as it is written )."""
    if value is None or value == "":
        return None
    if isinstance( value, str ) and value.strip().endswith( "%" ):
        pct = float( value.strip()[ : -1 ] )
        if not 0 < pct <= 100:
            raise ValueError( f"gpu_ram = {value!r}: a share between 0 and 100 %" )
        return f"{pct:g}%"
    return parse_size( value )


def share_on( spec, size: float ) -> float | None:
    """What `gpu_ram` takes on a card of `size` MB. None: the card whole ( no share, or no size known )."""
    if spec is None or not size:
        return None
    if isinstance( spec, str ):
        return size * float( spec[ : -1 ] ) / 100
    return float( spec )


def normalize( needs: dict ) -> dict:
    """An entry's `cpus=4, ram="8G"` as numbers in the machine's own units. `exclusive` is not a
    quantity, and is left to the caller."""
    out = { }
    for key, value in ( needs or { } ).items():
        if key == "exclusive" or value is None:
            continue
        out[ key ] = ( parse_size( value ) if key == "ram" else parse_share( value ) if key == "gpu_ram"
                       else float( value ) )
    if out.get( "gpu_ram" ) is not None and not out.get( "gpus" ):
        out[ "gpus" ] = 1.0                     # memory on a card is a card
    elif "gpu_ram" in out and out[ "gpu_ram" ] is None:
        del out[ "gpu_ram" ]
    # Several ranks: what is declared is what ONE needs ( a core at least ), and the machine is asked for all of them
    ranks = out.pop( "ranks", 0.0 )
    if ranks > 1:
        out[ "cpus" ] = ranks * max( out.get( "cpus", 1.0 ), 1.0 )
        for key in ( "gpus", "ram" ):
            if key in out:
                out[ key ] *= ranks
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


def _waiting_dir( ) -> Path:
    d = queue_dir() / "waiting"
    d.mkdir( parents = True, exist_ok = True )
    return d


def waiting_exclusive( ) -> list:
    """The requests that are queued and still breathing, that what arrives after waits behind:
    exclusive ones, and claims that grow ( `grows` )."""
    out, now = [ ], time.time()
    for path in sorted( _waiting_dir().glob( "*.yaml" ) ):
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age > STALE_AFTER:
            path.unlink( missing_ok = True )
            continue
        row = yamlish.read( path )
        if row:
            row[ "path" ] = str( path )
            out.append( row )
    return out


def _fits( needs: dict, exclusive: bool, others: list, ahead: list = ( ), keep = ( ) ):
    """( waiting_for, devices ). `waiting_for` is None when it fits.

    `ahead` are the requests already queued: exclusive ones, and claims that grow
    ( `grow` ). Whatever arrives after one waits behind it: otherwise a steady
    stream of small work would starve a benchmark for ever, which is the one
    thing a queue is for. `keep`: the cards a growing claim already has, given
    first when they still fit.
    """
    if ahead and not exclusive:
        first = ahead[ 0 ]
        why = "more than it holds" if first.get( "grows" ) else "the machine to itself"
        return f"{first.get( 'label', 'something' )}, which is waiting for {why}", [ ]
    if exclusive and others:
        return f"the machine to itself ({len( others )} running)", [ ]
    if any( o.get( "exclusive" ) for o in others ):
        owner = next( o for o in others if o.get( "exclusive" ) )
        return f"{owner.get( 'label', 'something' )}, which has the machine to itself", [ ]

    have = capacity()
    for key, wanted in needs.items():
        if key in ( "gpus", "gpu_ram" ):
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
    # A card's memory is counted per card ( ADR 0014 ): two runs that each take 30 % share one, two
    # that take 75 % do not. Without `gpu_ram`, or without the card's size, a card is taken whole.
    spec = needs.get( "gpu_ram" )
    free = [ ]
    for d in devices():
        left = _left_on( d, others )
        size = card_size( d )
        want = share_on( spec, size )
        if want is not None and want > size:
            want = None                         # more than the card has: the card, whole
        if left is None or ( want is None and left < size ) or ( want is not None and want > left ):
            continue
        free.append( ( d not in keep, -left, d ) )
    # The cards given are the ones with the most left: two runs that share no card do not slow
    # each other down.
    free = [ d for _, _, d in sorted( free ) ]
    if len( free ) < wanted_gpus:
        if not others:
            return None, free       # more than exists: run alone with what there is
        how = f", {spec} of each" if spec is not None else ""
        return f"gpus ({len( free )} free of {len( devices() )}, needs {wanted_gpus}{how})", [ ]
    return None, free[ : wanted_gpus ]


def _left_on( d: int, others: list ) -> float | None:
    """What is left of card `d`'s memory, in MB ( 0 when its size is unknown and nobody holds it ).
    None when somebody holds it whole."""
    left = card_size( d )
    for o in others:
        held = [ int( x ) for x in ( o.get( "devices" ) or [ ] ) ]
        if d not in held:
            continue
        shares = o.get( "card_ram" ) or [ ]
        i = held.index( d )
        if i >= len( shares ) or shares[ i ] is None or not left and not card_size( d ):
            return None
        left -= float( shares[ i ] )
    return max( left, 0.0 )


def _shares( needs: dict, got: list, exclusive: bool ) -> dict:
    """What a claim writes of its cards' memory: `card_ram`, one size per card, when it shares them."""
    spec = needs.get( "gpu_ram" )
    if exclusive or spec is None or not got:
        return { }
    shares = [ share_on( spec, card_size( d ) ) for d in got ]
    return { } if any( s is None for s in shares ) else { "card_ram": shares }


def _acquire( needs: dict, exclusive: bool, label: str, mine: Path, echo ) -> list:
    """Block until the claim fits, then write it. Returns the devices given."""
    queued = _waiting_dir() / mine.name
    waited_for = None
    try:
        while True:
            with _lock():
                others = [ o for o in held() if o[ "path" ] != str( mine ) ]
                ahead = [ w for w in waiting_exclusive() if w[ "path" ] != str( queued ) ]
                waiting, got = _fits( needs, exclusive, others, ahead )
                if waiting is not None:
                    # What is only kept warm gives way: ask it, and wait for it to go.
                    keen = [ o for o in others if not o.get( "preemptible" ) ]
                    gives = [ o for o in others if o.get( "preemptible" ) ]
                    if gives and _fits( needs, exclusive, keen, ahead )[ 0 ] is None:
                        for o in gives:
                            evict( o[ "path" ] )
                        waiting = ", ".join( o.get( "label", "something" ) for o in gives ) + \
                            ", kept warm, to make room"
                if waiting is None:
                    yamlish.write( mine, { "label": label, "pid": os.getpid(), "host": host(),
                                           "exclusive": exclusive, "since": time.time(),
                                           "devices": got, **needs, **_shares( needs, got, exclusive ) } )
                    return got
                if exclusive:
                    if queued.exists():
                        os.utime( queued, None )
                    else:
                        yamlish.write( queued, { "label": label, "pid": os.getpid(),
                                                 "host": host(), "since": time.time() } )
            if waiting != waited_for:
                if echo:
                    echo( f"  waiting for {waiting}" )
                from .agents import arrival
                arrival.waiting( f"room on {host()}: {waiting}", key = "queue" )      # ADR 0009
                waited_for = waiting
            time.sleep( POLL )
    finally:
        queued.unlink( missing_ok = True )
        if waited_for is not None:
            from .agents import arrival
            arrival.arrived( key = "queue" )


@contextlib.contextmanager
def claim( needs: dict, *, exclusive = False, label = "", enabled = True, echo = None ):
    """Hold a share of the machine for the duration of the block."""
    inherited = os.environ.get( CLAIM )
    if inherited is not None:
        # Already paid for by whoever started us. Queueing again would wait for
        # a claim that cannot be released until we are done with it.
        yield Granted( path = None, devices = _devices_of( inherited ) )
        return

    scheduler = someone_else_is_scheduling()
    if not enabled or os.environ.get( "ERRAND_NO_QUEUE" ) or scheduler:
        if scheduler and echo:
            echo( f"  ({scheduler} already decided what this process may have)" )
        yield Granted( path = None, devices = devices() if scheduler else [ ] )
        return

    needs = normalize( needs )
    mine = _claims_dir() / f"{host()}-{os.getpid()}-{time.time_ns()}.yaml"
    got = _acquire( needs, exclusive, label, mine, echo )

    stop = threading.Event()
    beat = threading.Thread( target = _heartbeat, args = ( mine, stop ), daemon = True )
    beat.start()
    try:
        yield Granted( path = mine, devices = got )
    finally:
        stop.set()
        beat.join( timeout = 1.0 )
        release( mine )


# ── a claim that grows ( ADR 0014 ) ─────────────────────────────────────────
#
# A run asks for more once it knows: `errand.require`, from its own code. Its
# claim stays held by the errand process that started it; `grow` only rewrites
# what it holds, under the lock, once it fits. A growing claim is ahead of any
# new one. Two that grow at once can each hold what the other waits for: the
# younger is stopped ( `Rerun` ), and errand runs it again with its needs up front.

QUANTITIES = ( "cpus", "ram", "gpus", "gpu_ram" )


def _pct( v ) -> float:
    return float( v[ : -1 ] )


def merged( row: dict, needs: dict ) -> dict:
    """What a claim holds once `needs` is added to it: the larger of each. Cards held whole already
    hold any share of them; a share and a size, which cannot be compared, take the newer."""
    out = { }
    for k in ( "cpus", "ram", "gpus" ):
        v = max( float( row.get( k ) or 0 ), float( needs.get( k ) or 0 ) )
        if v:
            out[ k ] = v
    a, b = row.get( "gpu_ram" ), needs.get( "gpu_ram" )
    whole = bool( row.get( "gpus" ) ) and a is None
    if not whole and ( a is not None or b is not None ):
        if a is not None and b is not None and isinstance( a, str ) == isinstance( b, str ):
            out[ "gpu_ram" ] = max( a, b, key = _pct if isinstance( a, str ) else float )
        else:
            out[ "gpu_ram" ] = b if b is not None else a
    return out


def grow( path, needs: dict, *, exclusive = False, label = None, echo = None ) -> list:
    """Grow the claim at `path` to hold `needs` too, and wait until it does. -> the cards it holds.

    What was asked is kept in the claim ( `required` ), for errand to remember once the run is over,
    even when the claim already held it."""
    from .entries import Rerun
    mine = Path( path )
    asked = normalize( needs )
    request = _waiting_dir() / f"{mine.stem}.grow.yaml"
    waited_for = None
    try:
        while True:
            with _lock():
                row = yamlish.read( mine ) if mine.exists() else None
                if not row:
                    raise RuntimeError( f"the claim {mine.name} is gone ( reclaimed? ): there is nothing to grow" )
                note = { "required": merged( row.get( "required" ) or { }, asked ) }
                if exclusive or row.get( "required_exclusive" ):
                    note[ "required_exclusive" ] = True
                want = merged( row, asked )
                excl = bool( exclusive or row.get( "exclusive" ) )
                if want == merged( row, { } ) and excl == bool( row.get( "exclusive" ) ):
                    yamlish.write( mine, { **row, **note } )
                    return [ int( d ) for d in row.get( "devices" ) or [ ] ]
                others = [ o for o in held() if o[ "path" ] != str( mine ) ]
                keep = [ int( d ) for d in row.get( "devices" ) or [ ] ]
                waiting, got = _fits( want, excl, others, keep = keep )
                if waiting is None:
                    rest = { k: v for k, v in row.items() if k not in ( *QUANTITIES, "card_ram" ) }
                    yamlish.write( mine, { **rest, **want, "exclusive": excl, "devices": got,
                                           **_shares( want, got, excl ), **note } )
                    return got
                if _younger_in_a_cycle( row, mine, want, excl, others ):
                    yamlish.write( mine, { **row, **note, "rerun": True } )
                    raise Rerun( f"it waits for {waiting}, held by a run that waits for what this one holds: "
                                 f"errand runs it again, with what it requires up front" )
                if request.exists():
                    os.utime( request, None )
                else:
                    yamlish.write( request, { "label": label or row.get( "label", "" ), "pid": os.getpid(),
                                              "host": host(), "since": row.get( "since", time.time() ),
                                              "grows": True, "claim": mine.name, "exclusive": excl,
                                              "want": want } )
            if waiting != waited_for:
                if echo:
                    echo( f"  waiting for {waiting}" )
                from .agents import arrival
                arrival.waiting( f"room on {host()}: {waiting}", key = "queue" )      # ADR 0009
                waited_for = waiting
            time.sleep( POLL )
    finally:
        request.unlink( missing_ok = True )
        if waited_for is not None:
            from .agents import arrival
            arrival.arrived( key = "queue" )


def _younger_in_a_cycle( row, mine: Path, want: dict, excl: bool, others: list ) -> bool:
    """Is another growing claim waiting for what this one holds, while this one waits for what it
    holds -- and is this one the younger of the two? Then it is the one to stop."""
    for g in waiting_exclusive():
        if not g.get( "grows" ) or g.get( "claim" ) == mine.name:
            continue
        theirs = next( ( o for o in others if Path( o[ "path" ] ).name == g.get( "claim" ) ), None )
        if theirs is None or float( row.get( "since", 0 ) ) < float( theirs.get( "since", 0 ) ):
            continue                            # gone, or older than this one: it is the other that stops
        without = [ o for o in others if o is not theirs ]
        mine_row = { **row, "path": str( mine ) }
        if ( _fits( want, excl, without )[ 0 ] is None
             and _fits( g.get( "want" ) or { }, bool( g.get( "exclusive" ) ), without + [ mine_row ] )[ 0 ] is not None
             and _fits( g.get( "want" ) or { }, bool( g.get( "exclusive" ) ), without )[ 0 ] is None ):
            return True
    return False


def _devices_of( spelt: str ) -> list:
    return [ int( d ) for d in spelt.split( "," ) if d.strip().isdigit() ]


@dataclass
class Granted:
    """What the machine gave: where the claim is, and which devices are ours."""
    path   : Path | None
    devices: list

    def preemptible( self, flag = True ):
        """Kept warm and nothing more: anybody who needs the room may ask for it ( `evicted` )."""
        if self.path is not None:
            mark( self.path, flag )

    def evicted( self ) -> bool:
        """Somebody needs what this holds, and it said it could give it up."""
        return self.path is not None and evicted( self.path )

    def handed_down( self ) -> dict:
        """What everything this entry starts must be told: the cards, and where the claim is, for
        `errand.require` to grow it ( ADR 0014 )."""
        out = { CLAIM: ",".join( str( d ) for d in self.devices ) }
        if self.path is not None:
            out[ CLAIM_FILE ] = str( self.path )
        return out

    def row( self ) -> dict:
        """The claim as it is now: what `require` made of it."""
        return ( yamlish.read( Path( self.path ) ) or { } ) if self.path is not None else { }

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


# ── kept warm, and giving way ────────────────────────────────────────────────
#
# A claim marked `preemptible` holds what is only kept warm -- a virtual
# machine nobody uses at the moment, a process that has imported torch ahead.
# A request that does not fit, but would without such claims, leaves an
# eviction request beside each of them and waits; their holders give the room
# back as soon as they are idle, rather than at the end of their keep_alive.

def _evict_dir( ) -> Path:
    d = queue_dir() / "evict"
    d.mkdir( parents = True, exist_ok = True )
    return d


def evict( claim_path ):
    ( _evict_dir() / Path( claim_path ).name ).touch()


def evicted( claim_path ) -> bool:
    return ( _evict_dir() / Path( claim_path ).name ).exists()


def mark( claim_path, preemptible: bool ):
    """Say, in the claim itself, whether it may be asked to give way."""
    with _lock():
        row = yamlish.read( Path( claim_path ) )
        if row is not None and bool( row.get( "preemptible" ) ) != preemptible:
            yamlish.write( Path( claim_path ), { **row, "preemptible": preemptible } )
        if not preemptible:
            ( _evict_dir() / Path( claim_path ).name ).unlink( missing_ok = True )


def release( claim_path ):
    Path( claim_path ).unlink( missing_ok = True )
    ( _evict_dir() / Path( claim_path ).name ).unlink( missing_ok = True )


def try_claim( needs: dict, *, label = "", preemptible = True ) -> Path | None:
    """A claim taken only if it fits now, for whatever holds without a thread to keep it alive
    ( a zygote, which must not have one ): the caller touches it ( `touch` ), and releases it."""
    if os.environ.get( CLAIM ) is not None or os.environ.get( "ERRAND_NO_QUEUE" ) or someone_else_is_scheduling():
        return None
    needs = normalize( needs )
    mine = _claims_dir() / f"{host()}-{os.getpid()}-{time.time_ns()}.yaml"
    with _lock():
        others = held()
        waiting, got = _fits( needs, False, others, waiting_exclusive() )
        if waiting is not None:
            return None
        yamlish.write( mine, { "label": label, "pid": os.getpid(), "host": host(), "exclusive": False,
                               "since": time.time(), "devices": got, "preemptible": preemptible, **needs,
                               **_shares( needs, got, False ) } )
    return mine


def resize( claim_path, **needs ):
    """What a claim holds, said again: a zygote's memory grows with what it imports."""
    with _lock():
        row = yamlish.read( Path( claim_path ) )
        if row is not None:
            yamlish.write( Path( claim_path ), { **row, **normalize( needs ) } )


def touch( claim_path ) -> bool:
    """Still breathing. -> False when the claim was reclaimed meanwhile."""
    try:
        os.utime( claim_path, None )
        return True
    except OSError:
        return False


def _heartbeat( path: Path, stop: threading.Event ):
    while not stop.wait( HEARTBEAT ):
        try:
            os.utime( path, None )
        except OSError:
            return      # reclaimed while we were away; nothing to keep alive


def wait_idle( ) -> int:
    """Return once nothing holds the machine and nothing is queued for it."""
    while held() or waiting_exclusive():
        time.sleep( 1.0 )
    return 0


def describe( ) -> list:
    """One line per live claim, for a banner or a monitor."""
    out = [ ]
    for row in waiting_exclusive():
        why = "waits to grow its claim" if row.get( "grows" ) else "waits for the whole machine"
        out.append( f"{row.get( 'label', '?' )}  {why}  pid {row.get( 'pid' )}" )
    for row in held():
        what = "the whole machine" if row.get( "exclusive" ) else ", ".join(
            f"{k}={row[ k ]:g}" for k in ( "cpus", "ram", "gpus" ) if row.get( k ) ) or "a slot"
        if row.get( "gpu_ram" ) is not None and not row.get( "exclusive" ):
            spec = row[ "gpu_ram" ]
            what += f", gpu_ram={spec if isinstance( spec, str ) else f'{spec:g}'}"
        if row.get( "devices" ):
            what += "  gpu " + ",".join( str( d ) for d in row[ "devices" ] )
        age = time.time() - float( row.get( "since", time.time() ) )
        warm = "  ( kept warm: gives way )" if row.get( "preemptible" ) else ""
        out.append( f"{row.get( 'label', '?' )}  {what}  {age:.0f}s  pid {row.get( 'pid' )}{warm}" )
    return out


# ── a claim on this machine, for a process elsewhere ─────────────────────────

def hold( spec: dict ) -> int:
    """`python -m errand.queue hold '<json>'`: a claim on THIS machine, for whoever holds the
    stream to this process -- a keeper on another machine, for the machine it boots here.

    Says `granted <devices>` once it has it, `evict` when somebody needs the room; reads `warm`
    ( it may give way ) and `busy` ( it may not ); goes, and releases, when its input closes."""
    import json
    import select
    import sys
    spec = json.loads( spec ) if isinstance( spec, str ) else spec
    with claim( spec.get( "needs" ) or { }, exclusive = bool( spec.get( "exclusive" ) ), label = spec.get( "label", "" ),
                echo = lambda m: print( m, file = sys.stderr, flush = True ) ) as granted:
        print( "granted " + ",".join( str( d ) for d in granted.devices ), flush = True )
        said = False
        while True:
            ready, _, _ = select.select( [ sys.stdin ], [ ], [ ], 1.0 )
            if ready:
                line = sys.stdin.readline()
                if not line:
                    return 0
                if line.strip() in ( "warm", "busy" ):
                    granted.preemptible( line.strip() == "warm" )
                    said = False
            if not said and granted.evicted():
                print( "evict", flush = True )
                said = True


if __name__ == "__main__":
    import sys
    if len( sys.argv ) == 3 and sys.argv[ 1 ] == "hold":
        sys.exit( hold( sys.argv[ 2 ] ) )
    print( "usage: python -m errand.queue hold SPEC", file = sys.stderr )
    sys.exit( 2 )
