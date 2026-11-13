"""Environment agents: an agent at the end of a stack, with the environment's own interpreter.

The bridge to it is started THROUGH the layers -- `micromamba run python …`, a
module loaded, a container entered, variables set -- so the agent it starts
lives inside all of them, and so does everything it starts after. Over `Ssh`,
the host agent starts that bridge ( through `rsh`, over the hub's stream, or
one ssh without a hub ): no new login per command, no new `micromamba run`.

The agent's directory is named by what errand's sources are and by the
command that reaches it -- which holds every layer's declaration -- so a
changed stack is another agent, as an edit to errand is.
"""
from __future__ import annotations

import hashlib
import shlex
from pathlib import Path

from .. import bootstrap, layers as L
from . import mode, upstream as U


def target( env, stack, tags, phase, *, root, ssh = None, cache = None, keep_alive = None ) -> dict:
    """The target of `env`'s agent for `phase`, `stack` being that phase's layers and `root`
    the project's root where the agent runs ( over there, after an `Ssh` )."""
    inner = [ l for l in stack if not isinstance( l, L.Ssh ) ]
    keep = int( keep_alive or getattr( env, "keep_alive", None ) or U.KEEP_ALIVE )
    cache = cache or str( bootstrap.local_cache() )      # errand's per-user directory where the agent runs
    ctx = L.Context( root = Path( root ), tags = tags, remote = ssh is not None, phase = phase )
    boot = None if ssh is not None else str( bootstrap.PACKAGE / "_boot.py" )

    def line_for( where: str ) -> str:
        cmd = L.Command( [ "python", "-m", "errand.agents", "connect", where, str( keep ) ] )
        sent = bootstrap.command( cmd, inner, cache, ssh.python if ssh is not None else "python", boot = boot )
        return f"cd {shlex.quote( str( root ) )} && {L.compose( inner, sent, ctx ).shell()}"

    # Named from what it reaches through, which the name itself is not part of.
    shape = line_for( "@" )
    digest = hashlib.sha1( f"{env.name}\0{phase}\0{shape}".encode() ).hexdigest()[ : 10 ]
    name = f"env-{bootstrap.sources_key()}-{digest}"
    line = line_for( f"{cache}/{U.AGENTS}/{name}" )

    if ssh is None:
        argv = [ "sh", "-c", line ]
    elif mode() == "hub":
        # Through the host agent: its interactive shell, as every remote line is.
        argv = [ *U.rsh_argv( ssh.host, ssh.options ), ssh.host, f"$SHELL -ic {shlex.quote( line )}" ]
    else:
        argv = [ "ssh", "-T", *ssh.options, ssh.host, f"$SHELL -ic {shlex.quote( line )}" ]
    where = ssh.host if ssh is not None else "here"
    return { "kind": "cmd", "id": f"{where}:{name}", "argv": argv, "keep_alive": keep }


def python_of( conn ) -> str:
    """The environment's interpreter, as its agent knows it."""
    return conn.ping()[ "python" ]


def boot_of( ssh, cache ) -> str:
    return f"{cache}/{bootstrap.boot_rel()}" if ssh is not None else str( bootstrap.PACKAGE / "_boot.py" )


def ops_argv( python: str, boot: str, request: dict, preload = None ) -> list:
    """A session: forked from the agent's zygote when the stack has a `Preload` ( `warm.py` ),
    a Python started anew otherwise. `ERRAND_WARM=0` here starts it anew anyway."""
    import json
    import os
    if preload is None or os.environ.get( "ERRAND_WARM" ) == "0":
        return [ python, boot, "-m", "errand.agents.ops", "session", json.dumps( request ) ]
    request = { **request, "warm": True, "preload": preload.modules, "learn": preload.learn }
    return [ python, boot, "-m", "errand.agents.warm", "session", json.dumps( request ) ]

