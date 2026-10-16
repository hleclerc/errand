"""Launching work and getting the shell back, then finding out how it went.

`--batch` is a MODE, not a layer: it means the same thing in every context,
and only the way of letting go differs.

    local     a session of its own, which survives the terminal
    Ssh       started over there and released
    Slurm, …  `sbatch` instead of `srun`

Nothing else about the run changes -- same paths, same queue, same output. And
because each place writes its plan BEFORE anything runs there, **the arrival of
a result file where its plan said one would be is itself the completion
signal.** There is
no protocol between the two sides, no daemon, and no agreement that can get out
of sync: the output tree is the state.

What is kept here is only what the tree cannot say: which places belong to one
submission, what handle was given for each, and where each writes its plan.
That record is LOCAL: it is the side that asked which knows those places went
together.

Results are PULLED, not pushed: a finished remote run sits there until
something collects it, which is what `errand status` and `errand watch` do.
"""
from __future__ import annotations

import datetime
import os
import re
import subprocess
import time
from pathlib import Path

from . import layers as L, yamlish

def batch_rel( root ) -> str:
    from . import config
    return os.path.join( config.state_rel( root ), "batch" )

PENDING, PREPARING, RUNNING, DONE, LOST = "pending", "preparing", "running", "done", "lost"


def batch_dir( root: Path ) -> Path:
    d = Path( root ) / batch_rel( root )
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

def detach( env, tags, argv, *, root, log: Path, child_env: dict, phase = "run",
            then = None ) -> dict:
    """Start `argv` through `env`'s layers of `phase` and come straight back.

    `then` is what to run once that is done, inside the same allocation but
    outside the layers after its scheduler: how a preparation submits the run
    it has just sized, without anybody waiting for it here.

    -> { kind, handle, host?, remote_root?, options? }, or { kind: "failed" }.
    """
    stack = env.stack_for( phase, tags )
    ctx = L.Context( root = root, tags = tags, batch = True, phase = phase )
    ssh = L.ssh_of( stack )
    batch = L.batch_of( stack )

    if L.vm_of( stack ) is not None:
        return { "kind": "failed", "handle": "",
                 "error": f"{env.name} is a virtual machine: `--batch` does not reach one yet" }

    tail, python, work = stack, "python", ctx
    if ssh is not None:
        tail, python = stack[ 1 : ], ssh.python
        work = L.Context( root = ssh.remote_root( ctx ), tags = tags, remote = True,
                          batch = True, phase = phase )
    cmd = L.Command( [ python, "-m", "errand", *argv ], dict( child_env ) )
    follow = L.Command( [ python, "-m", "errand", *then ], dict( child_env ) ) if then else None
    if follow is not None and batch is not None:
        # Inside the allocation, outside the layers after the scheduler.
        k = tail.index( batch )
        inner = L.compose( tail[ k + 1 : ], cmd, work )
        cmd = L.Command( [ "sh", "-c", f"{inner.shell()} && {follow.shell()}" ], { } )
        tail = tail[ : k + 1 ]
        follow = None
    wrapped = L.compose( tail, cmd, work )
    if follow is not None:
        # No scheduler: the same detached session goes on to the next step.
        wrapped = L.Command( [ "sh", "-c", f"{wrapped.shell()} && {follow.shell()}" ], { } )

    if ssh is None and batch is None:
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
        got = subprocess.run( wrapped.argv, cwd = root, capture_output = True, text = True,
                              env = { **os.environ, **wrapped.env } )
        return _from_submission( got, kind = "batch" )

    L.push( root, ssh.host, work.root, ssh.options )

    remote_log = f"{work.root}/{batch_rel( root )}/{log.name}"
    line = ( f"mkdir -p {work.root}/{batch_rel( root )} && cd {work.root} && "
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

    record.update( host = ssh.host, remote_root = str( work.root ),
                   options = list( ssh.options ), log = remote_log )
    return record


def submitted_path( plan: Path ) -> Path:
    """Where a preparation says which job it submitted for the run it prepared."""
    return plan.with_name( plan.stem + ".submitted.json" )


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


def _json( path: Path ):
    import json
    try:
        return json.loads( path.read_text() )
    except ( OSError, ValueError ):
        return None


def plan_of_place( root: Path, place: dict ):
    """The plan that place wrote, once it has: what it is going to run."""
    return _json( root / place[ "plan" ] ) if place.get( "plan" ) else None


def runs_of( root: Path, record: dict ) -> list:
    """Every run of a submission whose place has said what it will run."""
    out = [ ]
    for place in record.get( "places", [ ] ):
        plan = plan_of_place( root, place )
        if plan is not None:
            out += [ { **r, "env": place.get( "env" ) or r.get( "env" ) } for r in plan[ "runs" ] ]
    return out


def run_job( root: Path, place: dict ):
    """The job a preparation submitted for its run phase, as a place of its own."""
    if not place.get( "plan" ):
        return None
    got = _json( submitted_path( root / place[ "plan" ] ) )
    return { **place, **got } if got else None


def alive_anywhere( root: Path, place: dict ):
    """Still going: the preparation, or the run it submitted."""
    then = run_job( root, place )
    return alive( then ) if then is not None else alive( place )


def collect( root: Path, record: dict ):
    """Fetch what a remote submission has produced so far: its plan first, then
    what the plan says will be written. Cheap, and repeatable."""
    for place in record.get( "places", [ ] ):
        if not place.get( "host" ):
            continue
        there = Path( place[ "remote_root" ] )
        options = place.get( "options" ) or [ ]
        L.fetch( [ str( Path( place[ "plan" ] ).parent ) ], place[ "host" ], there, root, options )
        plan = plan_of_place( root, place )
        if plan is not None:
            L.fetch( sorted( { r[ "under" ] for r in plan[ "runs" ] } ), place[ "host" ], there,
                     root, options )


def states( root: Path, record: dict ) -> list:
    """One row per expected run: what the output tree says about it.

    The tree is the state. A run whose result file is there is done, whatever
    any handle claims; one whose file is absent is still owed, and whether it
    is still going or lost is the only thing a handle is asked about. A place
    that has not written its plan yet is still preparing: one row says so.

    WHERE it ran is looked for, not predicted. The place is part of the path,
    and a batch job carries the name of whichever compute node the scheduler
    happened to pick. So the case directory is searched, and the result that
    names this run's environment and parameters is the one.
    """
    rows = [ ]
    for place in record.get( "places", [ ] ):
        living = alive_anywhere( root, place )
        plan = plan_of_place( root, place )
        if plan is None:
            rows.append( { "label": "(preparing)", "env": place.get( "env" ), "place": "?",
                           "params": { }, "under": "",
                           "state": PREPARING if living or living is None else LOST } )
            continue
        for run in plan[ "runs" ]:
            run = { **run, "env": place.get( "env" ) or run.get( "env" ) }
            result = _result_for( root, run )
            if result:
                rows.append( { **run, "state": DONE, "status": result.get( "status" ),
                               "place": result.get( "place" ) or run.get( "place" ),
                               "seconds": result.get( "duration_s" ),
                               "results": result.get( "results" ) or { } } )
            else:
                rows.append( { **run, "state": RUNNING if living or living is None else LOST } )
    return rows


def _result_for( root: Path, run: dict ):
    path = result_path_for( root, run )
    return yamlish.read( path ) if path else None


def result_path_for( root: Path, run: dict ):
    """WHERE this run's result file landed, or None while it is still owed.

    The path and not just its contents, because whoever wants to watch the run
    wants `output.txt` beside it.
    """
    if not run.get( "under" ):
        return None
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
