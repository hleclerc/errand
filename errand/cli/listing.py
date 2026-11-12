"""What is printed about the project: environments, the queue, entries, files that could not be read,
and the epilogue of a run.
"""
from __future__ import annotations

import os

from .. import config, discovery, entries as E, layers as L, queue, runner as P, setup
from .style import bad, dim, good, head, warn
from .project import build_dir_for


# ── listing ──────────────────────────────────────────────────────────────────

def print_envs( root ):
    print( head( "\nEnvironments" ) )
    if not config.envs:
        print( dim( "  none declared -- work runs in this interpreter" ) )
        print( dim( f"  declare some in {config.ENVS_FILE} at the project root" ) )
        return 0
    default = config.default()
    width = max( len( n ) for n in config.envs )
    for name, e in config.envs.items():
        ctx = L.Context( root = root, tags = e.tags )
        state = setup.status( root, e, ctx )
        tags = "  ".join( k if v is True else f"{k}={v}" for k, v in sorted( e.tags.items() ) )
        mark = "  <- default" if e is default else ""
        note = "" if state == setup.OK else f"  {warn( state )}"
        print( f"  {name:{width}}  {tags:28}  {dim( e.describe() )}{note}{mark}" )
    print( dim( f"\n  choose one with --env <name>, or by tag: "
                f"{ ' '.join( '--' + n for n in config.tag_names() ) or '(no tags declared)' }" ) )
    return 0


def prepare_runners( entries, *, root, out_root, tags, env_name = None ):
    """Give each runner its one chance to get ready. -> [ ( who, why ) ] on trouble."""
    out = [ ]
    seen = [ ]
    for e in entries:
        if e.runner is not None and not any( e.runner is p for p in seen + discovery.built ):
            seen.append( e.runner )
    for p in seen:
        mine = [ e for e in entries if e.runner is p ]
        ctx = P.RunContext( root = root, out_dir = out_root, env = { },
                            build_dir = build_dir_for( root, env_name ) )
        if p.builds_to_collect or getattr( p, "build", None ):
            # Only for what builds: a command run here leaves no `build/` behind.
            ctx.build_dir.mkdir( parents = True, exist_ok = True )
        why = p.prepare( mine, ctx )
        if why:
            out.append( ( p.name, why ) )
    return out


def print_queue( ):
    scheduler = queue.someone_else_is_scheduling()
    print( head( f"\nThe machine ({queue.host()})" ) )
    have = queue.capacity()
    print( dim( f"  has  cpus={have[ 'cpus' ]:g}  ram={have[ 'ram' ]:.0f}M  gpus={have[ 'gpus' ]:g}" ) )
    if scheduler:
        print( dim( f"  {scheduler} already decides what runs here; errand does not queue" ) )
        return 0
    lines = queue.describe()
    if not lines:
        print( dim( "  nothing held" ) )
    for line in lines:
        print( f"  {line}" )
    print( dim( f"  {queue.queue_dir()}" ) )
    return 0


def say_broken( ):
    """What declares work and would not import. Said wherever entries are
    listed, because a list that is short for a reason must give the reason."""
    if not discovery.broken:
        return
    print( bad( f"\n  {len( discovery.broken )} file(s) could not be read:" ) )
    for path, why, _ in discovery.broken:
        print( f"    {path}  {dim( why )}" )


def print_entries( entries ):
    if not entries:
        print( dim( "  nothing matched" ) )
        return
    for e in entries:
        site = f"{os.path.relpath( e.file )}:{e.line}" if e.line else os.path.relpath( e.file )
        runner = f"  {e.runner.name}" if e.runner is not None else ""
        print( head( f"\n{e.name}" ) + dim( f"  ({site})  [{e.kind}]{runner}" ) )
        if e.tags:
            print( dim( f"  tags: {', '.join( e.tags )}" ) )
        traits = [ k if v else f"!{k}" for k, v in e.traits.items() if v != E.TRAITS[ k ] ]
        if traits:
            print( dim( f"  traits: {' '.join( traits )}" ) )
        if e.resources:
            print( dim( f"  needs: {', '.join( f'{k}={v}' for k, v in e.resources.items() )}" ) )
        for name, p in e.params.items():
            flag = f"--{name.replace( '_', '-' )}"
            extra = f"  choices: {p.choices}" if p.choices else ""
            print( f"  {flag:22s} default={p.default!r}  {p.help}{extra}" )


def _epilogue( report, rc ):
    print( "\n" + "=" * 46 )
    if report.broken:
        # Everything else still ran -- that is the point of being tolerant --
        # but a file that declares work and cannot be read is a failure, not a
        # detail, and it takes the return code with it.
        print( bad( f"  {len( report.broken )} file(s) could not be read:" ) )
        for path, why, _ in report.broken:
            print( f"    {path}  {dim( why )}" )
    if report.skipped:
        # A skip is not a pass. It gets its own block, with what was missing and
        # what to write where -- a suite that tested nothing must not look like
        # a suite that passed.
        print( warn( f"  {len( report.skipped )} skipped:" ) )
        for e, reason, hint in report.skipped:
            print( f"    {e.name}  {dim( f'({e.file.name}:{e.line})' )}  {reason}" )
            if hint:
                for line in hint.splitlines():
                    print( dim( f"      {line}" ) )
    if report.failed:
        for e, why in report.failed:
            print( f"  {bad( 'FAILED' )} {e.name}  ({e.file}:{e.line})  {why}" )
        return 1
    if report.broken:
        return 1
    if rc:
        return rc
    print( good( "  all good" ) + ( warn( f"  ({len( report.skipped )} skipped)" )
                                    if report.skipped else "" ) )
    return 0
