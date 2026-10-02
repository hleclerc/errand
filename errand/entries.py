"""Declaring work: `entry` and the three presets over it.

The guard works in two phases, driven by the runner.

  collect  -- registers the entry and returns something falsy, so the body is
              skipped and the file can be read for what it declares
  run      -- returns an `Args` (truthy) for the one entry being run, and
              something falsy for every other guard in the same file

An entry is identified by its CALL SITE -- module plus line -- not by its name,
so two entries may share a name, in one file or across several. The runner
re-imports a file once per selected entry, which is what makes each body run
isolated and each failure land on its own entry.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Traits: how an entry should be treated, as opposed to what it does.
TRAITS = {
    "bulk"       : True,    # picked up by a bare `errand`, with no pattern
    "keep"       : False,   # its numbers are kept and compared date to date
    "exclusive"  : False,   # it needs the machine to itself
    "stable_path": False,   # `latest/` is what you are meant to open
}

# Resources counted against what the host has, when it is shared.
RESOURCES = ( "cpus", "ram", "gpus" )


class Param:
    """A typed flag, its type taken from the default: Param(1000) is an int."""
    __slots__ = ( "default", "help", "choices" )

    def __init__( self, default: Any, *, help: str = "", choices: list | None = None ):
        self.default = default
        self.help    = help
        self.choices = choices

    @property
    def ptype( self ):
        return type( self.default )


class Args:
    """What a running entry gets back: its parameters, out_dir and results."""
    __slots__ = ( "__dict__", )

    def __init__( self, **kw ):
        self.__dict__.update( kw )

    def __repr__( self ):
        return "Args(" + ", ".join( f"{k}={v!r}" for k, v in self.__dict__.items() ) + ")"


class Entry:
    # A provider ( None: this file's own two-phase guard ) and the opaque key it
    # uses to find this entry again when asked to run it.
    provider = None
    key      = None

    def __init__( self, name, tags, params, traits, resources, file, line, module ):
        self.name      = name
        self.tags      = tags          # list[str], free-form, filtered by -e
        self.params    = params        # dict[str, Param]
        self.traits    = traits        # dict[str, bool]
        self.resources = resources     # dict[str, int|str]
        self.file      = Path( file )
        self.line      = line
        self.module    = module

    @property
    def site( self ):
        """Identity: where it is written, not what it is called."""
        return ( self.module, self.line )

    @property
    def kind( self ):
        """The preset it most resembles, for `-k` and for display."""
        if self.traits[ "keep" ]:
            return "bench"
        if self.traits[ "stable_path" ]:
            return "experiment"
        return "test"

    def __repr__( self ):
        return f"<Entry {self.name!r} {self.file.name}:{self.line}>"


# ── the two phases ───────────────────────────────────────────────────────────

COLLECT, RUN = 0, 1

phase: int            = COLLECT
target: Entry | None  = None          # the entry being run, in the RUN phase
collected: list       = [ ]
results: dict         = { }           # the dict behind the running Args.results
_resolved: dict       = { }           # parameter values for the running entry
_tags: dict           = { }           # the selected environment's tags


def reset_collection( ):
    global phase, target
    phase, target = COLLECT, None
    collected.clear()


def begin_run( entry, resolved, out_dir ):
    global phase, target
    phase, target = RUN, entry
    results.clear()
    _resolved.clear()
    _resolved.update( resolved )
    os.environ[ "ERRAND_OUT_DIR" ] = str( out_dir )


def end_run( ):
    global phase, target
    phase, target = COLLECT, None


def set_tags( tags: dict ):
    _tags.clear()
    _tags.update( tags )


# ── the declaration ──────────────────────────────────────────────────────────

def entry( name, tags = None, /, **kw ):
    """Declare a piece of work, or run it.

    `name` and `tags` are positional-only, and `tags = [ … ]` is accepted as a
    keyword too -- both spellings read well and neither can be confused with a
    parameter, since a parameter is recognized by BEING a `Param`. Every other
    keyword must name a trait or a resource.
    """
    if "tags" in kw:
        if tags is not None:
            raise TypeError( f"entry( {name!r} ): tags given twice" )
        tags = kw.pop( "tags" )

    params  = { k: v for k, v in kw.items() if isinstance( v, Param ) }
    rest    = { k: v for k, v in kw.items() if not isinstance( v, Param ) }

    traits  = dict( TRAITS )
    resources = { }
    for k, v in rest.items():
        if k in TRAITS:
            traits[ k ] = bool( v )
        elif k in RESOURCES:
            resources[ k ] = v
        else:
            raise TypeError(
                f"entry( {name!r} ): unknown keyword {k!r}. A parameter must be a Param "
                f"( {k} = Param( {v!r} ) ); a trait is one of { ', '.join( TRAITS ) }; "
                f"a resource is one of { ', '.join( RESOURCES ) }."
            )

    frame  = sys._getframe( 2 if _is_preset( ) else 1 )
    line   = frame.f_lineno
    module = frame.f_globals.get( "__name__" )

    if phase == COLLECT:
        collected.append( Entry( name, _as_list( tags ), params, traits, resources,
                                 frame.f_code.co_filename, line, module ) )
        return False

    if target is None or ( module, line ) != target.site:
        return False

    return Args( results = results, out_dir = out_dir( ), **dict( _resolved ) )


def _is_preset( ):
    """True when `entry` was reached through test/bench/experiment.

    The call site has to be the user's line, not the preset's, so the frame to
    read is one further up when a preset is in between.
    """
    return sys._getframe( 2 ).f_globals.get( "__name__" ) == __name__


def test( name, tags = None, /, **kw ):
    """It must pass. Picked up by a bare `errand`."""
    return entry( name, tags, **kw )


def bench( name, tags = None, /, **kw ):
    """Numbers to follow, measured alone. Kept; takes the machine to itself.

    Exclusive because the commonest numbers worth following are timings, and a
    timing taken while something else ran is not a timing. The numbers need not
    be times at all -- an error, a residual, a score, a size -- in which case
    `exclusive = False`, or `track`, says so.
    """
    return entry( name, tags, **{ "bulk": False, "keep": True, "exclusive": True, **kw } )


def track( name, tags = None, /, **kw ):
    """Numbers to follow over time that do not need the machine to themselves."""
    return entry( name, tags, **{ "bulk": False, "keep": True, **kw } )


def experiment( name, tags = None, /, **kw ):
    """It must be looked at. `latest/` is the path to open."""
    return entry( name, tags, **{ "bulk": False, "stable_path": True, **kw } )


# ── what a body can ask ──────────────────────────────────────────────────────

def out_dir( ) -> Path:
    """This run's own directory (./out outside errand, for an ad-hoc run)."""
    return Path( os.environ.get( "ERRAND_OUT_DIR", "out" ) )


