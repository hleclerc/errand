"""`errand-*.py`: what a project declares, and how an environment is chosen.

Ordinary Python, loaded once BY PATH -- never as a module named `errand`, so a
file sitting at the root of a project cannot shadow the package it imports
from. There is no entry point to call and nothing to return: `configure`,
`envs` and `runners` hold what they are given.
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
CONFIG_FILE = "errand-project.py"      # the name `errand init` writes: the one that is versioned
ENVS_FILE   = "errand-envs.py"      # where it runs: versioned when it holds no machine name
VARS_FILE   = "errand-vars.py"      # what only this machine knows ( hosts, paths ): never versioned, read first


def config_files( directory: Path ) -> list:
    """The project files in `directory`, in the order they are read: `errand-vars.py` first, so that
    the files declaring environments can ask it for the hosts and paths of this machine."""
    return sorted( ( p for p in directory.glob( CONFIG_GLOB ) if p.is_file() ),
                   key = lambda p: ( p.name != VARS_FILE, p.name ) )


def config_in( directory: Path ):
    """The first project file in `directory`, or None: is this a project root?"""
    files = config_files( directory )
    return files[ 0 ] if files else None


class Env:
    """Where work runs: a stack of layers, and the tags saying what it is.

        errand.envs[ "gpu" ] = errand.Env( [ errand.Apptainer( ... ) ], driver = "cuda" )

    The preparation ( setting up, building, writing the plan ) goes through the same layers, unless
    `prepare` gives it its own: another allocation, another machine. Copy what both share:

        base = [ errand.Ssh( host = "login.hpc", root = "/scratch/me/proj" ) ]
        errand.Env( base + [ errand.Slurm( gpus = 1 ) ], prepare = base + [ errand.Slurm( cpus = 16 ) ] )

    `tools` names what the runners start in this environment, where its usual name is wrong:
    `tools = { "python": "python3.12", "cmake": "/opt/cmake/bin/cmake" }`. A runner's command and a
    build line write `{python}`, `{cmake}`; a target whose first word is a tool named here is run
    as named.

    `needs` is what every run in it takes of the machine, known before anything starts ( ADR 0014 ):
    `needs = { "gpus": 1, "gpu_ram": "75%", "ram": "16G" }` for Jax on a GPU, which takes 75 % of
    its card at its first array. The command line ( `--gpus`, `--gpu-ram`, `-x` ) is over it, and
    `errand.require` adds to both.

    The name is the key it is stored under; `Env` does not take one.
    """

    NEEDS = ( "cpus", "ram", "gpus", "gpu_ram", "exclusive" )

    def __init__( self, stack = ( ), prepare = None, tools = None, needs = None, **tags ):
        for k, v in tags.items():
            # A comma on the command line is several values: a tag value holding
            # one could never be asked for.
            if isinstance( v, str ) and "," in v:
                raise ValueError( f"tag {k} = {v!r}: a tag value cannot hold a comma, which means "
                                  f"several values on the command line" )
        self.name    = ""
        self.stack   = list( stack )
        self.prepare = None if prepare is None else list( prepare )
        self.tags    = dict( tags )
        self.tools   = dict( tools or { } )
        self.needs   = dict( needs or { } )
        unknown = [ k for k in self.needs if k not in self.NEEDS ]
        if unknown:
            raise ValueError( f"needs[ {unknown[ 0 ]!r} ]: one of {', '.join( self.NEEDS )}" )
        from . import queue
        queue.normalize( self.needs )           # a size or a share that does not read fails now, not on a run
        for name, argv in self.tools.items():
            if not isinstance( argv, ( str, list, tuple ) ) or not argv:
                raise ValueError( f"tools[ {name!r} ]: a command, as a string or a list of words" )
        for layers in ( self.stack, self.prepare ):
            for i, layer in enumerate( layers or ( ) ):
                # A `WindowsBox` is reached by the `Ssh` before it: its own copy knows which.
                if getattr( layer, "is_box", False ):
                    import dataclasses
                    layers[ i ] = layer = dataclasses.replace( layer )
                    layer.via = layers[ 0 ] if i == 1 and isinstance( layers[ 0 ], L.Ssh ) else None
        # Checked now, rather than on the day somebody first runs in this environment.
        check_stack( self.stack, "run" )
        if self.prepare is not None:
            check_stack( self.prepare, "prepare" )
            # Another machine to prepare on is an `Ssh` of its own: what it builds is carried to the
            # run's copy ( ADR 0011 ). A machine errand boots is one place for both phases.
            a, b = L.vm_of( self.stack ), L.vm_of( self.prepare )
            if not ( a is b or a == b ):
                what = lambda l: l.describe() if l is not None else "no machine to boot"
                raise ValueError( f"`prepare` boots {what( b )}, the run {what( a )}: a machine errand boots "
                                  f"is the same for both phases -- copy the first layer" )

    # -- the stack of one phase ----------------------------------------------

    def stack_for( self, phase: str ) -> list:
        """The layers `phase` goes through: `prepare`'s for the preparation when it was given."""
        if phase not in PHASES:
            raise ValueError( f"phase {phase!r}: one of {', '.join( PHASES )}" )
        return list( self.prepare if phase == "prepare" and self.prepare is not None else self.stack )

    def prepares_elsewhere( self ) -> bool:
        """Is the preparation on another machine than the run ( another `Ssh`, or one and not the other )?
        Then what it builds is carried to the run's copy."""
        if self.prepare is None:
            return False
        a, b = L.ssh_of( self.stack ), L.ssh_of( self.prepare )
        return not ( a is b or a == b )

    def places( self ):
        """One environment per machine it uses, each with that machine's layers: what `setup` builds, place
        by place. Just this one when both phases are on one machine."""
        if not self.prepares_elsewhere():
            return [ self ]
        return [ Env.make( self.name, layers, self.tags, tools = self.tools, needs = self.needs )
                 for layers in ( self.stack, self.prepare ) ]

    def layers( self ):
        """( index, layer ) for every layer of either phase, once each: what `setup` builds and keeps
        current. The run's first, in order, then what only the preparation has."""
        out = list( enumerate( self.stack ) )
        seen = { id( l ) for l in self.stack }
        for layer in self.prepare or ( ):
            if id( layer ) not in seen:
                seen.add( id( layer ) )
                out.append( ( len( out ), layer ) )
        return out

    def single_pass( self ) -> bool:
        """Can preparing and running be one process? Only when both phases go
        through the same layers and nothing has to be sized from the plan -- a
        watched scheduler is sized from its declaration, and is one job."""
        prepare, run = self.stack_for( "prepare" ), self.stack_for( "run" )
        same = len( prepare ) == len( run ) and all( a is b for a, b in zip( prepare, run ) )
        return same and not any( L.is_scheduler( l ) and not getattr( l, "watch", None ) for l in run )

    @classmethod
    def make( cls, name: str, stack = ( ), tags = None, prepare = None, tools = None, needs = None ):
        e = cls( stack, prepare, tools, needs, **( tags or { } ) )
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

    @property
    def vm( self ):
        return L.vm_of( self.stack )

    @property
    def missing( self ):
        """The `Missing` layer that says why this environment cannot be reached from here, or None."""
        return L.missing_of( [ l for _, l in self.layers() ] )

    def describe( self ):
        def arrow( layers ):
            return " -> ".join( l.describe() for l in layers ) or "this interpreter"
        if self.prepare is None:
            return arrow( self.stack )
        return f"{arrow( self.stack )}  ( prepared: {arrow( self.prepare )} )"

    def wraps_anything( self ):
        """Does reaching this environment mean leaving this process?"""
        return any( not isinstance( l, L.Vars ) for _, l in self.layers() )


