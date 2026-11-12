"""`errand …`: parse, then hand the verb to whoever does it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import batch, config, history, layers as L, queue, setup, trace
from .style import bad, dim, warn
from .project import _from_root, _put_src_on_path, _tags_from_env, _targets, find_root, IN_ENV, output_tree
from .here import Ask, Report
from .parallel import run_one
from .there import go_there, run_there
from .batches import show_batches, submit, submit_run
from .listing import _epilogue, print_envs, print_queue
from .parsing import build_parser, KINDS, misplaced, own_part, split_target, split_verb, VERBS
from .help import print_help
from .inside import here


def main( argv = None ):
    from .. import __version__

    argv = list( sys.argv[ 1 : ] if argv is None else argv )

    # `--root` and `--out` are needed before the project's tags are known, so
    # this first reading takes errand's own part of the command leniently.
    pre, _ = build_parser().parse_known_args( own_part( build_parser(), argv, lenient = True ) )
    # Before anything starts a process: config.load may already run some. The
    # screen draws on the terminal itself, so it keeps quiet -- the runs it
    # starts still inherit `-v` and say their commands in their own panes.
    if pre.verbose:
        os.environ[ trace.ENV ] = "1"
    if split_verb( build_parser(), argv )[ 0 ] != "tui":
        trace.install()
    root = Path( pre.root ).resolve() if pre.root else find_root()

    config.load( root, warn = lambda m: print( warn( f"  warning: {m}" ), file = sys.stderr ) )

    # Where each run is recorded: errand's own state when nobody asked for a
    # directory -- the history, the screen and `--batch` read it there -- and a
    # tree of the project's ( `runs/` ) when somebody did, with `-o` or `--out`.
    out_root = output_tree( root, pre )

    parser = build_parser( config.tag_names() )
    verb, rest = split_verb( parser, argv )

    if verb == "shell" and "--" in rest:
        print( bad( "errand shell takes no command: `errand run [--env X] <command…>` runs one" ) )
        return 2

    # errand's options, then the target, then what belongs to the target --
    # its own arguments, as `python script.py args…` has them.
    target, after = None, [ ]
    if verb in ( "run", "list" ):
        try:
            before, target, after = split_target( parser, rest )
        except ValueError as err:
            print( bad( f"errand {verb}: {err}" ) )
            return 2
        known, _ = parser.parse_known_args( before )
    else:
        known, _ = parser.parse_known_args( rest )
    known.pattern, known.target_args = target, after
    known.from_default = False

    if known.version and verb is None:
        # The version of the PACKAGE and the file it came out of: an editable
        # install and a copy on PYTHONPATH answer the same otherwise, and which
        # one is answering is exactly what is being asked.
        print( f"errand {__version__}  ({Path( __file__ ).resolve().parent.parent})" )
        return 0

    if verb is None:
        # No verb runs nothing: an implicit `run` would make a file called
        # `list` or `setup.py` a verb.
        print_help( parser )
        return 0 if known.help or not argv else 2

    if verb not in VERBS:
        print( bad( f"errand: unknown verb {verb!r}" ) + dim( "   ( errand --help lists them )" ) )
        return 2

    if known.help:
        print_help( parser, verb )
        return 0

    why = misplaced( parser, known, verb )
    if why:
        print( bad( f"errand: {why}" ) )
        return 2

    # The verbs that take no pattern take no word either, `forget`'s id and
    # `vm`'s action aside: a stray word is a mistake worth hearing about.
    words = [ ]
    if verb not in ( "run", "list" ):
        known, extra = parser.parse_known_args( rest )
        words = ( [ known.pattern ] if known.pattern else [ ] ) + extra
        unknown = [ w for w in words if w.startswith( "-" ) ]
        if unknown:
            print( bad( f"errand {verb}: unknown option {unknown[ 0 ]}" ) )
            return 2
        wanted = { "forget": 1, "vm": 1, "setup": None }.get( verb, 0 )
        if wanted is not None and len( words ) != wanted:
            print( bad( f"errand {verb}: " + ( f"takes no argument ( got {' '.join( words )} )"
                                               if not wanted else "expects one argument" ) ) )
            print_help( parser, verb )
            return 2

    if verb == "tui":
        # Imported here and nowhere else: it needs `curses`, which not every
        # interpreter carries, and a missing screen must not cost the command
        # line.
        from .. import tui
        return tui.main( root = root, out_root = out_root, also = [ root / config.settings.out ] )

    if verb == "init":
        from .. import detect
        return detect.init( root, force = known.force, echo = lambda s: print( dim( s ) ) )

    if verb == "envs":
        return print_envs( root )

    if verb == "shell":
        # Somebody types into it. Through the environment's own layers, the
        # default one when none is named: a shell HERE is the one you typed
        # this in. The user's own shell when the place has it -- a container
        # rarely has the zsh of the machine outside it.
        login = [ "sh", "-c", 'command -v "${SHELL:-}" >/dev/null 2>&1 && exec "$SHELL" -i; exec sh -i' ]
        return run_there( known, login, root = root, interactive = True )

    if verb == "wait":
        return queue.wait_idle()

    if verb == "forget":
        batch.forget( root, words[ 0 ] )
        return 0

    if verb in ( "status", "watch" ):
        return show_batches( root, live = verb == "watch" )

    if verb == "queue":
        return print_queue()

    if verb == "vm":
        if words != [ "stop" ]:
            print( bad( f"errand vm: unknown action {words[ 0 ]!r} ( only `stop` )" ) )
            return 2
        from .. import vm
        # Every keeper is here, wherever its machine runs: stopping it stops that.
        return vm.stop_all( echo = lambda s: print( dim( s ) ) )

    if verb == "setup":
        if words:
            # `errand setup gpu,cluster` reads as well as `--env gpu,cluster`.
            known.env = ",".join( ( [ known.env ] if known.env else [ ] ) + words )
        try:
            targets = _targets( known, config.tag_names() )
        except ValueError as err:
            print( bad( str( err ) ) )
            return 1
        rc = 0
        for env, tags in targets:
            rc |= setup.ensure( root, env, L.Context( root = root, tags = tags ),
                                force = known.force, echo = lambda s: print( dim( s ) ),
                                dry_run = known.dry_run )
        return rc

    # run, list
    if known.at:
        # A child running exactly one entry: no discovery over the tree, no
        # environment selection ( it is already inside one ), no epilogue.
        # `--env` names it when the parent dispatched to one of several; being
        # INSIDE one ( a container, another machine ) names it instead, and
        # wins, because that is where this process actually is.
        inside = os.environ.get( IN_ENV )
        env_obj = ( config.envs.get( inside ) if inside
                    else config.envs.get( known.env ) if known.env
                    else config.default() )
        _put_src_on_path( root )
        return run_one( known.at, root = root, out_root = out_root,
                        env_name = ( env_obj.name if env_obj else known.env or "default" ),
                        tags = _tags_from_env() or ( env_obj.tags if env_obj else { } ),
                        version = __version__, report = Report(),
                        queued = not known.no_queue, ask = Ask( known ) )

    if target is None:
        # What the project says "everything" is: its own targets, from its
        # root. With none, there is nothing obvious to run, and guessing is
        # exactly what errand does not do.
        default = getattr( sys.modules[ "errand" ], "default_run", None )
        if not default:
            print_help( parser, verb )
            print( dim( "\n  nothing to run by default: errand.default_run = [ \"tests/**::*\" ] "
                        "in errand-project.py says what a bare `errand run` runs" ) )
            return 2
        target = ",".join( _from_root( t, root ) for t in ( [ default ] if isinstance( default, str ) else default ) )
        known.pattern, known.from_default = target, True

    kinds = set()
    for k in known.kind:
        if k not in KINDS:
            print( bad( f"unknown kind {k!r}; expected one of {', '.join( sorted( KINDS ) )}" ) )
            return 2
        kinds.add( KINDS[ k ] )

    # Which environments, and with which tags. On the child side of a dispatch
    # there is exactly one, already entered.
    inside = os.environ.get( IN_ENV )
    if inside is not None:
        targets = [ ( config.envs.get( inside ) or config.Env.make( inside, [ ], { } ),
                      _tags_from_env() ) ]
    else:
        try:
            targets = _targets( known, config.tag_names() )
        except ValueError as err:
            print( bad( str( err ) ) )
            return 1

    # Recorded as the command it was, so it can be run again -- from the shell
    # or from the screen. Only on the side that was ASKED: the child of a
    # dispatch runs a command nobody typed, over there.
    if inside is None and verb == "run":
        history.push( root, argv )

    if inside is None and verb == "run" and known.batch:
        forward = [ a for a in before if a != "--batch" ] + ( [ target ] if target else [ ] ) + after
        return submit( targets, forward, argv, root = root, out_root = out_root )

    if known.submit_run:
        env, tags = targets[ 0 ]
        return submit_run( env, tags, [ a for a in before if a != "--submit-run" ]
                                      + ( [ target ] if target else [ ] ) + after, root = root )

    report = Report()
    rc, dispatched = 0, 0
    for env, tags in targets:
        if inside is None and env.vm is not None and verb == "run":
            # errand does not run inside a virtual machine: the command goes in
            # as it is, and what `--pull` names comes back.
            rc |= run_there( known, [ target, *after ], root = root, targets = [ ( env, tags ) ] )
            dispatched += 1
            continue
        if inside is None and env.wraps_anything( tags ):
            # This side only chooses where, and hands the command over as it
            # was typed: what it designates is for that place to say.
            if not known.no_setup:
                if setup.ensure( root, env, L.Context( root = root, tags = tags ),
                                 echo = lambda s: print( dim( s ), flush = True ) ):
                    print( bad( f"  could not prepare {env.name}" ) )
                    rc = 1
                    continue
            print( dim( f"\n  -> {env.name}  {env.describe()}" ), flush = True )
            rc |= go_there( env, tags, verb, rest, root = root, pull = known.pull, time = known.time )
            dispatched += 1
            continue
        rc |= here( env, tags, verb, rest, known, root = root, out_root = out_root,
                    report = report, kinds = kinds, inside = inside )

    # The child of a dispatch has already said how it went, in full. Saying it
    # again here -- out of a report that ran nothing and knows nothing -- is an
    # "all good" under somebody else's failures, which is worse than silence.
    if verb == "list" or ( dispatched and dispatched == len( targets ) ):
        return rc
    if known.phase == "prepare":
        return rc or ( 1 if report.broken else 0 )
    return _epilogue( report, rc )
