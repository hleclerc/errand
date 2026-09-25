"""Launching work and getting the shell back, then finding out how it went.

`--batch` is a MODE, not a layer: it means the same thing in every context,
and only the way of letting go differs.

    local     a session of its own, which survives the terminal
    Ssh       started over there and released
    Slurm, …  `sbatch` instead of `srun`

Nothing else about the run changes -- same paths, same queue, same output. And
because the paths were worked out BEFORE anything started, **the arrival of a
result file where one was expected is itself the completion signal.** There is
no protocol between the two sides, no daemon, and no agreement that can get out
of sync: the output tree is the state.

What is kept here is only what the tree cannot say: which runs belong to one
submission, and what handle was given for each place. That record is LOCAL,
because the side that expanded the matrix is the only one that ever knew those
runs went together.

Results are PULLED, not pushed: a finished remote run sits there until
something collects it, which is what `--status` and `--watch` do.
"""
from __future__ import annotations

import datetime
import os
import re
import subprocess
import time
from pathlib import Path

from . import layers as L, yamlish

BATCH_DIR = ".errand/batch"

PENDING, RUNNING, DONE, LOST = "pending", "running", "done", "lost"


def batch_dir( root: Path ) -> Path:
    d = root / BATCH_DIR
    d.mkdir( parents = True, exist_ok = True )
    return d


def new_id( root: Path ) -> str:
    """Short, and not already taken."""
    import hashlib
    seed = f"{time.time_ns()}-{os.getpid()}"
    return hashlib.sha256( seed.encode() ).hexdigest()[ : 4 ]


def record_path( root: Path, ident: str ) -> Path:
    return batch_dir( root ) / f"{ident}.yaml"


def save( root: Path, record: dict ):
    yamlish.write( record_path( root, record[ "id" ] ), record )


def load_all( root: Path ) -> list:
    out = [ ]
    for path in sorted( batch_dir( root ).glob( "*.yaml" ) ):
        got = yamlish.read( path )
        if got:
            out.append( got )
    return sorted( out, key = lambda r: r.get( "when", "" ) )


def forget( root: Path, ident: str ):
    record_path( root, ident ).unlink( missing_ok = True )


# ── letting go ───────────────────────────────────────────────────────────────

def detach( env, tags, argv, *, root, log: Path, child_env: dict ) -> dict:
    """Start `argv` through `env`'s layers and come straight back.

    -> { kind, handle, host?, remote_root?, options? }, or { kind: "failed" }.
    """
    ctx = L.Context( root = root, tags = tags, batch = True )
    cmd = L.Command( [ "python", "-m", "errand", *argv ], dict( child_env ) )

    ssh = env.ssh
    batch = L.batch_of( env.stack )

    if ssh is None and batch is None:
        wrapped = L.compose( env.stack, cmd, ctx )
        log.parent.mkdir( parents = True, exist_ok = True )
        with open( log, "wb" ) as handle:
            # A session of its own: closing the terminal, or the shell sending
            # a hangup to its group, must not take the work with it.
            child = subprocess.Popen( wrapped.argv, cwd = root,
                                      env = { **os.environ, **wrapped.env },
                                      stdout = handle, stderr = subprocess.STDOUT,
                                      start_new_session = True )
        return { "kind": "local", "handle": str( child.pid ), "log": str( log ) }

    if ssh is None:
        # A batch system here on this machine: it is its own detachment.
        wrapped = L.compose( env.stack, cmd, ctx )
        got = subprocess.run( wrapped.argv, cwd = root, capture_output = True, text = True,
                              env = { **os.environ, **wrapped.env } )
        return _from_submission( got, kind = "batch" )

    remote_ctx = L.Context( root = ssh.remote_root( ctx ), tags = tags, remote = True,
                            batch = True )
    wrapped = L.compose( env.stack[ 1 : ], L.Command( [ ssh.python, *cmd.argv[ 1 : ] ], cmd.env ),
                         remote_ctx )
    L.push( root, ssh.host, remote_ctx.root, ssh.options )

    remote_log = f"{remote_ctx.root}/{BATCH_DIR}/{log.name}"
    line = ( f"mkdir -p {remote_ctx.root}/{BATCH_DIR} && cd {remote_ctx.root} && "
             f"{wrapped.shell()}" )

    if batch is not None:
        # sbatch returns as soon as the job is queued: nothing to let go of.
        got = _ssh_capture( ssh, line )
        record = _from_submission( got, kind = "batch" )
    else:
        # Let go over there: a new session, output to a file we can fetch, and
        # the pid printed back so there is something to ask about later.
        detached = ( f"{line} > {remote_log} 2>&1 & echo ERRAND_PID=$!" )
        got = _ssh_capture( ssh, detached )
        found = re.search( r"ERRAND_PID=(\d+)", got.stdout or "" )
        record = ( { "kind": "ssh", "handle": found.group( 1 ) } if found
                   else { "kind": "failed", "handle": "",
                          "error": ( got.stderr or got.stdout or "" ).strip()[ : 400 ] } )

    record.update( host = ssh.host, remote_root = str( remote_ctx.root ),
                   options = list( ssh.options ), log = remote_log )
    return record