# What a command goes through: preparing ( setting up, building, writing the plan ), then running.
PHASES = ( "prepare", "run" )


def check_stack( stack, phase = "run" ):
    """What a stack must look like."""
    where = f" ( in `prepare` )" if phase == "prepare" else ""
    for i, layer in enumerate( stack ):
        if isinstance( layer, L.Ssh ) and i:
            raise ValueError( "Ssh must be the first layer" + where )
        # A machine errand boots is reached the way another machine is, and is
        # first for the same reason -- or right after the `Ssh` that leads to
        # the machine that boots it.
        if getattr( layer, "is_vm", False ) and i and not ( i == 1 and isinstance( stack[ 0 ], L.Ssh ) ):
            raise ValueError( f"{type( layer ).__name__} must be the first layer, or follow its Ssh" + where )
    for layer in stack:
        # An image left for something to fill in ( a package that completes the layers its users give ) and never filled.
        if isinstance( layer, L.Container ) and not getattr( layer, "image", "x" ):
            raise ValueError( f"{type( layer ).__name__}( image = ... ) is empty: name the image" )
        if isinstance( layer, L.Micromamba ) and not layer.name:
            raise ValueError( f"{type( layer ).__name__}( name = ... ) is empty: name the environment" )
    schedulers = [ l for l in stack if L.is_scheduler( l ) ]
    if len( schedulers ) > 1:
        hint = ( "one allocation per list" if phase == "prepare" else
                 "to prepare in another allocation, give it its own layers: Env( [ ... ], prepare = [ ... ] )" )
        raise ValueError( f"{len( schedulers )} schedulers{where} "
                          f"( {', '.join( l.describe() for l in schedulers )} ): {hint}" )


