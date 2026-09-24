"""Environments kept current by themselves.

A layer says what it needs -- an interpreter version, a channel list, a
requirements file, a recipe, a pip list. Before running anything, what it says
is compared against what was last built into it, and the difference is made up.
Creating an environment, installing into it and rebuilding an image are one
operation seen at three moments, which is why there is one command for all
three and why it mostly runs by itself.

The record of what was built lives outside the output tree, in `.errand/`: it
is state about this checkout, not a result.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from . import layers as L, yamlish

STATE_DIR = ".errand"

OK, STALE, MISSING, UNKNOWN = "ok", "stale", "not built", "unknown"


def state_path( root: Path, env ) -> Path:
    return root / STATE_DIR / f"env-{env.name}.yaml"


def wanted( env, ctx ) -> dict:
    """The fingerprint each layer of `env` says it should have."""
    out = { }
    for i, layer in enumerate( env.stack ):
        if hasattr( layer, "spec" ):
            out[ f"{i}:{layer.describe()}" ] = L.fingerprint( *layer.spec( ctx ) )
    return out


def recorded( root: Path, env ) -> dict:
    return ( yamlish.read( state_path( root, env ) ) or { } ).get( "layers", { } ) or { }


def status( root: Path, env, ctx ) -> str:
    """ok / stale / not built / unknown -- what `--envs` prints."""
    want = wanted( env, ctx )
    if not want:
        return UNKNOWN if env.wraps_anything() else OK
    if env.ssh:
        return UNKNOWN           # only the other machine can say
    for layer in env.stack:
        if hasattr( layer, "probe" ) and not layer.probe( ctx ):
            return MISSING
    return OK if recorded( root, env ) == want else STALE


def ensure( root: Path, env, ctx, *, force = False, echo = print, dry_run = False ) -> int:
    """Build or update whatever `env` declares and does not have."""
    want = wanted( env, ctx )
    have = recorded( root, env )

    steps = [ ]
    for i, layer in enumerate( env.stack ):
        if not hasattr( layer, "build" ):
            continue
        key = f"{i}:{layer.describe()}"
        present = layer.probe( ctx ) if hasattr( layer, "probe" ) else True
        if force or not present or have.get( key ) != want.get( key ):
            steps += [ ( layer, s ) for s in layer.build( ctx ) ]

    if not steps:
        # Nothing to do, but what it declares may still differ from what was
        # recorded -- a layer with no build of its own, or a first run. Record
        # it, or the environment stays "stale" forever with nothing to fix.
        if want and have != want and not dry_run:
            _record( root, env, want )
        return 0

    why = "rebuilding" if force else "bringing up to date"
    echo( f"  {why} {env.name}" )
    if dry_run:
        for layer, step in steps:
            echo( f"    would run: {step}" )
        return 0

    for layer, step in steps:
        echo( f"    $ {step}" )
        if _run( step, env.ssh, ctx ) != 0:
            echo( f"    failed while preparing {layer.describe()}" )
            return 1

    _record( root, env, want )
    return 0


def _record( root: Path, env, want: dict ):
    path = state_path( root, env )
    path.parent.mkdir( parents = True, exist_ok = True )
    yamlish.write( path, { "env": env.name, "layers": want } )


def _run( step: str, ssh, ctx ) -> int:
    if ssh is None:
        return subprocess.run( [ "sh", "-c", step ] ).returncode
    line = f"cd {shlex.quote( str( ssh.remote_root( ctx ) ) )} && {step}"
    return subprocess.run( [ "ssh", ssh.host, f"$SHELL -ic {shlex.quote( line )}" ] ).returncode
