"""Reaching an agent: which command opens the stream to it, and the connection over that stream.

A target says where the agent is, as data the hub can be handed:

    { "kind": "ssh", "host": …, "options": [ … ], "python": "python3", "keep_alive": 900 }
    { "kind": "local", "dir": …, "keep_alive": … }        ( this machine: tests, and later `Here` )
    { "kind": "cmd", "id": …, "argv": [ … ] }              ( an environment agent: `envs.py` )

Over ssh, errand's sources go first ( `bootstrap.ship` ), then one ssh runs the
search for a Python ( `bootstrap` ) and execs the `connect` bridge with it. The
agent's directory is named by what errand's sources are, so an edit to errand
is a new agent, and the old one goes quiet on its own.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from .. import bootstrap
from .client import Connection


KEEP_ALIVE = 900.0          # seconds an agent with no client and nothing running stays
AGENTS = "agents"                 # in errand's per-user directory


def ssh_target( ssh ) -> dict:
    return { "kind": "ssh", "host": ssh.host, "options": list( ssh.options ), "python": ssh.python,
             "keep_alive": float( getattr( ssh, "keep_alive", None ) or KEEP_ALIVE ) }


def identity( target: dict ) -> str:
    """Which agent a target reaches: where, not with which settings. Everything that reaches
    the same place shares one stream."""
    import json
    if target[ "kind" ] == "local":
        return json.dumps( [ "local", str( target[ "dir" ] ) ] )
    if target[ "kind" ] == "cmd":
        return json.dumps( [ "cmd", target[ "id" ] ] )
    return json.dumps( [ "ssh", target[ "host" ], list( target.get( "options", [ ] ) ) ] )


def name( target: dict ) -> str:
    """How a person calls it: the host, `here:<dir>`, or the id an environment agent was given."""
    if target.get( "id" ):
        return str( target[ "id" ] )
    if target[ "kind" ] == "local":
        return f"here:{target[ 'dir' ]}"
    return str( target.get( "host" ) )


def of_host( host: str, options = ( ) ) -> dict:
    """The target of `host`, for what knows only the host and its options ( rsync )."""
    return { "kind": "ssh", "host": host, "options": list( options ), "python": "python3", "keep_alive": KEEP_ALIVE }


def _via( target: dict, via ) -> dict:
    """How `rsh` reaches the agent: through the hub, or on a stream of its own ( `direct`, the mode of
    the command that asked: no hub where it would not have one )."""
    if via is None:
        from . import mode
        via = mode()
    return target if via == "hub" else { **target, "via": via }


def rsh_argv( host: str, options = ( ), via = "hub" ) -> list:
    """A remote shell that is the agent, over the hub's stream: `<this> host command…`. `via = None`:
    in the mode of the command that asks ( an agent's line, which must not go around the agent )."""
    import base64, json
    code = base64.urlsafe_b64encode( json.dumps( _via( of_host( host, options ), via ) ).encode() ).decode()
    return [ sys.executable, str( bootstrap.PACKAGE / "_boot.py" ), "-m", "errand.agents", "rsh", code ]


def rsh_argv_to( target: dict, via = None ) -> list:
    """The same, to any agent: one on a node of an allocation, reached through another."""
    import base64, json
    code = base64.urlsafe_b64encode( json.dumps( _via( target, via ) ).encode() ).decode()
    return [ sys.executable, str( bootstrap.PACKAGE / "_boot.py" ), "-m", "errand.agents", "rsh", code ]


def rsh( host: str, options = ( ) ) -> str:
    """rsync's `-e`: the same, as one string."""
    return " ".join( shlex.quote( a ) for a in rsh_argv( host, options ) )


def name_of( target: dict, machine: str | None = None ) -> str:
    """The host agent's directory name: per machine, since several login nodes behind one name ( a
    cluster's ) share the home it lives in, and an agent of one cannot be reached from another."""
    return f"host-{bootstrap.sources_key()}" + ( f"-{machine}" if machine else "" )


def this_machine( ) -> str:
    """This machine's short name, as `hostname -s` says it in `argv_of`."""
    import socket
    return socket.gethostname().split( "." )[ 0 ]


def argv_of( target: dict ) -> list:
    keep = int( target.get( "keep_alive" ) or KEEP_ALIVE )
    if target[ "kind" ] == "cmd":
        return list( target[ "argv" ] )          # a command whose stdio reaches a bridge ( `envs.py` )
    if target[ "kind" ] == "local":
        return [ sys.executable, "-m", "errand.agents", "connect", str( target[ "dir" ] ), str( keep ) ]
    where = f'"$base"/{shlex.quote( AGENTS + "/" + name_of( target ) )}-"$( hostname -s 2>/dev/null || hostname )"'
    then = f'exec "$py" "$base"/{shlex.quote( bootstrap.boot_rel() )} -m errand.agents connect {where} {keep}\n'
    line = " ".join( shlex.quote( a ) for a in ( "sh", "-c", bootstrap._script( then, target.get( "python" ) or "python3" ) ) )
    # Through the user's interactive shell, as every remote command is: it is what puts
    # micromamba or a module system on the PATH the agent, and all it starts, will have.
    from ..layers.gateways import ssh_options
    return [ "ssh", "-T", *ssh_options( target.get( "options" ) ), target[ "host" ], f"$SHELL -ic {shlex.quote( line )}" ]


def env_of( target: dict ) -> dict:
    if target.get( "env" ):
        return { **os.environ, **target[ "env" ] }
    if target[ "kind" ] == "local":
        parent = str( bootstrap.PACKAGE.parent )
        return { **os.environ, "PYTHONPATH": os.pathsep.join( p for p in ( parent, os.environ.get( "PYTHONPATH" ) ) if p ) }
    return dict( os.environ )


def prepare( target: dict ):
    if target[ "kind" ] == "ssh":
        # Before there is an agent to go through: plain ssh and rsync.
        bootstrap.ship( target[ "host" ], target.get( "options", [ ] ), agent = False )


def spawn( target: dict, stderr = None ) -> subprocess.Popen:
    """The stream to the agent: a process whose stdio reaches the bridge."""
    prepare( target )
    return subprocess.Popen( argv_of( target ), stdin = subprocess.PIPE, stdout = subprocess.PIPE,
                             stderr = stderr, env = env_of( target ), start_new_session = True,
                             cwd = target.get( "cwd" ) )


_DIRECT : list = [ ]        # the bridges this process owns ( `direct` )


def _end_direct( *_ ):
    for proc in _DIRECT:
        if proc.poll() is None:
            proc.terminate()


def _owned( proc ):
    """A bridge of its own session goes with this process, however it ends -- but SIGKILL: a waiter
    left behind would keep its lease fresh, and what it waits for would arrive for nobody ( ADR 0009 )."""
    import atexit
    import signal
    import threading
    if not _DIRECT:
        atexit.register( _end_direct )
        if threading.current_thread() is threading.main_thread():
            for sig in ( signal.SIGTERM, getattr( signal, "SIGHUP", None ) ):
                if sig is None or signal.getsignal( sig ) not in ( signal.SIG_DFL, None ):
                    continue

                def ending( signum, frame ):
                    _end_direct()
                    signal.signal( signum, signal.SIG_DFL )
                    os.kill( os.getpid(), signum )

                signal.signal( sig, ending )
    _DIRECT[ : ] = [ p for p in _DIRECT if p.poll() is None ] + [ proc ]


def direct( target: dict ) -> Connection:
    """A connection owned by this process: it ends with it ( `--no-agent`, no terminal )."""
    proc = spawn( target )
    _owned( proc )
    out, inp = proc.stdout.fileno(), proc.stdin

    def write( data ):
        inp.write( data )
        inp.flush()

    def close():
        for f in ( proc.stdin, proc.stdout ):
            try:
                f.close()
            except OSError:
                pass
        proc.terminate()

    return Connection( lambda n: os.read( out, n ), write, close, marker = True )


def hub_dir( fresh = False ) -> Path:
    return bootstrap.local_cache() / f"hub-{bootstrap.sources_key( fresh )}"