@dataclass
class Settings:
    src    : list = field( default_factory = list )
    # Directories discovery must not walk into: vendored code, fixtures, a copy
    # of something that would be imported and should not be.
    exclude: list = field( default_factory = list )
    # Where a runner's build goes, one directory per environment under it
    # ( `build/<env>/` ): two environments never share a binary, so a number is
    # never measured on a binary built for somewhere else.
    build  : str = "build"
    # Everything errand writes for this project, in one visible directory:
    #     runs/     the records of the runs, and what they brought back
    #     builds/   what errand built ( Windows images ) and its records of it
    #     state/    its own bookkeeping: plans, history, launches, output kept for attach
    # Relative to the project's root, or absolute. `ERRAND_OUTPUTS_DIR` overrides
    # it for one machine; over there, `Ssh( errand_outputs_directory = ... )`.
    outputs_directory: str = "errand-outputs"
    # What errand builds ( `builds/` above ) somewhere else: another disk, or one
    # directory several projects share. Relative to the root, or absolute -- the
    # same path on every machine.
    builds_directory : str | None = None
    # Where a run writes in the project's copy over there ( ADR 0006 ). Elsewhere the copy holds only
    # what errand sends, and a change is said, then put back. `{ "results": "back" }`: path patterns
    # as a sync reads them ( `results`, a name anywhere; `/results`, at the root ), each a kind:
    #     back    written over there, brought back here
    #     build   built over there ( what a layer builds, `kept()`, is one already )
    #     cache   added to on both sides, never replaced nor deleted ( ADR 0012 ): downloaded data,
    #             memoized results. `errand.cache_dir( "/data-cache" )` gives a run its path.
    zones            : dict = field( default_factory = dict )
    # What a run's `errand.require` asked, kept by machine, environment and target
    # ( `errand-outputs/state/needs.json` ) and claimed up front the next time ( ADR 0014 ).
    # Off: every run asks again, from what it is told and what its code requires.
    remember_needs   : bool = False
    # How `errand run` draws a case's output ( ADR 0016 ): behind a `bar` ( │ stdout, ┃ stderr ), behind
    # `spaces`, or `off`; `plain` is `off` without colors. `$ERRAND_OUTPUT` and `--plain` win.
    output           : str = "bar"
    # Each run's page opened in the browser as it starts ( `errand run --open`, ADR 0017 §5 ).
    open             : bool = False


class Envs( dict ):
    """`errand.envs[ "name" ] = errand.Env( ... )`: the key becomes the environment's name."""

    def __setitem__( self, name, env ):
        if not isinstance( env, Env ):
            raise TypeError( f"envs[ {name!r} ] must be an errand.Env, not {type( env ).__name__}" )
        if "," in name:
            raise ValueError( f"envs[ {name!r} ]: an environment name cannot hold a comma, which "
                              f"means several environments on the command line" )
        env.name = name
        super().__setitem__( name, env )


settings  = Settings()
envs      = Envs()
# What declares environments BEFORE the project does: callables taking the project root, which fill
# `envs` like a project file would. A program that drives errand appends to it; an installed package
# declares one under the entry point group `errand.envs`. They run after `errand-vars.py`, so they
# can read this machine's values ( `errand.value` ), and before the project's other files, which
# can then redefine an environment they declared, under the same name, or change it in place.
providers = [ ]
PROVIDERS_GROUP = "errand.envs"
_provided = set( )          # id() of the environments a provider declared: never the default ( `default` )
# What runs what: name -> runner, filled with the ones that come with errand,
# which a project edits in place ( `errand.runners[ "bench" ] = …`, `del`,
# `.replace` ).
runners   = None            # a runner.Runners, filled below and by `reset`