def _ssh_capture( ssh, line ):
    import shlex
    return subprocess.run( [ "ssh", *ssh.options, ssh.host, f"$SHELL -ic {shlex.quote( line )}" ],
                           capture_output = True, text = True )


def _from_submission( got, kind ):
    # Every batch system prints its job id and little else; slurm's wording is
    # the one worth matching exactly, the rest fall back to the first number.
    text = ( got.stdout or "" ) + ( got.stderr or "" )
    found = re.search( r"Submitted batch job (\d+)", text ) or re.search( r"\b(\d{3,})\b", text )
    if got.returncode or not found:
        return { "kind": "failed", "handle": "", "error": text.strip()[ : 400 ] }
    return { "kind": kind, "handle": found.group( 1 ) }


# ── asking how it is going ───────────────────────────────────────────────────

def alive( place: dict ) -> bool | None:
    """Is the thing we were given a handle for still going? None: cannot say."""
    kind, handle = place.get( "kind" ), str( place.get( "handle" ) or "" )
    if not handle:
        return False
    try:
        if kind == "local":
            os.kill( int( handle ), 0 )
            return True
        if kind == "ssh":
            return _remote( place, f"kill -0 {handle}" ).returncode == 0
        if kind == "batch":
            if place.get( "host" ):
                got = _remote( place, f"squeue -h -j {handle} -o %T" )
            else:
                got = subprocess.run( [ "squeue", "-h", "-j", handle, "-o", "%T" ],
                                      capture_output = True, text = True, timeout = 30 )
            return bool( ( got.stdout or "" ).strip() ) if not got.returncode else False
    except ( ProcessLookupError, ValueError ):
        return False
    except ( OSError, subprocess.SubprocessError ):
        return None
    return None


def _remote( place: dict, line: str ):
    return subprocess.run( [ "ssh", *( place.get( "options" ) or [ ] ), place[ "host" ], line ],
                           capture_output = True, text = True, timeout = 60 )


def collect( root: Path, record: dict ):
    """Fetch what a remote submission has produced so far. Cheap, and repeatable."""
    for place in record.get( "places", [ ] ):
        if place.get( "host" ) and record.get( "pull" ):
            L.fetch( record[ "pull" ], place[ "host" ], Path( place[ "remote_root" ] ), root,
                     place.get( "options" ) or [ ] )


def states( root: Path, record: dict ) -> list:
    """One row per expected run: what the output tree says about it.

    The tree is the state. A run whose result file is there is done, whatever
    any handle claims; one whose file is absent is still owed, and whether it
    is still going or lost is the only thing a handle is asked about.

    WHERE it ran is looked for, not predicted. The place is part of the path,
    and this side does not know it: a remote run carries the other machine's
    name, and a batch job carries the name of whichever compute node the
    scheduler happened to pick. So the parameter directory -- which IS
    predictable, being a hash of what was asked for -- is searched, and the
    result that names this run's environment and parameters is the one.
    """
    living = any( alive( p ) for p in record.get( "places", [ ] ) )
    rows = [ ]
    for run in record.get( "runs", [ ] ):
        result = _result_for( root, run )
        if result:
            rows.append( { **run, "state": DONE, "status": result.get( "status" ),
                           "place": result.get( "place" ) or run.get( "place" ),
                           "seconds": result.get( "duration_s" ),
                           "results": result.get( "results" ) or { } } )
        else:
            rows.append( { **run, "state": RUNNING if living else LOST } )
    return rows


def _result_for( root: Path, run: dict ):
    path = result_path_for( root, run )
    return yamlish.read( path ) if path else None


def result_path_for( root: Path, run: dict ):
    """WHERE this run's result file landed, or None while it is still owed.

    The path and not just its contents, because whoever wants to watch the run
    wants `output.txt` beside it.
    """
    under = root / run[ "under" ]
    if not under.is_dir():
        return None
    # Newest first: the run directories are named after the moment they
    # started, so sorting their names backwards IS sorting them by time.
    for path in sorted( under.glob( "*/result.yaml" ), reverse = True ):
        got = yamlish.read( path )
        if not got:
            continue
        if got.get( "env" ) == run.get( "env" ) and ( got.get( "params" ) or { } ) == \
           ( run.get( "params" ) or { } ):
            return path
    return None


def finished( rows ) -> bool:
    return all( r[ "state" ] in ( DONE, LOST ) for r in rows )


def now( ) -> str:
    return datetime.datetime.now().replace( microsecond = 0 ).isoformat( sep = " " )
