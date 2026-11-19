"""What a machine's resources are doing, for `table` ( `errand tui`, `errand status` ): the cores busy,
the memory used, each card's load and memory, and what errand holds there ( its claims, `queue` ).

    { "cpus": 128, "busy": 0.68, "load": 87.1,
      "ram": { "total": 524288, "used": 215040 },                       # MB
      "gpus": [ { "index": 0, "name": "A100", "util": 87, "used": 30720, "total": 81920 } ],
      "held": { "cpus": 16, "ram": 65536, "gpus": 1, "exclusive": False, "claims": 2 },
      "scheduler": None }

Cheap enough to be asked at every table: `/proc` on Linux ( microseconds ), `vm_stat` on macOS, and
`nvidia-smi` at most every `GPU_EVERY` seconds. The share of the cores busy is the change between two
readings of `/proc/stat`: the agent keeps the last one; a process that asks once reads twice, apart.
Standard library only: the agent imports it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

GPU_EVERY = 5.0
_stat = None                        # ( time, busy, total ) of the last reading of /proc/stat
_gpus = ( 0.0, [ ] )                # ( when, cards )


def _cpu_times( ):
    try:
        with open( "/proc/stat" ) as f:
            parts = [ int( x ) for x in f.readline().split()[ 1 : ] ]
    except ( OSError, ValueError ):
        return None
    idle = parts[ 3 ] + ( parts[ 4 ] if len( parts ) > 4 else 0 )
    return sum( parts ), sum( parts ) - idle


def busy( ) -> float | None:
    """The share of the cores busy since the last reading ( Linux ); None where it cannot be read."""
    global _stat
    now = _cpu_times()
    if now is None:
        return None
    if _stat is None:
        time.sleep( 0.1 )                  # asked once: two readings, apart
        before, now = now, _cpu_times()
    else:
        before = _stat
    _stat = now
    total, used = now[ 0 ] - before[ 0 ], now[ 1 ] - before[ 1 ]
    return max( 0.0, min( 1.0, used / total ) ) if total > 0 else None


def ram( ) -> dict | None:
    """{ total, used } in MB."""
    try:
        with open( "/proc/meminfo" ) as f:
            info = { l.split( ":" )[ 0 ]: int( l.split()[ 1 ] ) for l in f if ":" in l }
        total, free = info[ "MemTotal" ], info.get( "MemAvailable", info.get( "MemFree", 0 ) )
        return { "total": total // 1024, "used": ( total - free ) // 1024 }
    except ( OSError, KeyError, ValueError, IndexError ):
        pass
    try:                                    # macOS
        total = os.sysconf( "SC_PAGE_SIZE" ) * os.sysconf( "SC_PHYS_PAGES" )
        got = subprocess.run( [ "vm_stat" ], capture_output = True, text = True, timeout = 3 )
        page = int( got.stdout.split( "page size of" )[ 1 ].split()[ 0 ] )
        pages = { l.split( ":" )[ 0 ].strip(): int( l.split( ":" )[ 1 ].strip().rstrip( "." ) )
                  for l in got.stdout.splitlines()[ 1 : ] if ":" in l and l.split( ":" )[ 1 ].strip().rstrip( "." ).isdigit() }
        free = sum( pages.get( k, 0 ) for k in ( "Pages free", "Pages inactive", "Pages speculative" ) ) * page
        return { "total": total // 2 ** 20, "used": max( 0, total - free ) // 2 ** 20 }
    except ( OSError, ValueError, IndexError, AttributeError, subprocess.SubprocessError ):
        return None


def gpus( ) -> list:
    """Each card: { index, name, util ( % ), used, total ( MB ) }, read at most every `GPU_EVERY` seconds."""
    global _gpus
    if time.time() - _gpus[ 0 ] < GPU_EVERY:
        return _gpus[ 1 ]
    cards = [ ]
    if shutil.which( "nvidia-smi" ):
        try:
            got = subprocess.run( [ "nvidia-smi", "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
                                    "--format=csv,noheader,nounits" ], capture_output = True, text = True, timeout = 5 )
            for line in got.stdout.splitlines() if not got.returncode else [ ]:
                i, name, util, used, total = [ x.strip() for x in line.split( "," ) ]
                cards.append( { "index": int( i ), "name": name, "util": float( util ) if util.replace( ".", "" ).isdigit() else None,
                                "used": float( used ), "total": float( total ) } )
        except ( OSError, ValueError, subprocess.SubprocessError ):
            cards = [ ]
    _gpus = ( time.time(), cards )
    return cards


def held( ) -> dict:
    """What errand's claims hold on this machine ( `queue` ), in all."""
    out = { "cpus": 0.0, "ram": 0.0, "gpus": 0, "exclusive": False, "claims": 0 }
    try:
        from .. import queue
        rows = queue.held()
    except Exception:
        return out
    for row in rows:
        out[ "claims" ] += 1
        out[ "exclusive" ] = out[ "exclusive" ] or bool( row.get( "exclusive" ) )
        out[ "cpus" ] += float( row.get( "cpus" ) or 0 )
        out[ "ram" ] += float( row.get( "ram" ) or 0 )
        out[ "gpus" ] += len( row.get( "devices" ) or [ ] ) or int( float( row.get( "gpus" ) or 0 ) )
    return out


def measure( ) -> dict:
    """This machine now."""
    out = { "cpus": os.cpu_count() or 1, "busy": busy(), "load": None, "ram": ram(), "gpus": gpus(),
            "held": held(), "scheduler": None }
    try:
        out[ "load" ] = os.getloadavg()[ 0 ]
    except ( OSError, AttributeError ):
        pass
    if out[ "busy" ] is None and out[ "load" ] is not None:
        out[ "busy" ] = min( 1.0, out[ "load" ] / out[ "cpus" ] )         # where /proc/stat is not: the load
    try:
        from .. import queue
        out[ "scheduler" ] = queue.someone_else_is_scheduling()
    except Exception:
        pass
    return out