OUTPUTS_ENV = "ERRAND_OUTPUTS_DIR"
DEFAULT_OUTPUTS = "errand-outputs"
LEGACY = ".errand"          # before errand-outputs/: moved on first sight ( `migrate` )


def outputs( root: Path ) -> Path:
    """Everything errand writes for the project at `root` ( `Settings.outputs_directory` )."""
    import os
    where = Path( os.environ.get( OUTPUTS_ENV ) or settings.outputs_directory ).expanduser()
    return where if where.is_absolute() else Path( root ) / where


CACHES_ENV = "ERRAND_CACHES"


def caches( root: Path ) -> Path:
    """Where a library run under errand puts its caches, one subdirectory each ( `$ERRAND_CACHES/loom` ): the
    outputs' `caches/`, made if missing and tagged as a cache ( ADR 0019 ). Each machine keeps its own."""
    from .sync import CACHEDIR_TAG, CACHEDIR_SIGNATURE
    out = outputs( root ) / "caches"
    tag = out / CACHEDIR_TAG
    if not tag.exists():
        try:
            out.mkdir( parents = True, exist_ok = True )
            tag.write_bytes( CACHEDIR_SIGNATURE + b"\n# errand: the caches of the libraries its runs use ( ADR 0019 )\n" )
        except OSError:
            pass
    return out


def outputs_rel( root: Path ) -> str:
    """The same, as the project's copy on another machine names it: relative to its root. Put
    outside the project here, it is the default name over there."""
    import os
    rel = os.path.relpath( outputs( root ), root )
    return DEFAULT_OUTPUTS if rel.startswith( ".." ) or os.path.isabs( rel ) else rel.replace( os.sep, "/" )


def runs( root: Path ) -> Path:
    return outputs( root ) / "runs"


def state( root: Path ) -> Path:
    """errand's own bookkeeping for this project: `errand-outputs/state/`."""
    return outputs( root ) / "state"


def state_rel( root: Path ) -> str:
    """The same, relative to the root over there."""
    return f"{outputs_rel( root )}/state"


def builds_rel( root: Path ) -> str:
    """What errand builds, from the root of any machine: `errand-outputs/builds`, or
    `Settings.builds_directory`, which an absolute path names the same everywhere."""
    if settings.builds_directory:
        return str( Path( settings.builds_directory ).expanduser() )
    return f"{outputs_rel( root )}/builds"


def migrate( root: Path, echo = print ):
    """`.errand/` ( and the visible `runs/` of errand's records ) as they were before
    `errand-outputs/`: moved in, once, here. Over there, `MIGRATE_SH` does the same."""
    import os
    root = Path( root )
    old, new = root / LEGACY, outputs( root )
    if any( d.is_dir() and not ( d / "exit" ).exists() for d in ( old / "procs" ).glob( "*" ) ):
        return                                  # a session still writes there: later
    moves = [ ]
    if old.is_dir():
        for name, dest in ( ( "runs", "runs" ), ( "builds", "builds/records" ), ( "vm/windows", "builds/windows" ) ):
            moves.append( ( old / name, new / dest ) )
        for p in sorted( old.iterdir() ) if old.is_dir() else [ ]:
            if p.name not in ( "runs", "builds", "vm" ):
                moves.append( ( p, new / "state" / p.name ) )
    visible = root / "runs"
    if visible.is_dir() and not visible.is_symlink() and visible != new / "runs" and next( visible.rglob( "summary.yaml" ), None ) is not None:
        moves.append( ( visible, new / "runs" ) )
    moved = False
    for src, dest in moves:
        if src.exists() or src.is_symlink():
            _merge( src, dest )
            moved = True
    if moved and ( new / "runs" ).is_dir():
        from . import results
        for entry in ( new / "runs" ).iterdir():
            if entry.is_dir():
                results.refresh( entry )
    if old.is_dir():
        try:
            for d in sorted( old.rglob( "*" ), key = lambda p: -len( p.parts ) ):
                if d.is_dir():
                    d.rmdir()
            old.rmdir()
        except OSError:
            pass
    if moved:
        echo( f"  errand's files moved to {os.path.relpath( new, Path.cwd() )}/ ( runs, builds, state )" )


