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


def _alive( pid ) -> bool:
    try:
        os.kill( int( pid ), 0 )
    except ( OSError, ValueError, TypeError ):
        return False
    return True


def waiting( ) -> list:
    """The requests that are queued and still breathing, oldest first ( ADR 0018: FIFO for all ):
    what arrives after one waits behind it. Claims that grow ( `grows` ) among them. A request of
    this host whose process is gone is dropped at once, not after `STALE_AFTER`."""
    out, now = [ ], time.time()
    for path in _waiting_dir().glob( "*.yaml" ):
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age > STALE_AFTER:
            path.unlink( missing_ok = True )
            continue
        row = yamlish.read( path )
        if not row:
            continue
        if row.get( "host" ) == host() and row.get( "pid" ) is not None and not _alive( row[ "pid" ] ):
            path.unlink( missing_ok = True )
            continue
        row[ "path" ] = str( path )
        out.append( row )
    out.sort( key = lambda r: ( not r.get( "grows" ), float( r.get( "since", 0 ) ), r[ "path" ] ) )
    return out


waiting_exclusive = waiting       # its name before ADR 0018, when only exclusive requests and growing claims waited


def _fits( needs: dict, exclusive: bool, others: list, ahead: list = ( ), keep = ( ) ):
    """( waiting_for, devices ). `waiting_for` is None when it fits.

    `ahead` are the requests queued before this one, and claims that grow
    ( `grow` ). Whatever arrives after one waits behind it ( FIFO, ADR 0018 ):
    otherwise a steady stream of small work would starve a benchmark, or a
    service waiting for a card, for ever, which is the one thing a queue is for. `keep`: the cards a growing claim already has, given
    first when they still fit.
    """
    if ahead:
        first = ahead[ 0 ]
        why = "more than it holds" if first.get( "grows" ) else "the machine to itself" if first.get( "exclusive" ) \
            else "its turn"
        more = f" ( {len( ahead )} ahead )" if len( ahead ) > 1 else ""
        return f"{first.get( 'label', 'something' )}, which is waiting for {why}{more}", [ ]
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
    if not wanted_gpus or not devices():
        return None, [ ]        # no card asked, or none here to share: nothing to wait for
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


class GaveUp( RuntimeError ):
    """A wait for a claim abandoned by its `give_up` ( a service nobody waits for any more, ADR 0018 )."""


def _acquire( needs: dict, exclusive: bool, label: str, mine: Path, echo, base = None, give_up = None ) -> list:
    """Block until the claim fits, then write it. Returns the devices given. `give_up()`, asked at each
    poll while it waits: True abandons the wait ( `GaveUp` )."""
    queued = _waiting_dir() / mine.name
    waited_for, since = None, time.time()
    try:
        while True:
            with _lock():
                others = [ o for o in held() if o[ "path" ] != str( mine ) ]
                ahead = [ w for w in waiting() if w[ "path" ] != str( queued )
                          and ( w.get( "grows" ) or ( float( w.get( "since", 0 ) ), w[ "path" ] ) < ( since, str( queued ) ) ) ]
                blocked, got = _fits( needs, exclusive, others, ahead )
                if blocked is not None:
                    # What is only kept warm gives way: ask it, and wait for it to go.
                    keen = [ o for o in others if not o.get( "preemptible" ) ]
                    gives = [ o for o in others if o.get( "preemptible" ) ]
                    if gives and _fits( needs, exclusive, keen, ahead )[ 0 ] is None:
                        for o in gives:
                            evict( o[ "path" ] )
                        blocked = ", ".join( o.get( "label", "something" ) for o in gives ) + \
                            ", kept warm, to make room"
                if blocked is None:
                    yamlish.write( mine, { "label": label, "pid": os.getpid(), "host": host(),
                                           "exclusive": exclusive, "since": time.time(),
                                           "devices": got, **needs, **_shares( needs, got, exclusive ),
                                           **( { "base": base } if base is not None else { } ) } )
                    return got
                # Every waiter is recorded, the oldest first ( ADR 0018 ): a later request that fits does not pass it.
                if queued.exists():
                    os.utime( queued, None )
                else:
                    yamlish.write( queued, { "label": label, "pid": os.getpid(), "host": host(), "since": since,
                                             "exclusive": exclusive, "needs": needs } )
            if blocked != waited_for:
                if echo:
                    echo( f"  waiting for {blocked}" )
                from .agents import arrival
                arrival.waiting( f"room on {host()}: {blocked}", key = "queue" )      # ADR 0009
                waited_for = blocked
            if give_up is not None and give_up():
                raise GaveUp( f"stopped waiting for {blocked}" )
            time.sleep( POLL )
    finally:
        queued.unlink( missing_ok = True )
        if waited_for is not None:
            from .agents import arrival
            arrival.arrived( key = "queue" )


