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
    have = recorded( root, env )
    # Nothing recorded and everything present: it is somebody else's doing, and
    # it will be adopted rather than rebuilt -- so calling it `stale` would be
    # announcing work that is not going to happen.
    return OK if not have or have == want else STALE


def ensure( root: Path, env, ctx, *, force = False, echo = print, dry_run = False ) -> int:
    """Build or update whatever `env` declares and does not have.

    **What is already there was built by somebody, and is adopted rather than
    rebuilt.** The first time errand meets an environment there is no record of
    what it was built from, so every layer looks out of date -- and acting on
    that reading would mean recreating, on somebody's first command, an
    environment that has been working for months. So: present and never seen
    before is recorded as-is, and only a declaration that has CHANGED since a
    record errand itself wrote is a reason to touch it. `--setup force` is how
    you say the other thing.
    """
    want = wanted( env, ctx )
    have = recorded( root, env )
    first = not have

    steps = [ ]
    for i, layer in enumerate( env.stack ):
        if not hasattr( layer, "build" ):
            continue
        key = f"{i}:{layer.describe()}"
        present = _present( layer, env.ssh, ctx )
        if present and first and not force:
            continue                        # adopted: see above
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
    if not dry_run and env.ssh is not None:
        # A recipe, a requirements file, a project to install in editable mode:
        # all of them are files HERE, and the build happens THERE. Pushing
        # first is what makes `--setup` over ssh mean the same thing as
        # `--setup` at home.
        echo( f"    rsync push -> {env.ssh.host}:{env.ssh.remote_root( ctx )}" )
        L.push( ctx.root, env.ssh.host, env.ssh.remote_root( ctx ), env.ssh.options )
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


def _present( layer, ssh, ctx ) -> bool:
    """Is that layer THERE -- asked of the machine it would be built on.

    A remote environment's image does not live here, and answering "is it
    there" against this filesystem is answering about the wrong machine: an
    image built on the cluster last week would be rebuilt on every command,
    and one sitting here would never be built over there at all. So a layer
    may offer a `probe_shell`, a command whose exit code is the answer, and
    over ssh that is what is asked -- there, in the remote root.
    """
    if not hasattr( layer, "probe" ):
        return True
    if ssh is None:
        return layer.probe( ctx )
    if not hasattr( layer, "probe_shell" ):
        return False          # cannot ask: better to build than to assume
    return _run( layer.probe_shell( ctx ), ssh, ctx, quiet = True ) == 0


def _record( root: Path, env, want: dict ):
    path = state_path( root, env )
    path.parent.mkdir( parents = True, exist_ok = True )
    yamlish.write( path, { "env": env.name, "layers": want } )


def _run( step: str, ssh, ctx, *, quiet = False ) -> int:
    hush = { "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL } if quiet else { }
    if ssh is None:
        # From the root, like the remote side: a step names what it needs the
        # way the project declares it, and that is relative to the root.
        return subprocess.run( [ "sh", "-c", step ], cwd = str( ctx.root ), **hush ).returncode
    line = f"cd {shlex.quote( str( ssh.remote_root( ctx ) ) )} && {step}"
    # `-t`: building an image can ask for a password, and prints a progress bar
    # nobody sees without a terminal. An interactive shell, for the same reason
    # as everywhere else -- micromamba and the rest live in an rc file. Not for
    # a probe, which nobody is watching and which must not steal the terminal.
    tty = [ ] if quiet else [ "-t" ]
    return subprocess.run( [ "ssh", *tty, *ssh.options, ssh.host,
                             f"$SHELL -ic {shlex.quote( line )}" ], **hush ).returncode
