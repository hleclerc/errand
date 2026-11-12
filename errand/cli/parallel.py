"""Running entries in several processes ( `-j` ): each child runs exactly one.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .. import discovery, entries as E, results as R
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
    print( head( f"\n{'=' * 10} {total} entr{'y' if total == 1 else 'ies'}"
                 f"  {env.name}  {out_prefix}  -j {how_many} {'=' * 10}" ), flush = True )

    def start( e, values ):
        child = dict( os.environ )
        child[ PARAMS ] = json.dumps( values )
        child[ "PYTHONUNBUFFERED" ] = "1"
        argv = [ sys.executable, "-m", "errand", "run", "--at", f"{e.file}:{e.line}",
                 "--root", str( root ), "--env", env.name, *flags ]
        return ( e, values,
                 subprocess.Popen( argv, cwd = root, env = child, text = True,
                                   stdout = subprocess.PIPE, stderr = subprocess.STDOUT ) )

    while pending or running:
        while pending and len( running ) < how_many:
            running.append( start( *pending.pop( 0 ) ) )

        e, values, child = running.pop( 0 )
        output = child.communicate()[ 0 ]
        done += 1
        # In completion order, as a block: interleaved lines from several
        # entries at once are unreadable, and worse, unattributable.
        sys.stdout.write( output )
        sys.stdout.flush()

        resolved = E.resolve_params( e.params, values )
        leaf, _ = R.dirs_for( out_root, e, shown_params( resolved, values ), R.place( env.name ), root )
        got = yamlish.read( leaf / R.RESULT ) or { }
        status = got.get( "status" ) or ( "PASS" if child.returncode == 0 else "FAIL" )
        if status == "SKIP":
            report.skipped.append( ( e, got.get( "error" ), None ) )
        elif status != "PASS":
            report.failed.append( ( e, got.get( "error" ) or f"exit {child.returncode}" ) )
    return report


def run_one( at, *, root, out_root, env_name, tags, version, report, queued, ask = None ):
    """The child side of the above: exactly the entry at FILE:LINE."""
    from .. import yamlish

    path, _, line = at.rpartition( ":" )
    entries, modules = discovery.select_at( Path( path ), int( line ), root )
    if not entries:
        print( bad( f"no entry at {at}" ) )
        return 1

    values = json.loads( os.environ[ PARAMS ] ) if os.environ.get( PARAMS ) else { }
    run_entries( entries, modules, root = root, out_root = out_root, overrides = values,
                 env_name = env_name, tags = tags, version = version,
                 report = report, queued = queued, quiet = True, ask = ask )
    return 1 if report.failed else 0
