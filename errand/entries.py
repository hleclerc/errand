"""Declaring work: `entry`, and the four names it goes by ( `test`, `bench`, `track`, `experiment` ).

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

# What an entry can say of how it runs. Only `ranks`: the body runs in that many processes, under
# the MPI launcher of the place ( `errand.mpi` ), and takes as many cores -- something a body
# written for MPI cannot do without. What a run asks of the machine otherwise ( `--cpus`, `--gpus`,
# `-x` ) belongs to the command, not to the entry ( ADR 0011 ).
RESOURCES = ( "ranks", )

# What entries used to say of themselves, and where it went: an entry declaring one is told.
GONE = {
    "bulk"       : "a bare `errand run` runs `errand.default_run`",
    "keep"       : "every recorded result is kept and comparable",
    "exclusive"  : "`-x` on the command line",
    "stable_path": "`latest/` is always there, beside the stamped runs",
    "cpus"       : "`--cpus` on the command line",
    "ram"        : "`--ram` on the command line",
    "gpus"       : "`--gpus` on the command line",
}


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
    # The runner ( None: this file's own two-phase guard, run by the core ) and
    # the opaque key it uses to find this entry again when asked to run it.
    runner = None
    key      = None
    # A runner's `::name`, handed to its tool as it was typed ( ADR 0011 ): None for errand's own.
    selector = None

    def __init__( self, name, tags, params, resources, file, line, module ):
        self.name      = name
        self.tags      = tags          # list[str], free-form, filtered by -e
        self.params    = params        # dict[str, Param]
        self.resources = resources     # dict[str, int|str]
        self.file      = Path( file )
        self.line      = line
        self.module    = module

    @property
    def site( self ):
        """Identity: where it is written, not what it is called."""
        return ( self.module, self.line )

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
    parameter, since a parameter is recognized by BEING a `Param`. The only other
    keyword is `ranks`.
    """
    if "tags" in kw:
        if tags is not None:
            raise TypeError( f"entry( {name!r} ): tags given twice" )
        tags = kw.pop( "tags" )

    params  = { k: v for k, v in kw.items() if isinstance( v, Param ) }
    rest    = { k: v for k, v in kw.items() if not isinstance( v, Param ) }

    resources = { }
    for k, v in rest.items():
        if k in RESOURCES:
            resources[ k ] = v
        elif k in GONE:
            raise TypeError( f"entry( {name!r} ): {k} = … is no longer an entry's to say: {GONE[ k ]}" )
        else:
            raise TypeError(
                f"entry( {name!r} ): unknown keyword {k!r}. A parameter must be a Param "
                f"( {k} = Param( {v!r} ) ); the only other keyword is {', '.join( RESOURCES )}."
            )

    frame  = sys._getframe( 2 if _is_preset( ) else 1 )
    line   = frame.f_lineno
    module = frame.f_globals.get( "__name__" )

    if phase == COLLECT:
        collected.append( Entry( name, _as_list( tags ), params, resources,
                                 frame.f_code.co_filename, line, module ) )
        return False

    if target is None or ( module, line ) != target.site:
        return False

    return Args( results = results, out_dir = out_dir( ), **dict( _resolved ) )


def _is_preset( ):
    """True when `entry` was reached through test/bench/track/experiment.

    The call site has to be the user's line, not the preset's, so the frame to
    read is one further up when a preset is in between.
    """
    return sys._getframe( 2 ).f_globals.get( "__name__" ) == __name__


# What the work is, said in the file for whoever reads it: the four are the same declaration.
# What used to differ between them ( taking the machine, being in a bare run ) is the command's.

def test( name, tags = None, /, **kw ):
    """It must pass."""
    return entry( name, tags, **kw )


def bench( name, tags = None, /, **kw ):
    """Numbers to follow. Measured alone when the command says so ( `-x` )."""
    return entry( name, tags, **kw )


def track( name, tags = None, /, **kw ):
    """Numbers to follow over time."""
    return entry( name, tags, **kw )


def experiment( name, tags = None, /, **kw ):
    """It must be looked at: `latest/` is the path to open."""
    return entry( name, tags, **kw )


# ── what a body can ask ──────────────────────────────────────────────────────