def _merge( src: Path, dest: Path ):
    """`src` into `dest`: moved whole when `dest` is not there, merged entry by entry otherwise --
    what is already at `dest` wins."""
    import shutil
    if not dest.exists() and not dest.is_symlink():
        dest.parent.mkdir( parents = True, exist_ok = True )
        shutil.move( str( src ), str( dest ) )
        return
    if src.is_dir() and not src.is_symlink() and dest.is_dir():
        for p in list( src.iterdir() ):
            _merge( p, dest / p.name )
        try:
            src.rmdir()
        except OSError:
            pass
    elif src.name in ( "summary.yaml", "latest" ):
        src.unlink()                    # made again from the runs: the summaries are rewritten


# Over there, from the project's copy: the same moves, in POSIX sh, at each arrival.
MIGRATE_SH = r"""
o="$1"
for p in .errand/procs/*/; do                   # a session still writes there: later
    [ -d "$p" ] && [ ! -f "$p/exit" ] && exit 0
done
if [ -d .errand ]; then
    mkdir -p "$o/state" "$o/builds"
    m() { if [ -e "$1" ] && [ ! -e "$2" ]; then mkdir -p "$( dirname "$2" )" && mv "$1" "$2"; fi; }
    m .errand/runs "$o/runs"
    m .errand/builds "$o/builds/records"
    m .errand/vm/windows "$o/builds/windows"
    for p in .errand/* .errand/.[!.]*; do
        [ -e "$p" ] || continue
        case "$p" in .errand/runs|.errand/builds|.errand/vm) ;; *) m "$p" "$o/state/${p#.errand/}" ;; esac
    done
    rmdir .errand/vm 2>/dev/null; rmdir .errand 2>/dev/null
fi
true
"""


_SAID = set()
RENAMED = { "out": "outputs_directory ( runs are in its runs/ )", "state": "outputs_directory" }


def configure( **kw ):
    """Project-wide settings. See `Settings`."""
    for k, v in kw.items():
        if k in RENAMED:
            # Read, said once, and left: what it named is errand-outputs/ now.
            if k not in _SAID:
                _SAID.add( k )
                print( f"  warning: configure( {k} = ... ) is ignored: see {RENAMED[ k ]}", file = sys.stderr )
            continue
        if not hasattr( settings, k ):
            raise TypeError( f"configure(): unknown setting {k!r}; "
                             f"expected one of { ', '.join( vars( settings ) ) }" )
        if k == "zones":
            _check_zones( v, "configure( zones = ... )" )
        if k == "output" and v not in ( "bar", "spaces", "off", "plain" ):
            raise ValueError( f"configure( output = {v!r} ): bar, spaces, off or plain" )
        setattr( settings, k, v )


def _check_zones( zones, who = "zones" ):
    kinds = ( "back", "build", "cache" )      # `errand`, errand's own outputs, is not declared
    if not isinstance( zones, dict ):
        raise TypeError( f"{who}: a dict, path -> kind ( {' or '.join( kinds )} ), "
                         f"not {type( zones ).__name__}" )
    for path, kind in zones.items():
        if kind not in kinds:
            raise ValueError( f"{who}: {path!r} is {kind!r}; a zone is {' or '.join( kinds )}" )
        if not isinstance( path, str ) or not path.strip( "/" ) or ".." in path.split( "/" ):
            raise ValueError( f"{who}: {path!r} is not a path in the project" )


def zones( env_name = None ) -> dict:
    """The project's zones ( ADR 0006 ): what its runners say their tools write ( `Pytest( zones = … )` ),
    then `configure( zones = ... )`, which has the last word on a path both name.

    A path may name the environment: `{env}`, its name, and `{build_dir}`, its build directory from the
    root ( `build/<env>` ) -- `{ "/{build_dir}/target/criterion": "back" }`. For one environment, that
    one's; without, every declared environment's: environments share one copy over there."""
    declared = { }
    for r in ( runners or { } ).values():
        declared.update( getattr( r, "zones", None ) or { } )
    declared.update( settings.zones )
    names = [ env_name ] if env_name else ( list( envs ) or [ "default" ] )
    out = { }
    for path, kind in declared.items():
        if "{env}" not in path and "{build_dir}" not in path:
            out[ path ] = kind
            continue
        for name in names:
            from .results import slug
            out[ path.replace( "{build_dir}", f"{settings.build.strip( '/' )}/{slug( name )}" )
                     .replace( "{env}", name ) ] = kind
    return out


