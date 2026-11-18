"""`python <errand> -m errand.agents.ops session '<request>'`: the work, done where the environment is.

Started by an environment agent, in the environment's interpreter, by the side
that orchestrates ( `cli/drive.py` ). It decides nothing: it is told which
entries, which values, which cases, and

    prepares   resolves the targets, builds, collects, writes the plan    ( `cli/inside.prepare_here` )
    runs       each case it is given, under a claim on this machine       ( `cli/here.run_case` )

and says what came of each, as one line marked `MARK` among its output -- what
the orchestrating side reads, and does not show. Everything else it prints is
what a run prints, and is shown as it comes.

It takes its claims itself, on the machine it runs on: that is the queue the
work shares, and a run whose client went away ( a closed laptop ) goes on
under them.
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

MARK = "\x1eerrand-op "

# What a session is told of the command line: everything that decides what runs and how.
KNOWN = ( "pattern", "entry_tags", "from_default", "runner", "target_args", "jobs", "no_queue", "cpus", "ram",
          "gpus", "ranks", "exclusive", "label", "log", "quiet", "keep_out", "out", "mem", "from_plan", "phase",
          "grid" )


def say( what: dict ):
    sys.stdout.flush()
    sys.stdout.write( MARK + json.dumps( what ) + "\n" )
    sys.stdout.flush()


def _entry( e, root ) -> dict:
    from .. import results as R
    return { "name": e.name, "file": str( R._under( e.file, root ) ), "line": e.line }


def session( req: dict ) -> int:
    from .. import __version__, config, queue
    from ..cli.here import Ask, Report, run_case
    from ..cli.inside import combo_banner, prepare_here
    from ..cli.project import output_tree
    from ..cli.style import dim, head
    from .. import results as R

    import faulthandler
    # A crash in an extension says where it was, on stderr: kept in the run's `stderr.txt`, and said
    # by the side that drives this session ( `cli.sessions.follow` ).
    faulthandler.enable( all_threads = True )
    root = Path( req[ "root" ] )
    try:
        os.chdir( root )
    except FileNotFoundError:
        # Seen from a container that does not mount the file system the project is on
        print( f"errand: the project root {root} is not seen here"
               + ( ": mount it in the image ( `flags = [ \"--bind\", ... ]` on the container layer )"
                   if os.environ.get( "APPTAINER_CONTAINER" ) or os.environ.get( "SINGULARITY_CONTAINER" ) else "" ),
               file = sys.stderr )
        return 1
    config.load( root, warn = lambda m: print( dim( f"  warning: {m}" ), file = sys.stderr ) )
    known = SimpleNamespace( **{ **{ k: None for k in KNOWN }, **req[ "known" ] } )
    out_root = output_tree( root, known )
    env = config.envs.get( req[ "env" ] ) or config.Env.make( req[ "env" ], [ ], { } )
    tags = dict( req[ "tags" ] )
    report = Report()

    rc, p = prepare_here( env, tags, req[ "verb" ], known, root = root, out_root = out_root,
                          report = report )
    say( { "op": "prepared", "rc": rc, "plan": p.plan if p else None,
           "combos": [ list( c ) for c in p.combos ] if p else [ ],
           "entries": [ _entry( e, root ) for e in p.selected ] if p else [ ],
           "broken": [ [ str( path ), why ] for path, why, _ in report.broken ] } )
    if p is None or req.get( "prepare_only" ) or p.phase == "prepare":
        return rc

    ask = Ask( known )
    blocks = bool( req.get( "blocks" ) )
    cases = req.get( "cases" )
    cases = [ tuple( c ) for c in cases ] if cases is not None else [
        ( i, j ) for i in range( len( p.combos ) ) for j in range( len( p.selected ) ) ]
    where = R.place( env.name )
    for i, j in cases:
        varied, values = p.combos[ i ]
        e = p.selected[ j ]
        if not blocks and j == 0:
            banner = combo_banner( i, len( p.combos ), varied )
            if banner:
                print( banner, flush = True )
            if not ask.quiet:
                n = len( p.selected )
                print( head( f"\n{'=' * 10} {n} entr{'y' if n == 1 else 'ies'}  {env.name}  {where} {'=' * 10}" ),
                       flush = True )
        # The case under way, for the side that drives: what to name if this process dies in it.
        say( { "op": "start", "case": [ i, j ], "entry": _entry( e, root ) } )
        kept, buf = sys.stdout, io.StringIO()
        if blocks:
            # Several sessions at once: each case is said as one block, or nobody could read them.
            sys.stdout = buf
        try:
            asked = { **e.resources, **ask.resources }
            # In an allocation errand holds, what says nothing of its needs takes all of it ( ADR 0009 ):
            # what runs there is exclusive by default, and shares only what it declares.
            whole = bool( queue.in_allocation() ) and not asked
            with queue.claim( asked,
                              exclusive = ask.exclusive or whole,
                              label = ask.label or f"{e.file.name}::{e.name}", enabled = not known.no_queue,
                              echo = lambda m: print( dim( m ), flush = True ) ) as granted:
                handed = { **granted.env(), **granted.handed_down() } if granted else { }
                devices = granted.devices if granted and granted.devices and granted.path else None
                status, error, hint = run_case( e, p.modules, root = root, out_root = out_root,
                                                overrides = values, env_name = env.name, tags = tags,
                                                version = __version__, selectors = p.selectors, ask = ask,
                                                handed = handed, devices = devices, marks = True )
        finally:
            sys.stdout = kept
        say( { "op": "ran", "case": [ i, j ], "entry": _entry( e, root ), "status": status,
               "error": error, "hint": hint, "output": buf.getvalue() if blocks else None } )
    say( { "op": "done" } )
    return 0


def main( argv = None ) -> int:
    argv = list( sys.argv[ 1 : ] if argv is None else argv )
    if len( argv ) != 2 or argv[ 0 ] != "session":
        print( "usage: python -m errand.agents.ops session REQUEST", file = sys.stderr )
        return 2
    return session( json.loads( argv[ 1 ] ) )


if __name__ == "__main__":
    sys.exit( main() )
