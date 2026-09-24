"""`errand.py`: what a project declares, and how an environment is chosen.

Ordinary Python, loaded once BY PATH -- never as a module named `errand`, so a
file sitting at the root of a project cannot shadow the package it imports
from. There is no entry point to call and nothing to return: `configure`,
`env` and `provider` register what they are given.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

from . import layers as L
from .expr import matches

# `errandfile.py` first, in the spirit of Makefile / Dockerfile / Justfile: it
# is visible, it is obviously the project's, and it cannot be mistaken for the
# package. `errand.py` is accepted because it is the name everyone reaches for
# first -- but it SHADOWS the package whenever the project root is on
# sys.path, which is to say for `python -m errand` and for any script run from
# the root. `load` says so out loud rather than letting that be discovered.
CONFIG_NAMES = ( "errandfile.py", "errand.py" )
CONFIG_FILE  = CONFIG_NAMES[ 0 ]


def config_in( directory: Path ):
    for name in CONFIG_NAMES:
        path = directory / name
        if path.is_file():
            return path
    return None


@dataclass
class Env:
    name  : str
    stack : list
    tags  : dict = field( default_factory = dict )

    @property
    def container( self ):
        return L.container_of( self.stack )

    @property
    def ssh( self ):
        return L.ssh_of( self.stack )

    def describe( self ):
        return " -> ".join( l.describe() for l in self.stack ) or "this interpreter"

    def wraps_anything( self ):
        """Does reaching this environment mean leaving this process?"""
        return any( not isinstance( l, L.Vars ) for l in self.stack )


@dataclass
class Settings:
    out    : str = "runs"
    src    : list = field( default_factory = list )
    default: str | None = None


settings  = Settings()
envs      : dict = { }
providers : list = [ ]


def configure( **kw ):
    """Project-wide settings. See `Settings`."""
    for k, v in kw.items():
        if not hasattr( settings, k ):
            raise TypeError( f"configure(): unknown setting {k!r}; "
                             f"expected one of { ', '.join( vars( settings ) ) }" )
        setattr( settings, k, v )


def env( name: str, stack = ( ), **tags ):
    """Declare an environment. Keyword arguments are its tags."""
    stack = list( stack )
    for i, layer in enumerate( stack ):
        if isinstance( layer, L.Ssh ) and i:
            raise ValueError( f"env( {name!r} ): Ssh must be the first layer" )
    envs[ name ] = Env( name, stack, dict( tags ) )
    return envs[ name ]


def provider( p ):
    providers.append( p )
    return p


def reset( ):
    global settings
    settings = Settings()
    envs.clear()
    providers.clear()


def load( root: Path, warn = None ) -> bool:
    """Read the project's config file if it is there. -> was there one?

    Always by path, and under a private module name, so that loading it can
    never be what shadows the package.
    """
    reset()
    path = config_in( root )
    if path is None:
        return False
    if path.name == "errand.py" and warn:
        warn( f"{path} shadows the errand package: `python -m errand` and any script "
              f"started from {root} will import this file instead.\n"
              f"  rename it to {CONFIG_FILE} -- the `errand` command works either way." )
    spec = importlib.util.spec_from_file_location( "_errand_config", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return True


# ── choosing where to run ────────────────────────────────────────────────────

def tag_names( ) -> list:
    """Every tag name any environment mentions: one flag each."""
    seen = { }
    for e in envs.values():
        for name in e.tags:
            seen[ name ] = True
    return sorted( seen )


def default_env( ) -> Env:
    """The one named `default`, the one `configure` named, or the first."""
    if settings.default and settings.default in envs:
        return envs[ settings.default ]
    if "default" in envs:
        return envs[ "default" ]
    if envs:
        return next( iter( envs.values() ) )
    return Env( "default", [ ], { } )


def select( names = None, expression = None, wanted_tags = None ):
    """Which environments to run in, and with which tags resolved.

    -> [ ( Env, resolved_tags ), … ]

    `wanted_tags` is what the per-dimension flags asked for -- `{ "fp": "32" }`.
    SAYING NOTHING MEANS EVERY VALUE: an environment that does not mention a
    dimension is selected for any value of it, and carries the asked-for value
    in its resolved tags, which is what a `Vars` callable reads back.
    """
    wanted_tags = wanted_tags or { }

    if names:
        chosen = [ ]
        for name in names:
            if name not in envs:
                raise ValueError( f"no environment named {name!r}; "
                                  f"declared: { ', '.join( envs ) or 'none' }" )
            e = envs[ name ]
            # Naming an environment AND asking for a tag it cannot have is a
            # contradiction, not a request to override it -- silently running
            # `--env only64 --fp 32` in single precision would be a lie.
            for key, value in wanted_tags.items():
                if key in e.tags and not _covers( e.tags[ key ], value ):
                    raise ValueError( f"environment {name!r} has {key}={e.tags[ key ]!r}, "
                                      f"so it cannot run with {key}={value!r}" )
            chosen.append( e )
    elif expression or wanted_tags:
        chosen = [ e for e in envs.values() if _fits( e, expression, wanted_tags ) ]
        if not chosen:
            asked = " & ".join( filter( None, [ expression,
                                                *( f"{k}={v}" for k, v in wanted_tags.items() ) ] ) )
            raise ValueError( f"no environment matches '{asked}'; "
                              f"declared: { ', '.join( envs ) or 'none' }" )
    else:
        chosen = [ default_env() ]

    return [ ( e, { **e.tags, **wanted_tags } ) for e in chosen ]


def _fits( e: Env, expression, wanted_tags ):
    for name, value in wanted_tags.items():
        if name in e.tags and not _covers( e.tags[ name ], value ):
            return False
    return matches( expression, e.tags ) if expression else True


def _covers( declared, value ) -> bool:
    """`fp = "32|64"` covers both; `fp = "64"` covers only that."""
    if declared is True:
        return str( value ).lower() in ( "true", "yes", "1" )
    return str( value ) in [ p.strip() for p in str( declared ).split( "|" ) ]
