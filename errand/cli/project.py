"""The project: its root, where its sources are, where its output goes, and which environments a
command asked for, with which tags.
"""
from __future__ import annotations

import contextlib
import itertools
import os
import sys
from pathlib import Path

from .. import config, layers as L, results as R, trace
from .grid import split_values


# Set on the child side of a dispatch: the environment has already been entered
# by the layers that wrapped this process, so re-selecting it here would send it
# round again -- and, over ssh, straight back out to the machine it is on.
IN_ENV = "ERRAND_IN_ENV"
TAGS   = "ERRAND_TAGS"


def find_root( start: Path | None = None ) -> Path:
    """The project root: the nearest ancestor holding an errand-*.py, else here.

    Deliberately not the git root. Walking up to one means that running from a
    subdirectory of a large repository silently widens the search to the whole
    of it -- and with no errand-*.py there is nothing that says where the project
    begins, so "here and below" is the answer least likely to surprise.
    """
    here = ( start or Path.cwd() ).resolve()
    for directory in [ here, *here.parents ]:
        if config.config_in( directory ) is not None:
            return directory
    return here


@contextlib.contextmanager
def _with_env( values: dict ):
    """Set, then put back exactly what was there -- including nothing."""
    before = { k: os.environ.get( k ) for k in values }
    os.environ.update( values )
    try:
        yield
    finally:
        for k, old in before.items():
            if old is None:
                os.environ.pop( k, None )
            else:
                os.environ[ k ] = old


def _src_paths( root ):
    """Where this project's own code lives, nearest first."""
    return [ str( root / extra ) for extra in ( config.settings.src or [ "src" ] )
             if ( root / extra ).is_dir() ] + [ str( root ) ]


def _put_src_on_path( root ):
    for path in reversed( _src_paths( root ) ):
        sys.path.insert( 0, path )


def ssh_root( env, root ):
    return env.ssh.remote_root( L.Context( root = root ) ) if env.ssh else root


def build_dir_for( root, env_name ) -> Path:
    """`build/<env>/`: where the runners' builds go for that environment."""
    return Path( root ) / config.settings.build / R.slug( env_name or "default" )


def output_tree( root: Path, known ) -> Path:
    """Where runs are recorded: `errand-outputs/runs/`, or the tree `--out` names."""
    out = getattr( known, "out", None )
    R.pattern = out if out and "{" in out else None
    if out and not R.pattern:
        tree = Path( out )
        return tree if tree.is_absolute() else root / tree
    return config.runs( root )


def _from_root( target: str, root: Path ) -> str:
    """A target written from the project root, as one from the cwd."""
    path, sep, name = target.partition( "::" )
    moved = os.path.relpath( root / path, Path.cwd() ) if path else os.path.relpath( root, Path.cwd() )
    return moved + sep + name


def _tag_values( known ) -> bool:
    """Whether an environment was asked for by one of its tags ( `--driver torch` )."""
    return any( v is not None for k, v in vars( known ).items() if k.startswith( "tag_" ) )


def _tags_from_env( ) -> dict:
    out = { }
    for item in filter( None, os.environ.get( TAGS, "" ).split( "," ) ):
        k, _, v = item.partition( "=" )
        out[ k ] = v if v else True
    return out


def _targets( args, tag_names ):
    """The environments to run in, one entry per combination of tag values."""
    sep = getattr( args, "grid", None )
    names = split_values( args.env, sep, what = "--env" ) if args.env else None

    axes = { }
    for name in tag_names:
        values = split_values( getattr( args, f"tag_{name}", None ), sep,
                               what = f"--{name.replace( '_', '-' )}" )
        if values != [ None ]:
            axes[ name ] = values

    if not axes:
        return config.select( names = names, expression = args.env_tags )

    out = [ ]
    keys = list( axes )
    for combo in itertools.product( *( axes[ k ] for k in keys ) ):
        wanted = dict( zip( keys, combo ) )
        out += config.select( names = names, expression = args.env_tags, wanted_tags = wanted )
    return out


# ── one environment, from outside it ────────────────────────────────────────

def child_env_for( env, tags ) -> dict:
    """What crosses into the environment: which one it is, its resolved tags,
    and the stamp of this command -- NOT `--env`, since re-selecting over there
    would send an ssh environment straight back out to the machine it is on."""
    return { IN_ENV: env.name,
             TAGS: ",".join( f"{k}={v}" for k, v in sorted( tags.items() ) ),
             R.STAMP_ENV: R.stamp(),
             "PYTHONUNBUFFERED": "1",
             # `-v` over there too: the env a command crosses ssh with
             **( { trace.ENV: "1" } if trace.enabled() else { } ) }