@contextlib.contextmanager
def claim( needs: dict, *, exclusive = False, label = "", enabled = True, echo = None, base = None, give_up = None ):
    """Hold a share of the machine for the duration of the block. `base`: what the run is started
    with, by what it is told ( the environment, the command line ), when `needs` is more ( claimed up
    front ): what `require( extra = True )` adds to. `needs` by default."""
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
    got = _acquire( needs, exclusive, label, mine, echo, base = None if base is None else normalize( base ),
                    give_up = give_up )

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


def _in_mb( spec, size: float ) -> float | None:
    """A share or a size, in MB on a card of `size` MB. None: a share, and no size to read it with."""
    if isinstance( spec, str ):
        return size * _pct( spec ) / 100 if size else None
    return float( spec )


def merged( row: dict, needs: dict, size: float = 0.0 ) -> dict:
    """What a claim holds once it holds `needs` too: the larger of each. Cards held whole already hold
    any share of them. A share and a size are compared on a card of `size` MB; with no size to read
    the share, what is held is kept: a claim never shrinks."""
    out = { }
    for k in ( "cpus", "ram", "gpus" ):
        v = max( float( row.get( k ) or 0 ), float( needs.get( k ) or 0 ) )
        if v:
            out[ k ] = v
    a, b = row.get( "gpu_ram" ), needs.get( "gpu_ram" )
    whole = bool( row.get( "gpus" ) ) and a is None
    if not whole and ( a is not None or b is not None ):
        if a is None or b is None:
            out[ "gpu_ram" ] = b if a is None else a
        elif isinstance( a, str ) == isinstance( b, str ):
            out[ "gpu_ram" ] = max( a, b, key = _pct if isinstance( a, str ) else float )
        else:
            ma, mb = _in_mb( a, size ), _in_mb( b, size )
            out[ "gpu_ram" ] = b if ma is not None and mb is not None and mb > ma else a
    return out


def added( row: dict, needs: dict, size: float = 0.0 ) -> dict:
    """What a claim holds once `needs` is added to it ( `require( extra = True )` ): the sum of each.
    `gpu_ram` is added on each card: two shares add up, two sizes too, a share and a size on a card
    of `size` MB ( with none known, the cards are taken whole ). Cards held whole stay whole."""
    out = { }
    for k in ( "cpus", "ram", "gpus" ):
        v = float( row.get( k ) or 0 ) + float( needs.get( k ) or 0 )
        if v:
            out[ k ] = v
    a, b = row.get( "gpu_ram" ), needs.get( "gpu_ram" )
    whole = bool( row.get( "gpus" ) ) and a is None
    if not whole and ( a is not None or b is not None ):
        if a is None or b is None:
            out[ "gpu_ram" ] = b if a is None else a
        elif isinstance( a, str ) and isinstance( b, str ):
            out[ "gpu_ram" ] = f"{min( _pct( a ) + _pct( b ), 100.0 ):g}%"
        else:
            ma, mb = _in_mb( a, size ), _in_mb( b, size )
            if ma is not None and mb is not None:
                out[ "gpu_ram" ] = ma + mb
    return out


def _reference_size( row: dict ) -> float:
    """The card a share and a size are compared on: the smallest the claim holds, else the smallest
    of the machine, else 0 ( unknown )."""
    held = [ card_size( int( d ) ) for d in row.get( "devices" ) or [ ] ]
    sizes = [ s for s in ( held or [ card_size( d ) for d in range( len( capacity().get( "card_ram" ) or [ ] ) ) ] ) if s ]
    return min( sizes ) if sizes else 0.0


