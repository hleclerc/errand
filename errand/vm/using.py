"""A command's hold on a machine, on the machine that runs QEMU ( ADR 0008 ).

    python -m errand.vm use '<request>'

Started by that machine's agent for a command, and gone with the command: a process that may not
outlive its client ( `keep` false ), so a command killed, or whose connection is lost, lets go of
the machine at once, by the kernel's hand ( its lock ), whatever happened here.

It decides, under `start.lock`, whether a keeper must be started, and starts it through the same
agent, as a process that outlives its client: the agent owns it, lists it, stops it, and kills it
if the agent itself is killed and comes back ( `procs.kill_orphans` ). Then it takes `use.lock` --
commands on one machine take turns -- and says, a line at a time, what the machine is doing, until
it is ready ( its port ) or failed. It holds `use.lock` until its input closes.

Every line it says is `errand-vm <json>`: { "state" }, { "ready": port }, { "failed": why }.
"""
from __future__ import annotations

import json
import os
import select
import sys
import time
from pathlib import Path

from .common import _alive, _lock, _read, BOOT_TIMEOUT


def say( **what ):
    print( "errand-vm " + json.dumps( what ), flush = True )


def keeper_up( live: Path ) -> bool:
    return _alive( _read( live / "keeper.pid" ) ) and _read( live / "state", "stopped" ) not in ( "stopping", "stopped",
                                                                                                    "failed", "orphaned" )


def start_keeper( live: Path, launcher: list ):
    """Through the agent this process runs under, as one of its processes that outlives its client.
    No agent ( started by hand ): a session of its own, as before -- still on this machine."""
    argv = [ *launcher, "-m", "errand.vm", "keep", str( live ) ]
    ( live / "keeper.pid" ).unlink( missing_ok = True )
    agent = os.environ.get( "ERRAND_AGENT_DIR" )
    if agent:
        from ..agents import upstream as U
        conn = U.direct( { "kind": "local", "dir": agent, "keep_alive": 900 } )   # never through a hub, here
        call = conn.open( { "op": "spawn", "argv": argv, "cwd": os.getcwd(), "keep": True,
                            "env": { "PYTHONPATH": os.environ.get( "PYTHONPATH", "" ) } } )
        call.reply( 30 )
        call.close()            # it is the agent's now: its output goes to the agent's directory
    else:
        import subprocess
        with open( live / "keeper.log", "a" ) as log:
            subprocess.Popen( argv, stdin = subprocess.DEVNULL, stdout = log, stderr = subprocess.STDOUT,
                              start_new_session = True )
    deadline = time.monotonic() + 60
    while not _read( live / "keeper.pid" ) and time.monotonic() < deadline:
        time.sleep( 0.1 )


def use( request: dict ) -> int:
    from .machine import sweep
    from .places import live_dir
    live = live_dir() / request[ "name" ]
    live.mkdir( parents = True, exist_ok = True )
    sweep( keep = live )
    start = _lock( live / "start.lock" )
    try:
        if not keeper_up( live ):
            ( live / "config.json" ).write_text( json.dumps( request[ "config" ] ) )
            ( live / "state" ).write_text( "starting" )
            start_keeper( live, request[ "launcher" ] )
        use_lock = _lock( live / "use.lock", block = False )
        if use_lock is None:
            say( state = "waiting" )             # another command uses it: they take turns
            use_lock = _lock( live / "use.lock" )
    finally:
        start.close()
    ( live / "used" ).touch()
    try:
        if not _wait_ready( live ):
            return 1
        _hold_until_eof()
    finally:
        ( live / "used" ).touch()
        use_lock.close()
    return 0


def _wait_ready( live: Path ) -> bool:
    said, since = None, time.monotonic()
    while True:
        state = _read( live / "state", "stopped" )
        if state == "ready":
            say( ready = int( _read( live / "port", "0" ) ) )
            return True
        if not _alive( _read( live / "keeper.pid" ) ) or state in ( "stopped", "failed", "orphaned" ):
            say( failed = _tail( live ) )
            return False
        if state != said:
            say( state = state )
            said, since = state, time.monotonic()
        if state == "booting" and time.monotonic() - since > BOOT_TIMEOUT:
            say( failed = f"windows did not answer within {BOOT_TIMEOUT // 60} minutes" )
            return False
        time.sleep( 0.5 )


def _tail( live: Path ) -> str:
    return _read( live / "keeper.log" )[ -800 : ] or "( the keeper said nothing )"


def _hold_until_eof():
    while True:
        ready, _, _ = select.select( [ sys.stdin ], [ ], [ ], 5.0 )
        if ready and not sys.stdin.readline():
            return