def has_tag( expr: str ) -> bool:
    """Does the selected environment satisfy `expr`?

    Outside errand -- a file run by hand -- the answer is yes to everything: a
    file that silently disappears is worse than an import that fails loudly.
    """
    if not _tags and not os.environ.get( "ERRAND_TAGS" ):
        return True
    from .expr import matches
    return matches( expr, _current_tags( ) )


def tag( name: str, default = None ):
    """The value of a tag of the selected environment."""
    return _current_tags( ).get( name, default )


def _current_tags( ) -> dict:
    if _tags:
        return _tags
    raw = os.environ.get( "ERRAND_TAGS", "" )
    out = { }
    for item in filter( None, raw.split( "," ) ):
        k, _, v = item.partition( "=" )
        out[ k ] = v if v else True
    return out


def _as_list( tags ):
    if tags is None:
        return [ ]
    return [ tags ] if isinstance( tags, str ) else list( tags )


def resolve_params( params: dict, overrides: dict ) -> dict:
    """Parameter values for one run: an override if given, else the default."""
    out = { }
    for name, p in params.items():
        raw = overrides.get( name )
        if raw is None:
            out[ name ] = p.default
            continue
        try:
            out[ name ] = raw if isinstance( raw, p.ptype ) else p.ptype( raw )
        except ( TypeError, ValueError ):
            raise ValueError( f"--{name.replace( '_', '-' )}: cannot read {raw!r} "
                              f"as {p.ptype.__name__}" )
    return out
