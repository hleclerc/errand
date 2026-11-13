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
AGENTS = f"{bootstrap.BASE}/agents"


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


def rsh_argv( host: str, options = ( ) ) -> list:
    """A remote shell that is the agent, over the hub's stream: `<this> host command…`."""
    import base64, json
    code = base64.urlsafe_b64encode( json.dumps( of_host( host, options ) ).encode() ).decode()
    return [ sys.executable, str( bootstrap.PACKAGE / "_boot.py" ), "-m", "errand.agents", "rsh", code ]


def rsh_argv_to( target: dict ) -> list:
    """The same, to any agent: one on a node of an allocation, reached through another."""
    import base64, json
    code = base64.urlsafe_b64encode( json.dumps( target ).encode() ).decode()
    return [ sys.executable, str( bootstrap.PACKAGE / "_boot.py" ), "-m", "errand.agents", "rsh", code ]


def rsh( host: str, options = ( ) ) -> str:
    """rsync's `-e`: the same, as one string."""
    return " ".join( shlex.quote( a ) for a in rsh_argv( host, options ) )


def name_of( target: dict ) -> str:
    return f"host-{bootstrap.sources_key()}"


def argv_of( target: dict ) -> list:
    keep = int( target.get( "keep_alive" ) or KEEP_ALIVE )
    if target[ "kind" ] == "cmd":
        return list( target[ "argv" ] )          # a command whose stdio reaches a bridge ( `envs.py` )
    if target[ "kind" ] == "local":
        return [ sys.executable, "-m", "errand.agents", "connect", str( target[ "dir" ] ), str( keep ) ]
    where = f'"$HOME"/{shlex.quote( AGENTS + "/" + name_of( target ) )}'
    then = f'exec "$py" "$HOME"/{shlex.quote( bootstrap.boot_rel() )} -m errand.agents connect {where} {keep}\n'
    line = " ".join( shlex.quote( a ) for a in ( "sh", "-c", bootstrap._script( then, target.get( "python" ) or "python3" ) ) )
    # Through the user's interactive shell, as every remote command is: it is what puts
    # micromamba or a module system on the PATH the agent, and all it starts, will have.
    return [ "ssh", "-T", *target.get( "options", [ ] ), target[ "host" ], f"$SHELL -ic {shlex.quote( line )}" ]


def env_of( target: dict ) -> dict:
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
                             stderr = stderr, env = env_of( target ), start_new_session = True )


def direct( target: dict ) -> Connection:
    """A connection owned by this process: it ends with it ( `--no-agent`, no terminal )."""
    proc = spawn( target )
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
    return Path.home() / bootstrap.BASE / f"hub-{bootstrap.sources_key( fresh )}"
