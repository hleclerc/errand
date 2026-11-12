"""The plan an environment writes when it prepares: where it lives, reading it back, and the runs it
says will happen.
"""
from __future__ import annotations

from pathlib import Path
import os

from .. import config, entries as E, layers as L, results as R
from .parsing import shown_params


# ── one environment, from inside it ──────────────────────────────────────────

def plans_rel( root ) -> str:
    """The plans, in errand's state: named from the root, as on the other side."""
    return os.path.join( config.state_rel( root ), "plans" )


def plan_path( root, env_name ) -> Path:
    """Where the plan of this command in that environment is written: the same
    path on both sides of a dispatch, since both know the stamp and the name."""
    return Path( root ) / plans_rel( root ) / f"{R.stamp()}-{R.slug( env_name or 'default' )}.json"


def read_plan( root, env_name ):
    import json
    try:
        return json.loads( plan_path( root, env_name ).read_text() )
    except ( OSError, ValueError ):
        return None


def planned( root, stamp ) -> list:
    """Every run the command of that stamp has said it will produce, in every
    place whose plan is here -- written here, or brought back from there."""
    import json
    out = [ ]
    for path in sorted( ( Path( root ) / plans_rel( root ) ).glob( f"{stamp}-*.json" ) ):
        if path.name.endswith( ".submitted.json" ):
            continue
        try:
            out += json.loads( path.read_text() )[ "runs" ]
        except ( OSError, ValueError, KeyError ):
            pass
    return out


# ── letting go, and looking back ─────────────────────────────────────────────

def plan_of( targets, entries, combos, *, root, out_root ):
    """Every run this command is about to produce, and where to look for it.

    One row per ( environment, parameter combination, entry ). The case's own
    directory is predictable -- it is its file and its name -- while the run
    directory under it may not be, since its name carries the PLACE: a remote
    run carries the other machine's name, and a batch job carries whichever
    compute node the scheduler picked. So a row names the place when it is
    knowable and says so when it is not, and whoever reads the tree searches
    beneath `under`.

    Worked out here, once, for everyone who needs it before the fact: the
    targeted rsync pull, the completion signal, and the screen that wants to
    show each case's output as it is written.
    """
    runs = [ ]
    for env, tags in targets:
        unknowable = env.ssh is not None or L.batch_of( env.stack ) is not None
        for _, values in combos:
            for e in entries:
                resolved = shown_params( E.resolve_params( e.params, values ), values )
                _, entry_root = R.dirs_for( out_root, e, resolved, "?", root )
                runs.append( { "label": e.name, "file": e.file.name, "env": env.name,
                               "place": "?" if unknowable else R.place( env.name ),
                               "params": _plain_params( resolved ),
                               "under": R._under( entry_root, root ),
                               "entry_root": R._under( entry_root, root ) } )
    return runs


def _plain_params( resolved ):
    return { k: ( v if isinstance( v, ( int, float, bool, str ) ) else repr( v ) )
             for k, v in resolved.items() }