def reset( ):
    global settings
    settings = Settings()
    sys.modules[ "errand" ].default_env = None
    sys.modules[ "errand" ].default_run = None
    envs.clear()
    _provided.clear()
    _default_runners()


def _default_runners( ):
    # The same dict throughout: `errand.runners` is handed out once.
    from .runner import Runners, defaults
    global runners
    if runners is None:
        runners = Runners()
    runners.clear()
    runners.update( defaults() )


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
        _provide( root, warn )
        _root_runners( root )
        return False
    package = _root_package( root )
    provided = False
    for path in files:
        if not provided and path.name != VARS_FILE:
            _provide( root, warn )           # after this machine's values, before the project's declarations
            provided = True
        spec = importlib.util.spec_from_file_location(
            f"{package}._errand_" + re.sub( r"\W", "_", path.stem ), path )
        module = importlib.util.module_from_spec( spec )
        spec.loader.exec_module( module )
        local.offer( module )
    if not provided:
        _provide( root, warn )
    _root_runners( root )
    return True


def _provide( root: Path, warn = None ):
    """Run the `providers`, then those installed packages declare ( `errand.envs` entry points ).
    One that fails is said and skipped: the environments the others declare stay usable."""
    say = warn or ( lambda text: print( f"errand: {text}", file = sys.stderr ) )
    found = list( providers )
    try:
        from importlib.metadata import entry_points
        installed = entry_points( group = PROVIDERS_GROUP )
    except Exception:                       # no metadata to read: nothing installed declares any
        installed = ( )
    for ep in installed:
        try:
            fn = ep.load()
        except Exception as err:
            say( f"the environments of `{ep.value}` ( entry point {PROVIDERS_GROUP} ) are not loaded: {err}" )
            continue
        if fn not in found:
            found.append( fn )
    for fn in found:
        try:
            before = set( map( id, envs.values() ) )
            fn( Path( root ) )
            _provided.update( id( e ) for e in envs.values() if id( e ) not in before )
        except Exception as err:
            say( f"`{getattr( fn, '__module__', '' )}.{getattr( fn, '__qualname__', fn )}` failed to declare its environments: {err}" )


def _root_package( root: Path ) -> str:
    """A private package whose directory is the root, freshly made: the project files are its
    modules, so that `from .helpers import X` reads `helpers.py` beside them ( nothing put on
    `sys.path`, where it could shadow a module of the same name )."""
    import hashlib, types
    name = "_errand_root_" + hashlib.sha1( str( Path( root ).resolve() ).encode() ).hexdigest()[ :12 ]
    for key in [ k for k in sys.modules if k == name or k.startswith( name + "." ) ]:
        del sys.modules[ key ]           # read again at each load, like the project files
    package = types.ModuleType( name )
    package.__path__ = [ str( root ) ]
    sys.modules[ name ] = package
    return name


def _root_runners( root: Path ):
    """What a runner's own relative paths -- `dirs`, `manifest` -- are relative to."""
    for r in runners.values():
        r.root = Path( root )


# ── choosing where to run ────────────────────────────────────────────────────

def tag_names( ) -> list:
    """Every tag name any environment mentions: one flag each."""
    seen = { }
    for e in envs.values():
        for name in e.tags:
            seen[ name ] = True
    return sorted( seen )


def default( ) -> Env:
    """The one `errand.default_env` names, else the first the project declared, else this interpreter. An environment a
    provider declared is never chosen by default ( a project can name one with `default_env`, or redefine it ): it is there
    for what asks for it."""
    named = sys.modules[ "errand" ].default_env
    if named is not None:
        if named not in envs:
            raise ValueError( f"errand.default_env = {named!r}, but no environment has that name; "
                              f"declared: { ', '.join( envs ) or 'none' }" )
        return envs[ named ]
    own = [ e for e in envs.values() if id( e ) not in _provided ]
    if own:
        return own[ 0 ]
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


_default_runners()
