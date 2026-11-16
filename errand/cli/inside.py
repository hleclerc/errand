"""One environment, from inside it: the plan it writes, and preparing then running what it holds.
"""
from __future__ import annotations

import os

from .. import config, discovery, layers as L, results as R
from .style import bad, dim, head
from .project import _put_src_on_path
from .grid import describe_grid, expand
from .here import aggregate_needs, Ask, run_entries
from .parallel import job_count, run_in_processes
from .plans import plan_of, plan_path, read_plan
from .listing import prepare_runners, print_entries, say_broken
from .parsing import split_args
from .help import _short, _suggest


def make_plan( env, tags, entries, combos, *, root, out_root, asked = None ) -> dict:
    """What this command is about to do here: the entries, what they ask of a
    machine, and the directories they will write. Written before anything
    runs, and read by whoever has to know before the fact -- the side that
    fetches back, `status`, the screen, and an allocation sized from it."""
    return {
        "env"    : env.name,
        "stamp"  : R.stamp(),
        "needs"  : aggregate_needs( entries, asked ),
        "entries": [ { "name": e.name, "file": str( R._under( e.file, root ) ), "line": e.line,
                       "runner": e.runner.name if e.runner is not None else "errand" }
                     for e in entries ],
        "runs"   : plan_of( [ ( env, tags ) ], entries, combos, root = root, out_root = out_root ),
    }


class Prepared:
    """What preparing found: the entries, their modules and selectors, the grid, the plan."""

    def __init__( self, **kw ):
        self.__dict__.update( kw )


def prepare_here( env, tags, verb, known, *, root, out_root, report ):
    """Resolve, build and collect, in this process, and write the plan: -> ( rc, Prepared or None ).
    None with rc 0 is `list`, which has said what it found and is done."""
    import json

    _put_src_on_path( root )
    # What a runner starts before it has a run to start it for ( listing a crate's targets ).
    for r in ( config.runners or { } ).values():
        r.place_tools = dict( env.tools )

    try:
        selected, modules, selectors = discovery.select(
            known.pattern, root, entry_tags = known.entry_tags, exclude = config.settings.exclude,
            runners = config.runners, force = known.runner,
        )
    except ValueError as err:
        print( bad( str( err ) ) )
        return 1, None
    report.broken += [ b for b in discovery.broken if b not in report.broken ]

    # The parameters only exist once we know which entries matched: they are
    # read out of the target's arguments, and the rest is handed to it.
    declared = { }
    for e in selected:
        declared.update( e.params )
    try:
        raw_values, raw = split_args( known.target_args, declared )
    except ValueError as err:
        print( bad( str( err ) ) )
        return 1, None

    if verb == "list":
        print_entries( selected )
        say_broken()
        return ( 1 if discovery.broken else 0 ), None

    try:
        combos = expand( { n: raw_values.get( n ) for n in declared }, declared, raw,
                         sep = getattr( known, "grid", None ) )
        how_many = job_count( known.jobs )
    except ValueError as err:
        print( bad( str( err ) ) )
        return 1, None

    if not selected:
        print( bad( f"nothing matched {known.pattern!r}" ) )
        if discovery.broken:
            # "nothing to run" when in fact nothing could be READ is the kind of
            # answer that sends somebody looking in the wrong place.
            say_broken()
            return 1, None
        _suggest( root )
        return 1, None

    ask = Ask( known )
    plan = make_plan( env, tags, selected, combos, root = root, out_root = out_root,
                      asked = { **ask.resources, **( { "exclusive": True } if ask.exclusive else { } ) } )
    where = plan_path( root, env.name )
    from_plan = bool( getattr( known, "from_plan", False ) )
    if from_plan:
        # The run phase of two: what is here now must be what was prepared,
        # sized and announced. Otherwise the sources moved in between, or the
        # filesystem the two phases share is not shared.
        # Prepared on another machine, the plan came with the request ( ADR 0011 ), and is kept here too.
        before = getattr( known, "plan", None ) or read_plan( root, env.name )
        if getattr( known, "plan", None ):
            where.parent.mkdir( parents = True, exist_ok = True )
            where.write_text( json.dumps( known.plan, indent = 1 ) )
        if before is None or before[ "entries" ] != plan[ "entries" ] or before[ "runs" ] != plan[ "runs" ]:
            print( bad( f"  {env.name}: what is here is not what was prepared "
                        f"( {_short( where, root )} ) -- the sources changed between the two phases, "
                        f"or the root is not on a filesystem both of them see" ) )
            return 1, None
    else:
        where.parent.mkdir( parents = True, exist_ok = True )
        where.write_text( json.dumps( plan, indent = 1 ) )

    # Running here rather than in a child, either because nothing needed
    # wrapping or because the wrapping already happened and this IS the
    # child. Either way no command is about to be rewritten, so what the
    # layers meant to put in the environment has to be put there directly --
    # and `Vars` is the only kind that can act without a new process at all.
    phase = getattr( known, "phase", None ) or "run"
    os.environ.update( L.compose( [ l for l in env.stack_for( phase ) if isinstance( l, L.Vars ) ],
                                  L.Command( [ "python" ] ),
                                  L.Context( root = root, tags = tags ) ).env )

    if not from_plan:
        # Build once, here, before anything runs: a suite is built once and not
        # once per file, and under `-j` several children would otherwise write
        # the same binary at the same time.
        trouble = prepare_runners( selected, root = root, out_root = out_root, tags = tags,
                                   env_name = env.name )
        if trouble:
            for who, why in trouble:
                print( bad( f"  {who}: {why}" ) )
            return 1, None

    if len( combos ) > 1 and not from_plan:
        print( dim( f"  {describe_grid( combos )}" ), flush = True )

    if phase == "prepare":
        print( dim( f"  prepared {len( selected )} entr{'y' if len( selected ) == 1 else 'ies'} "
                    f"in {env.name}: {_short( where, root )}" ), flush = True )
    return 0, Prepared( selected = selected, modules = modules, selectors = selectors, combos = combos,
                        plan = plan, how_many = how_many, phase = phase )