def grow( path, needs: dict, *, exclusive = False, extra = False, label = None, echo = None ) -> list:
    """Grow the claim at `path` to hold `needs` too, and wait until it does. -> the cards it holds.

    `needs` is what the run needs in all ( at least that much ), or, with `extra`, what it needs on
    top of what it was started with ( `base`, written when the claim was taken ): several `extra`
    calls add up. What the code asked is kept in the claim -- `required`, `required_extra`, and the
    total it comes to, `wanted` -- for the run's record, and for errand to remember."""
    from .entries import Rerun
    mine = Path( path )
    asked = normalize( needs )
    if extra and "gpus" not in needs:
        asked.pop( "gpus", None )               # more memory on the cards held, not one more card
    request = _waiting_dir() / f"{mine.stem}.grow.yaml"
    waited_for = None
    try:
        while True:
            with _lock():
                row = yamlish.read( mine ) if mine.exists() else None
                if not row:
                    raise RuntimeError( f"the claim {mine.name} is gone ( reclaimed? ): there is nothing to grow" )
                size = _reference_size( row )
                base = row.get( "base" )
                if base is None:
                    base = { k: row[ k ] for k in QUANTITIES if row.get( k ) is not None }
                note = { "base": base }
                required = row.get( "required" ) or { }
                plus = row.get( "required_extra" ) or { }
                if extra:
                    plus = added( plus, asked, size )
                else:
                    required = merged( required, asked, size )
                if required:
                    note[ "required" ] = required
                if plus:
                    note[ "required_extra" ] = plus
                if exclusive or row.get( "required_exclusive" ):
                    note[ "required_exclusive" ] = True
                # what the code comes to: what it started with and what was added, and at least what was asked
                note[ "wanted" ] = merged( added( base, plus, size ), required, size )
                want = merged( row, note[ "wanted" ], size )
                excl = bool( exclusive or row.get( "exclusive" ) )
                if want == merged( row, { } ) and excl == bool( row.get( "exclusive" ) ):
                    yamlish.write( mine, { **row, **note } )
                    return [ int( d ) for d in row.get( "devices" ) or [ ] ]
                others = [ o for o in held() if o[ "path" ] != str( mine ) ]
                keep = [ int( d ) for d in row.get( "devices" ) or [ ] ]
                blocked, got = _fits( want, excl, others, keep = keep )
                if blocked is None:
                    rest = { k: v for k, v in row.items() if k not in ( *QUANTITIES, "card_ram" ) }
                    yamlish.write( mine, { **rest, **want, "exclusive": excl, "devices": got,
                                           **_shares( want, got, excl ), **note } )
                    return got
                if _younger_in_a_cycle( row, mine, want, excl, others ):
                    yamlish.write( mine, { **row, **note, "rerun": True } )
                    raise Rerun( f"it waits for {blocked}, held by a run that waits for what this one holds: "
                                 f"errand runs it again, with what it requires up front" )
                if request.exists():
                    os.utime( request, None )
                else:
                    yamlish.write( request, { "label": label or row.get( "label", "" ), "pid": os.getpid(),
                                              "host": host(), "since": row.get( "since", time.time() ),
                                              "grows": True, "claim": mine.name, "exclusive": excl,
                                              "want": want } )
            if blocked != waited_for:
                if echo:
                    echo( f"  waiting for {blocked}" )
                from .agents import arrival
                arrival.waiting( f"room on {host()}: {blocked}", key = "queue" )      # ADR 0009
                waited_for = blocked
            time.sleep( POLL )
    finally:
        request.unlink( missing_ok = True )
        if waited_for is not None:
            from .agents import arrival
            arrival.arrived( key = "queue" )


def _younger_in_a_cycle( row, mine: Path, want: dict, excl: bool, others: list ) -> bool:
    """Is this growing claim, waiting, among what holds back an older one that waits too? Then it is
    the one to stop ( and run again ): an older claim that grows is blocked only by younger ones that
    grow -- this one among them -- when it would fit without them, and does not with them. Two that
    wait for each other are the simplest such case; three or more growing to the whole machine
    ( benchmarks under `-j` ) are another, which no pair shows."""
    growing = { g.get( "claim" ): g for g in waiting() if g.get( "grows" ) }
    since = lambda o: float( o.get( "since", 0 ) )
    mine_row = { **row, "path": str( mine ) }
    everyone = others + [ mine_row ]
    for name, g in growing.items():
        if name == mine.name:
            continue
        theirs = next( ( o for o in others if Path( o[ "path" ] ).name == name ), None )
        if theirs is None or since( theirs ) > since( row ):
            continue                            # gone, or younger than this one: not for this one to make way
        younger = [ o for o in everyone if Path( o[ "path" ] ).name in growing and since( o ) > since( theirs ) ]
        rest = [ o for o in everyone if o is not theirs and o not in younger ]
        g_want, g_excl = g.get( "want" ) or { }, bool( g.get( "exclusive" ) )
        if _fits( g_want, g_excl, rest )[ 0 ] is None and \
           _fits( g_want, g_excl, [ o for o in everyone if o is not theirs ] )[ 0 ] is not None:
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
        if _fits( needs, False, others, waiting() )[ 0 ] is not None:
            return None
        _, got = _fits( needs, False, others )
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
    while held() or waiting():
        time.sleep( 1.0 )
    return 0


def describe( ) -> list:
    """One line per live claim, for a banner or a monitor."""
    out = [ ]
    for row in waiting():
        why = "waits to grow its claim" if row.get( "grows" ) else "waits for the whole machine" \
            if row.get( "exclusive" ) else "waits for its turn"
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