def out_dir( ) -> Path:
    """This run's own directory (./out outside errand, for an ad-hoc run)."""
    return Path( os.environ.get( "ERRAND_OUT_DIR", "out" ) )


def cache_dir( zone: str ) -> Path:
    """Where a cache zone ( ADR 0012 ) is for this run: `zone`, a path from the project root
    ( `"/data-cache"` ), joined to the root -- the nearest directory above the current one that holds a
    project file ( `errand-*.py` ). Created if missing. The same directory outside errand, run by hand.
    A library takes it as an argument: errand sets no variable for it."""
    rel = zone.strip( "/" )
    if not rel or ".." in rel.split( "/" ) or any( c in rel for c in "*?[" ):
        raise ValueError( f"cache_dir( {zone!r} ): a path from the project root, as the zone names it" )
    here = Path.cwd().resolve()
    for d in ( here, *here.parents ):
        if any( p.is_file() for p in d.glob( "errand-*.py" ) ):
            out = d / rel
            out.mkdir( parents = True, exist_ok = True )
            return out
    raise FileNotFoundError( f"cache_dir( {zone!r} ): no project file ( errand-*.py ) in {here} or above" )


def download( url: str, sha256: str | None = None, name: str | None = None, **kw ) -> Path:
    """The path of the file at `url`, downloaded into the project's cache ( `errand-cache/downloads/` )
    if it is not there yet ( ADR 0013 ). `sha256` is checked when given, never required. With no
    route to the URL, a run that errand follows asks up the chain ( the host over there, then here )."""
    from .downloads import download as _download      # urllib: only when a download is asked for
    return _download( url, sha256, name, **kw )


class Rerun( Exception ):
    """Raised by `require` when two runs that grow their claims wait for each other: errand stops the
    younger, and runs it again, once, with what it requires up front ( ADR 0014 )."""


_DEVICE_VARS = ( "CUDA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES" )
_said_allocation = False


def require( gpus: int | None = None, gpu_ram: str | int | None = None, ram: str | int | None = None,
             cpus: int | None = None, exclusive: bool = False ) -> list:
    """Ask the machine for more than the run was started with, and wait until it is given ( ADR 0014 ).
    Call it early, before what it protects is allocated: for Jax, before `import jax`.

        errand.require( gpus = 1, gpu_ram = "75%" )

    `gpu_ram` is what the run takes on each of its cards: a size ( `"40G"` ) or a share ( `"75%"` );
    `gpus` without it takes cards whole. It only adds to the run's claim. Once granted, it sets
    `CUDA_VISIBLE_DEVICES` ( and the HIP / ROCR ones ) in this process, and returns the cards.
    errand remembers it, and claims it up front the next time.

    Outside errand, with `--no-queue`, or in an allocation of Slurm, PBS… it does nothing and returns
    `[ ]` at once."""
    needs = { k: v for k, v in ( ( "gpus", gpus ), ( "gpu_ram", gpu_ram ), ( "ram", ram ), ( "cpus", cpus ) )
              if v is not None }
    path = os.environ.get( "ERRAND_CLAIM_FILE" )
    if not path:
        _check_allocation( needs )
        return [ ]
    from . import queue                     # the standard library, and only when errand runs this
    got = queue.grow( path, needs, exclusive = exclusive,
                      echo = lambda m: print( m.strip(), file = sys.stderr, flush = True ) )
    if got:
        listed = ",".join( str( d ) for d in got )
        os.environ.update( { k: listed for k in _DEVICE_VARS } )
        os.environ[ queue.CLAIM ] = listed
    return got


def _check_allocation( needs: dict ):
    """In somebody else's allocation, said once: what it has is less than what is asked."""
    global _said_allocation
    if _said_allocation or not any( os.environ.get( v ) for v in ( "SLURM_JOB_ID", "PBS_JOBID", "OAR_JOB_ID",
                                                                   "LSB_JOBID", "FLUX_JOB_ID" ) ):
        return
    _said_allocation = True
    visible = os.environ.get( "CUDA_VISIBLE_DEVICES" )
    if needs.get( "gpus" ) and visible is not None and len( [ v for v in visible.split( "," ) if v.strip() ] ) < int( needs[ "gpus" ] ):
        print( f"errand.require: {needs[ 'gpus' ]} gpus asked, the allocation has {visible!r}", file = sys.stderr )


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