def combo_banner( i, n, varied ) -> str | None:
    if not varied:
        return None
    shown = ", ".join( f"{k.replace( '_', '-' )}={v}" for k, v in varied.items() )
    return head( f"\n--- {i + 1}/{n}  {shown} ---" )


def here( env, tags, verb, rest, known, *, root, out_root, report, inside ):
    """Resolve, build, collect and run, in this process: the environment is the
    one this process is in -- entered by a dispatch, or one that wraps nothing."""
    from .. import __version__

    rc, p = prepare_here( env, tags, verb, known, root = root, out_root = out_root,
                          report = report )
    if p is None:
        return rc
    if p.phase == "prepare":
        return 0

    ask = Ask( known )
    runs = len( p.selected ) * len( p.combos )
    if p.how_many > 1 and runs == 1:
        # One run: `-j N` is its tool's parallelism, when its runner says how ( ADR 0011 ), and the
        # claim asks for as many cpus. Otherwise there is nothing to run at the same time.
        runner = p.selected[ 0 ].runner
        if runner is not None and runner.jobs:
            ask.jobs = p.how_many
            ask.resources.setdefault( "cpus", p.how_many )
        else:
            print( dim( f"  -j {p.how_many}: a single run, and {runner.name if runner else 'an entry'} "
                        f"takes no parallelism of its own -- it runs alone" ), flush = True )
    elif p.how_many > 1:
        run_in_processes( p.selected, p.combos, root = root, out_root = out_root, env = env,
                          tags = tags, how_many = p.how_many, report = report,
                          out_prefix = R.place( env.name ), flags = Ask.flags( known ) )
        return 0

    for i, ( varied, values ) in enumerate( p.combos ):
        banner = combo_banner( i, len( p.combos ), varied )
        if banner:
            print( banner, flush = True )
        run_entries( p.selected, p.modules, root = root, out_root = out_root,
                     overrides = values, env_name = env.name, tags = tags,
                     version = __version__, report = report,
                     queued = not known.no_queue, selectors = p.selectors, ask = ask )
    return 0
