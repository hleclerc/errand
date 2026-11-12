"""One environment, from outside it: the command handed over as it was typed, through the layers.
"""
from __future__ import annotations

import os
import subprocess

from .. import agents, config, layers as L, setup
from . import guest
from .style import bad, dim
from .project import _src_paths, _targets, TAGS


# ── running, elsewhere ───────────────────────────────────────────────────────

def run_there( known, command, *, root, interactive = False, targets = None ):
    """`errand shell --env X`: a shell in that environment -- or a command in a
    place errand itself does not run in ( a virtual machine ).

    Not a feature of the runner so much as of the environments. They are
    already declared here, once, with the layers that lead to them -- a venv, a
    container, another machine -- so being let into one, to look at a toolchain
    or to ask a card what it is, is a smaller thing than a second tool that
    would have to describe them all over again.

    The first word is replaced by the interpreter of the place when it names an
    interpreter, and kept when it does not ( see `layers.under` ).
    """
    if targets is None:
        try:
            targets = _targets( known, config.tag_names() )
        except ValueError as err:
            print( bad( str( err ) ) )
            return 1

    rc = 0
    for env, tags in targets:
        ctx = L.Context( root = root, tags = tags, interactive = interactive )
        # The same question as before any work: is the place ready? Being let
        # into an environment that has not been built yet is the one moment
        # where you MOST want it built -- there is nothing else about to do it.
        if not known.no_setup:
            if setup.ensure( root, env, ctx,
                             echo = lambda s: print( dim( s ), flush = True ) ):
                print( bad( f"  could not prepare {env.name}" ) )
                rc = 1
                continue
        # The same sources the work itself would see. Being let into the
        # environment to look at something is pointless if what you look at is
        # somebody else's checkout of the same package.
        path = os.pathsep.join( _src_paths( root ) + [ os.environ.get( "PYTHONPATH", "" ) ] )
        cmd = L.Command( list( command ),
                         { TAGS: ",".join( f"{k}={v}" for k, v in sorted( tags.items() ) ),
                           "PYTHONPATH": path.rstrip( os.pathsep ) } )
        print( dim( f"\n  -> {env.name}  {env.describe()}" ), flush = True )
        if interactive and env.vm is not None and guest.usable( env ) and agents.enabled():
            # A shell in Windows: cmd.exe in a pseudo-console, through the guest's agent.
            rc |= _guest_shell( env, tags, root )
            continue
        # The first layer leads somewhere -- another machine, a machine to
        # boot -- and takes over; it hands whatever follows it on itself.
        lead = env.stack[ 0 ] if env.stack and isinstance( env.stack[ 0 ], L.Gateway ) else None
        if lead is not None:
            rc |= lead.run( env.stack[ 1 : ], cmd, ctx, pull = known.pull or None,
                            echo = lambda s: print( dim( s ), flush = True ) )
        else:
            wrapped = L.compose( env.stack, cmd, ctx )
            print( dim( f"  $ {' '.join( str( a ) for a in wrapped.argv )}" ), flush = True )
            rc |= subprocess.run( wrapped.argv, env = { **os.environ, **wrapped.env },
                                  cwd = root ).returncode
    return rc


def _guest_shell( env, tags, root ) -> int:
    from ..vm.common import VmError
    from . import drive
    where = drive.arrive( env, tags, root )
    try:
        with guest.Guest( env, tags, where, lambda m: print( dim( m ), flush = True ) ) as g:
            return agents.interact( agents.open( g.target() ), [ "cmd.exe" ], cwd = g.there )
    except VmError as err:
        print( bad( f"  {err}" ) )
        return 1
