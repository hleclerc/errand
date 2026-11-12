"""One environment, from outside it: the command handed over as it was typed, through the layers.
"""
from __future__ import annotations

import os
import subprocess

from .. import config, layers as L, setup
from .style import bad, dim, warn
from .project import _src_paths, _targets, child_env_for, TAGS
from .plans import plans_rel, read_plan


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
        # The first layer leads somewhere -- another machine, a machine to
        # boot -- and takes over; it hands whatever follows it on itself.
        lead = env.stack[ 0 ] if env.stack and hasattr( env.stack[ 0 ], "run" ) else None
        if lead is not None:
            rc |= lead.run( env.stack[ 1 : ], cmd, ctx, pull = known.pull or None,
                            echo = lambda s: print( dim( s ), flush = True ) )
        else:
            wrapped = L.compose( env.stack, cmd, ctx )
            print( dim( f"  $ {' '.join( str( a ) for a in wrapped.argv )}" ), flush = True )
            rc |= subprocess.run( wrapped.argv, env = { **os.environ, **wrapped.env },
                                  cwd = root ).returncode
    return rc


def go_there( env, tags, verb, rest, *, root, pull = ( ), time = None ):
    """The command, in `env`: one pass, or a preparation and then a run sized
    from the plan it wrote. -> the return code."""
    if env.vm is not None:
        # The child would be errand itself, over there -- and errand is a unix
        # program. `errand run` hands a virtual machine the command itself.
        print( bad( f"  {env.name} is a virtual machine: errand does not list entries in one" ) )
        return 1

    def through( phase, extra, needs = None ):
        stack = env.stack_for( phase, tags )
        needs = { **( needs or { } ), **( { "time": time } if time else { } ) }
        ctx = L.Context( root = root, tags = tags, needs = needs, phase = phase )
        cmd = L.Command( [ "python", "-m", "errand", verb, *extra, *rest ], child_env_for( env, tags ) )
        ssh = L.ssh_of( stack )
        for message in L.warnings_for( stack, ssh.remote_root( ctx ) if ssh else root ):
            print( warn( f"  warning: {message}" ), flush = True )
        if ssh is None:
            sched = L.batch_of( stack )
            if isinstance( sched, L.Slurm ) and sched.watched( ctx ):
                return L.run_on( L.Here( root ), stack, cmd, ctx, echo = lambda s: print( dim( s ), flush = True ) )
            wrapped = L.compose( stack, cmd, ctx )
            print( dim( f"  $ {' '.join( str( a ) for a in wrapped.argv )}" ), flush = True )
            return subprocess.run( wrapped.argv, env = { **os.environ, **wrapped.env },
                                   cwd = root ).returncode
        return ssh.run( stack[ 1 : ], cmd, ctx, echo = lambda s: print( dim( s ), flush = True ) )

    def fetch( paths ):
        ssh = L.ssh_of( env.stack_for( "run", tags ) )
        if ssh is not None and paths:
            there = ssh.remote_root( L.Context( root = root ) )
            print( dim( f"  rsync pull  <- {ssh.host}:{there} [{', '.join( paths )}]" ), flush = True )
            L.fetch( paths, ssh.host, there, root, ssh.options )

    def bring_back( ):
        fetch( [ plans_rel( root ) ] )
        plan = read_plan( root, env.name )
        if plan is not None:
            fetch( sorted( { r[ "under" ] for r in plan[ "runs" ] } ) )
        fetch( list( pull ) )
        return plan

    if verb == "list":
        # What would run there is what preparing there finds.
        return through( "prepare", [ ] )

    if env.single_pass( tags ):
        rc = through( "run", [ ] )
        bring_back()
        return rc

    rc = through( "prepare", [ "--phase", "prepare" ] )
    fetch( [ plans_rel( root ) ] )
    plan = read_plan( root, env.name )
    if rc or plan is None:
        if plan is None and not rc:
            print( bad( f"  {env.name}: the preparation wrote no plan" ) )
        return rc or 1
    rc = through( "run", [ "--from-plan" ], needs = plan[ "needs" ] )
    bring_back()
    return rc
