"""`errand-*.py`: what a project declares, and how an environment is chosen.

Ordinary Python, loaded once BY PATH -- never as a module named `errand`, so a
file sitting at the root of a project cannot shadow the package it imports
from. There is no entry point to call and nothing to return: `configure`,
`envs` and `provider` register what they are given.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import layers as L
from .expr import matches

# Every file matching this, at the root, is read. The root is the nearest directory that has one
# -- which is also how a project nested inside a bigger repository says where it starts.
CONFIG_GLOB = "errand-*.py"
CONFIG_FILE = "errand-project.py"      # the name `--init` writes: the one that is versioned
ENVS_FILE   = "errand-envs.py"      # the one that is not


def config_files( directory: Path ) -> list:
    """The project files in `directory`, in the order they are read."""
    return sorted( p for p in directory.glob( CONFIG_GLOB ) if p.is_file() )


def config_in( directory: Path ):
    """The first project file in `directory`, or None: is this a project root?"""
    files = config_files( directory )
    return files[ 0 ] if files else None


class Env:
    """Where work runs: a stack of layers, and the tags saying what it is.

        errand.envs[ "gpu" ] = errand.Env( [ errand.Apptainer( ... ) ], driver = "cuda" )

    The name is the key it is stored under; `Env` does not take one.
    """

    def __init__( self, stack = ( ), **tags ):
        self.name  = ""
        self.stack = list( stack )
        self.tags  = dict( tags )
        for i, layer in enumerate( self.stack ):
            if isinstance( layer, L.Ssh ) and i:
                raise ValueError( "Ssh must be the first layer" )

    @classmethod
    def make( cls, name: str, stack = ( ), tags = None ):
        e = cls( stack, **( tags or { } ) )
        e.name = name
        return e

    def __repr__( self ):
        return f"Env( {self.name!r}, {self.describe()} )"

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
    # Directories discovery must not walk into: vendored code, fixtures, a copy
    # of something that would be imported and should not be.
    exclude: list = field( default_factory = list )


class Envs( dict ):
    """`errand.envs[ "name" ] = errand.Env( ... )`: the key becomes the environment's name."""

    def __setitem__( self, name, env ):
        if not isinstance( env, Env ):
            raise TypeError( f"envs[ {name!r} ] must be an errand.Env, not {type( env ).__name__}" )
        env.name = name
        super().__setitem__( name, env )


settings  = Settings()
envs      = Envs()
providers : list = [ ]
# What was GUESSED for a project with no config file of its own: [ detect.Guess ].
# Kept apart from `providers` so that it can be announced -- a guess is never silent.
guessed   : list = [ ]


def configure( **kw ):
    """Project-wide settings. See `Settings`."""
    for k, v in kw.items():
        if not hasattr( settings, k ):
            raise TypeError( f"configure(): unknown setting {k!r}; "
                             f"expected one of { ', '.join( vars( settings ) ) }" )
        setattr( settings, k, v )


def provider( p ):
    providers.append( p )
    return p


def reset( ):
    global settings
    settings = Settings()
    sys.modules[ "errand" ].default_env = None
    envs.clear()
    providers.clear()
    guessed.clear()


def load( root: Path, warn = None ) -> bool:
    """Read the project's `errand-*.py` files if there are any. -> were there?

    Always by path, and under private module names, so that loading one can
    never be what shadows the package. Each file's plain values ( strings,
    numbers, lists... ) are offered to the files after it, and to entries, as
    `errand.value` / `errand.need`.
    """
    from . import local

    reset()
    files = config_files( root )
    local.reset( files, root )
    if not files:
        # No declaration: look at what is there. Existing suites are adopted for
        # this run only, and `cli` says so; `errand --init` writes the guess down.
        from . import detect
        for g in detect.guess( root ):
            guessed.append( g )
            providers.append( g.make() )
        return False
    for path in files:
        spec = importlib.util.spec_from_file_location(
            "_errand_" + re.sub( r"\W", "_", path.stem ), path )
        module = importlib.util.module_from_spec( spec )
        spec.loader.exec_module( module )
        local.offer( module )
    return True


# ── choosing where to run ────────────────────────────────────────────────────

def tag_names( ) -> list:
    """Every tag name any environment mentions: one flag each."""
    seen = { }
    for e in envs.values():
        for name in e.tags:
            seen[ name ] = True
    return sorted( seen )


def default( ) -> Env:
    """The one `errand.default_env` names, else the first declared, else this interpreter."""
    named = sys.modules[ "errand" ].default_env
    if named is not None:
        if named not in envs:
            raise ValueError( f"errand.default_env = {named!r}, but no environment has that name; "
                              f"declared: { ', '.join( envs ) or 'none' }" )
        return envs[ named ]
    if envs:
        return next( iter( envs.values() ) )
    return Env.make( "default", [ ], { } )


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
        chosen = [ default() ]

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
