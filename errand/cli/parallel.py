"""Running entries in several processes ( `-j` ): each child runs exactly one.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import discovery, entries as E, results as R, steps, streams
from . import bottom
from .render import COLOR, colors_on, forced_colors, recent_lines
from .style import bad, head
from .here import run_entries
from .parsing import shown_params


# ── running, several at once ─────────────────────────────────────────────────
#
# One process per entry, because the isolation between entries IS the module
# reload, and a reload only isolates within one interpreter. Serial runs stay
# in this process: they are faster that way and their output arrives live.
#
# A child is told which entry by call site (`--at file:line`) and what its
# parameters are through the environment -- not as flags, because a resolved
# value is allowed to contain a comma and a comma on the command line means a
# matrix.

PARAMS = "ERRAND_PARAMS"


def job_count( asked ) -> int:
    if asked in ( None, "", "1" ):
        return 1
    if str( asked ) == "auto":
        return max( 1, os.cpu_count() or 1 )
    try:
        return max( 1, int( asked ) )
    except ValueError:
        raise ValueError( f"-j: expected a number or `auto`, got {asked!r}" )


def run_in_processes( entries, combos, *, root, out_root, env, tags, how_many, report,
                      out_prefix, flags = ( ) ):
    """Each entry, in its own process, up to `how_many` at a time.

    What came of it is read back from the result file rather than parsed out of
    the child's chatter: the path was worked out before the child started, and
    the file is the record either way.
    """
    from .. import yamlish

    pending = [ ( e, values ) for _, values in combos for e in entries ]
    running, done = [ ], 0
    total = len( pending )
    from .here import drawn
    drawn().banner( total, env.name, f"{out_prefix}  -j {how_many}" )

    def start( e, values ):
        child = dict( os.environ )
        child[ PARAMS ] = json.dumps( values )
        child[ "PYTHONUNBUFFERED" ] = "1"
        if colors_on( sys.stdout ):
            child[ COLOR ] = "1"          # its block is shown on this terminal: drawn for it ( ADR 0016 )
            child.update( forced_colors() )   # and what it runs colors its output, as it would here
        argv = [ sys.executable, "-m", "errand", "run", "--at", at_of( e, root ),
                 "--root", str( root ), "--env", env.name, *flags ]
        talk = how_many > 1 and _interactive()
        proc = subprocess.Popen( argv, cwd = root, env = child, stdin = subprocess.PIPE if talk else subprocess.DEVNULL,
                                 stdout = subprocess.PIPE, stderr = subprocess.STDOUT )
        said = [ ]                        # what it wrote, read as it comes: for Focus, then its block
        last = [ 0.0 ]
        answered = [ False ]              # a line typed for it ended the line its question left open
        from .here import drawn
        gutter = drawn().gutter( False ).encode()

        def read():
            for chunk in iter( lambda: os.read( proc.stdout.fileno(), 65536 ), b"" ):
                if answered[ 0 ] and gutter and not chunk.startswith( gutter ):
                    chunk = gutter + chunk        # the child cannot know its line was ended here
                answered[ 0 ] = False
                said.append( chunk )
                last[ 0 ] = time.time()

        def write( data ):
            said.append( data )           # in its block, as a terminal would have shown it ( ADR 0016 )
            answered[ 0 ] = data.endswith( b"\n" )
            try:
                proc.stdin.write( data )
                proc.stdin.flush()
            except ( OSError, ValueError ):
                pass

        def close():
            try:
                proc.stdin.close()
            except OSError:
                pass

        reader = threading.Thread( target = read, daemon = True )
        reader.start()
        leaf = leaf_of( e, values )
        journal = leaf / steps.FILE
        bottom.case_start( proc.pid, e.name,
                           recent = lambda n: recent_lines( b"".join( said ).decode( errors = "replace" ), n ),
                           poll = lambda: steps.line( steps.summary( journal ) ) if journal.exists() else None,
                           write = write if talk else None, close = close if talk else None,
                           waiting = lambda: bool( said ) and not said[ -1 ].endswith( b"\n" ) and time.time() - last[ 0 ] > 2 )
        return e, values, proc, reader, said

    def leaf_of( e, values ):
        resolved = E.resolve_params( e.params, values )
        return R.dirs_for( out_root, e, shown_params( resolved, values ), R.place( env.name ), root )[ 0 ]

    with bottom.keys() if how_many > 1 else contextlib.nullcontext():
        while pending or running:
            while pending and len( running ) < how_many:
                running.append( start( *pending.pop( 0 ) ) )
            ended = next( ( r for r in running if r[ 2 ].poll() is not None ), None )
            if ended is None:
                time.sleep( 0.05 )
                continue
            running.remove( ended )
            e, values, child, reader, said = ended
            reader.join()
            bottom.case_end( child.pid )
            done += 1
            # In completion order, as a block: interleaved lines from several
            # entries at once are unreadable, and worse, unattributable.
            sys.stdout.write( b"".join( said ).decode( errors = "replace" ) )
            sys.stdout.flush()
            _tally( e, values, child, report, leaf_of )
    return report


def _tally( e, values, child, report, leaf_of ):
    """What came of a child, read from its record."""
    from .. import yamlish
    leaf = leaf_of( e, values )
    got = yamlish.read( leaf / R.RESULT ) or { }
    status = got.get( "status" ) or ( "PASS" if child.returncode == 0 else "FAIL" )
    if status == "SKIP":
        report.skipped.append( ( e, got.get( "error" ), None ) )
    elif status != "PASS":
        why = got.get( "error" ) or streams.ended( child.returncode )
        if child.returncode and got.get( "duration_s" ) is None:
            # it died before writing its record ( the keeper of its streams wrote one ): how, and its stderr
            why = streams.with_tail( f"{streams.ended( child.returncode )}: {why}",
                                     streams.tail( leaf / R.STDERR ) )
        report.failed.append( ( e, why ) )
    return report


def _interactive( ) -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except ( AttributeError, ValueError ):
        return False


RUNNER_AT = "runner:"


def at_of( e, root ) -> str:
    """What a child is told to run: errand's own entry by its call site ( FILE:LINE ), a runner's run
    by the runner and its target ( `runner:NAME:path[::selector]` )."""
    if e.runner is None:
        return f"{e.file}:{e.at}"
    path = os.path.relpath( e.file, root ) if Path( e.file ).is_absolute() else str( e.file )
    if e.runner.takes_entries:
        path += f"::{e.selector or '*'}"
    return f"{RUNNER_AT}{e.runner.name}:{path}"


def run_one( at, *, root, out_root, env_name, tags, version, report, queued, ask = None ):
    """The child side of the above: exactly the entry at FILE:LINE, or the one run of a runner."""
    from .. import config

    if at.startswith( RUNNER_AT ):
        name, _, target = at[ len( RUNNER_AT ) : ].partition( ":" )
        entries, modules, _ = discovery.select( target, root, exclude = config.settings.exclude,
                                                runners = config.runners, cwd = root, force = name )
    else:
        path, _, line = at.rpartition( ":" )
        entries, modules = discovery.select_at( Path( path ), line, root )
    if not entries:
        print( bad( f"no entry at {at}" ) )
        return 1

    values = json.loads( os.environ[ PARAMS ] ) if os.environ.get( PARAMS ) else { }
    run_entries( entries, modules, root = root, out_root = out_root, overrides = values,
                 env_name = env_name, tags = tags, version = version,
                 report = report, queued = queued, quiet = True, ask = ask )
    return 1 if report.failed else 0
