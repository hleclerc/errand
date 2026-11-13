"""One environment, driven from here ( ADR 0005 ): this side orchestrates, a session over there does the work.

What is decided is decided here: whether the environment is up to date, sending
the project, which cases ( every entry the preparation found, for every
combination of values ), how many at a time, the report, what comes back. What
is done is done over there, by a session ( `agents/ops.py` ), reached in one of
three ways ( `Reach` ):

    agent      no scheduler on the way: the environment's agent starts it
    command    a scheduler, waited for ( `srun` ): started through the layers by the host
    watched    a scheduler, asked about ( `Slurm( watch = … )` ): submitted, its log read

`--batch` is the same, let go of: prepared here, then submitted ( `submit` ).

A session started by an agent outlives this process. What it takes to find it
again is in `<state>/live/<id>.json`, which `errand attach` follows.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

from .. import agents, batch, bootstrap, config, layers as L, results as R
from ..agents import envs, upstream as U
from ..agents.ops import KNOWN
from .parallel import job_count
from .plans import plans_rel, read_plan
from .project import child_env_for
from . import alive, guest
from .sessions import follow_all, INTERRUPTED, LocalSession, Session, WatchedSession
from .style import dim, head, warn

LOGIN = 'exec "${SHELL:-/bin/sh}" -ic "$1"'          # `sh -c LOGIN sh line`: the user's interactive shell


def say( s ):
    print( dim( s ), flush = True )


def eligible( env, tags ) -> bool:
    """Driven from here: always -- a virtual machine when errand can run in it ( it has a Python )."""
    return env.vm is None or guest.usable( env )


def arrive( env, tags, root ):
    """The project over there, and errand's sources: -> where it all is."""
    ssh = L.ssh_of( env.stack_for( "run", tags ) )
    there = ssh.remote_root( L.Context( root = root ) ) if ssh is not None else root
    for message in L.warnings_for( env.stack_for( "run", tags ), there ):
        print( warn( f"  warning: {message}" ), flush = True )
    home = None
    if ssh is not None:
        say( f"  rsync push -> {ssh.host}:{there}" )
        L.push( root, ssh.host, there, ssh.options, echo = say, outputs = ssh.errand_outputs_directory )
        for other in ssh.also:
            L.push( Path( os.path.normpath( root / other ) ), ssh.host,
                    Path( os.path.normpath( there / other ) ), ssh.options )
        home = bootstrap.ship( ssh.host, ssh.options )
    return SimpleNamespace( root = root, ssh = ssh, there = Path( there ), home = home,
                            boot = envs.boot_of( ssh, home ) )


class Reach:
    """How a session of `env` reaches the environment in `phase`."""

    def __init__( self, env, tags, phase, where, *, needs = None, time = None, batch = False ):
        self.env, self.tags, self.phase, self.where = env, tags, phase, where
        self.stack = env.stack_for( phase, tags )
        self.inner = [ l for l in self.stack if not isinstance( l, L.Ssh ) ]
        self.sched = L.batch_of( self.inner )
        self.ctx   = L.Context( root = where.there, tags = tags, remote = where.ssh is not None, phase = phase,
                                needs = { **( needs or { } ), **( { "time": time } if time else { } ) }, batch = batch )
        watched = getattr( self.sched, "watched", None )
        self.kind  = ( "agent" if self.sched is None
                       else "alive" if alive.scheduler( self.inner ) is not None and not batch
                       else "watched" if watched is not None and watched( self.ctx ) else "command" )
        self.target = None             # what `attach` reaches again, once started

    def line( self, request: dict, child: dict ) -> str:
        """The session as one shell line, through the layers, from the project's root over there."""
        ssh = self.where.ssh
        cmd = L.Command( [ "python", "-m", "errand.agents.ops", "session", json.dumps( request ) ], child )
        sent = bootstrap.command( cmd, self.inner, self.where.home or str( Path.home() ),
                                  ssh.python if ssh is not None else "python",
                                  boot = None if ssh is not None else self.where.boot )
        self.wrapped = L.compose( self.inner, sent, self.ctx )
        return f"cd {shlex.quote( str( self.where.there ) )} && {self.wrapped.shell()}"

    def start( self, request: dict, child: dict ):
        w = self.where
        if w.ssh is not None:
            # over there, errand's outputs are the copy's own: not wherever this side keeps them
            child = { **child, config.OUTPUTS_ENV: config.outputs_rel( w.root ) }
        if self.kind == "alive":
            self._warm_or_not()
        if not agents.enabled() and self.kind != "watched":
            # No agent ( ERRAND_AGENT=off ): the same session, through one ssh of its own, or here.
            line = self.line( request, child )
            if w.ssh is None:
                return LocalSession( [ "sh", "-c", line ], cwd = str( w.root ) )
            return LocalSession( [ "ssh", "-T", *w.ssh.options, w.ssh.host, f"$SHELL -ic {shlex.quote( line )}" ] )
        if self.kind in ( "agent", "alive" ):
            self.target = ( envs.target( self.env, self.stack, self.tags, self.phase, root = w.there, ssh = w.ssh,
                                         home = w.home ) if self.kind == "agent"
                            else alive.Allocation( self.env, self.tags, w ).env_target() )
            conn = agents.open( self.target )
            return Session.start( conn, envs.ops_argv( envs.python_of( conn ), w.boot, request,
                                                       L.preload_of( self.inner ) ),
                                  cwd = str( w.there ), env = child, store = store_of( w ) )
        line = self.line( request, child )
        if self.kind == "watched":
            host = L.Over( w.ssh, w.there ) if w.ssh is not None else L.Here( w.root )
            return WatchedSession( host, self.wrapped, L.watch_dir( self.ctx ), self.sched.watch, say )
        if w.ssh is None:
            return LocalSession( [ "sh", "-c", line ], cwd = str( w.root ) )
        self.target = U.ssh_target( w.ssh )
        return Session.start( agents.open( self.target ), [ "sh", "-c", LOGIN, "sh", line ], store = store_of( w ) )


    def _warm_or_not( self ):
        """The allocation held warm, if this command fits in it; else a job of its own ( `srun` ),
        after giving the warm one back if nothing runs in it -- it may hold the very nodes."""
        w = self.where
        alloc = alive.Allocation( self.env, self.tags, w )
        host = L.Over( w.ssh, w.there ) if w.ssh is not None else L.Here( w.root )
        needs = { k: v for k, v in ( self.ctx.needs or { } ).items() if k != "time" }
        ok, why = alive.fits( alloc, needs, ( self.ctx.needs or { } ).get( "time" ), host )
        if ok:
            return
        say( f"  not in the allocation kept warm ( {why} ): a job of its own" )
        if alive.release_if_idle( alloc, host ):
            say( "  the allocation kept warm was given back first" )
        self.kind = "command"


def _requests( env, tags, verb, known, kinds, where ) -> dict:
    return { "root": str( where.there ), "env": env.name, "tags": tags, "verb": verb, "kinds": sorted( kinds ),
             "known": { **{ k: getattr( known, k, None ) for k in KNOWN }, "from_plan": False, "phase": None } }


def _prepare( env, tags, verb, known, kinds, where, report, box ) -> int:
    """The preparation on its own, through the preparation's layers. -> its return code."""
    base = _requests( env, tags, verb, known, kinds, where )
    req = { **base, "prepare_only": True, "known": { **base[ "known" ], "phase": None if verb == "list" else "prepare" } }
    rcs = follow_all( [ Reach( env, tags, "prepare", where ).start( req, child_env_for( env, tags ) ) ], report, [ box ] )
    return INTERRUPTED if rcs is None else rcs[ 0 ]


def drive( env, tags, verb, known, *, root, out_root, report, kinds, pull = ( ) ) -> int:
    if env.vm is not None:
        return _drive_guest( env, tags, verb, known, root = root, report = report, kinds = kinds, pull = pull )
    where = arrive( env, tags, root )
    child = child_env_for( env, tags )
    base = _requests( env, tags, verb, known, kinds, where )
    how_many = job_count( known.jobs )
    single = env.single_pass( tags ) and how_many == 1 and verb != "list"
    box : dict = { }

    if not single:
        rc = _prepare( env, tags, verb, known, kinds, where, report, box )
        if verb == "list" or rc or not box.get( "plan" ):
            _bring_back( where, env.name, box, [ ] )
            return rc

    reach = Reach( env, tags, "run", where, needs = ( box.get( "plan" ) or { } ).get( "needs" ),
                   time = getattr( known, "time", None ) )
    runs = { **base, "known": { **base[ "known" ], "from_plan": not single, "phase": "run" } }
    if single:
        sessions = [ reach.start( runs, child ) ]
    else:
        cases = [ ( i, j ) for i in range( len( box[ "combos" ] ) ) for j in range( len( box[ "entries" ] ) ) ]
        k = max( 1, min( how_many, len( cases ) ) )
        if k > 1 and reach.kind not in ( "agent", "alive" ):
            print( warn( f"  -j {how_many}: in one allocation, the cases run one after the other" ), flush = True )
            k = 1
        if how_many > 1:
            place = ( box[ "plan" ].get( "runs" ) or [ { } ] )[ 0 ].get( "place" ) or R.place( env.name )
            print( head( f"\n{'=' * 10} {len( cases )} entr{'y' if len( cases ) == 1 else 'ies'}"
                         f"  {env.name}  {place}  -j {how_many} {'=' * 10}" ), flush = True )
        sessions = [ reach.start( { **runs, "cases": cases[ s :: k ], "blocks": how_many > 1 }, child )
                     for s in range( k ) ]

    live = _remember( root, env, reach, sessions, where, pull )
    boxes = [ dict( box ) for _ in sessions ]
    rcs = follow_all( sessions, report, boxes )
    if rcs is None:
        if live:
            live.unlink( missing_ok = True )            # stopped: nothing over there to come back to
        return INTERRUPTED
    box.update( next( ( b for b in boxes if b.get( "plan" ) ), { } ) )
    if any( b.get( "lost" ) for b in boxes ):
        return 1                                        # left running, and said so: `errand attach`
    _bring_back( where, env.name, box, pull )
    if live:
        live.unlink( missing_ok = True )
    return max( rcs ) if rcs else 0


def _drive_guest( env, tags, verb, known, *, root, report, kinds, pull ) -> int:
    """The same, in a virtual machine: held for as long as this runs, everything through its guest agent."""
    from ..vm.common import VmError
    where = arrive( env, tags, root )
    child = child_env_for( env, tags )
    base = _requests( env, tags, verb, known, kinds, where )
    how_many = job_count( known.jobs )
    box : dict = { }
    try:
        with guest.Guest( env, tags, where, say ) as g:
            if verb == "list" or how_many > 1:
                req = { **base, "prepare_only": True, "known": { **base[ "known" ], "phase": None if verb == "list" else "prepare" } }
                rcs = follow_all( [ g.start( req, child ) ], report, [ box ] )
                if rcs is None:
                    return INTERRUPTED
                if verb == "list" or rcs[ 0 ] or not box.get( "plan" ):
                    return rcs[ 0 ]
                cases = [ ( i, j ) for i in range( len( box[ "combos" ] ) ) for j in range( len( box[ "entries" ] ) ) ]
                k = max( 1, min( how_many, len( cases ) ) )
                runs = { **base, "known": { **base[ "known" ], "from_plan": True, "phase": "run" } }
                sessions = [ g.start( { **runs, "cases": cases[ s :: k ], "blocks": True }, child ) for s in range( k ) ]
            else:
                sessions = [ g.start( { **base, "known": { **base[ "known" ], "phase": "run" } }, child ) ]
            boxes = [ dict( box ) for _ in sessions ]
            rcs = follow_all( sessions, report, boxes )
            if rcs is None:
                return INTERRUPTED
            box.update( next( ( b for b in boxes if b.get( "plan" ) ), { } ) )
            plan = box.get( "plan" ) or { }
            g.fetch( [ plans_rel( root ), *sorted( { r[ "under" ] for r in plan.get( "runs", [ ] ) } ), *pull ] )
    except VmError as err:
        say( f"  {err}" )
        return 1
    _bring_back( where, env.name, box, pull )
    return max( rcs ) if rcs else 0


# ── coming back ──────────────────────────────────────────────────────────────

def store_of( where ) -> str:
    """Where the agent keeps what a session writes, for `errand attach`: in the project over there
    ( `errand-outputs/state/procs/` ), never in the agent's own directory, which every project shares."""
    if where.ssh is None:
        return str( config.state( where.root ) / "procs" )
    return f"{where.there}/{config.state_rel( where.root )}/procs"


def _remember( root, env, reach, sessions, where, pull ):
    """What `errand attach` needs, when there is something to attach to."""
    pids = [ s.pid for s in sessions if getattr( s, "pid", None ) ]
    if not pids or reach.target is None:
        return None
    ident = f"{R.stamp()}-{R.slug( env.name )}"
    live = config.state( root ) / "live" / f"{ident}.json"
    live.parent.mkdir( parents = True, exist_ok = True )
    live.write_text( json.dumps( { "id": ident, "env": env.name, "target": reach.target, "procs": pids,
                                   "ssh": None if where.ssh is None else
                                   { "host": where.ssh.host, "options": list( where.ssh.options ) },
                                   "there": str( where.there ), "store": store_of( where ),
                                   "pull": list( pull ) }, indent = 1 ) )
    return live


def _bring_back( where, env_name, box, pull ):
    ssh = where.ssh
    if ssh is None:
        return

    def fetch( paths ):
        if paths:
            say( f"  rsync pull  <- {ssh.host}:{where.there} [{', '.join( paths )}]" )
            L.fetch( paths, ssh.host, where.there, where.root, ssh.options )

    fetch( [ plans_rel( where.root ) ] )
    plan = box.get( "plan" ) or read_plan( where.root, env_name )
    if plan:
        fetch( sorted( { r[ "under" ] for r in plan[ "runs" ] } ) )
    fetch( list( pull ) )


def attach( root, ident = None, *, report ) -> int:
    """`errand attach [ID]`: follow again what a command left running over there, and bring it back."""
    lives = sorted( ( config.state( root ) / "live" ).glob( "*.json" ) )
    if ident:
        lives = [ p for p in lives if p.stem.startswith( ident ) ]
    if not lives:
        say( "  nothing left running to attach to" )
        return 0
    rc = 0
    for path in lives:
        rec = json.loads( path.read_text() )
        say( f"\n  -> {rec[ 'env' ]}  ( {rec[ 'id' ]} )" )
        from .standing import processes
        try:
            gone = any( p is None for p in processes( rec ) )
        except Exception:
            gone = False                                # cannot tell: try to follow it
        if gone:
            # Its output over there was let go of. What it wrote in the project is still there.
            say( "  its output is gone over there: bringing back what it wrote" )
        else:
            conn = agents.open( rec[ "target" ] )
            boxes = [ { } for _ in rec[ "procs" ] ]
            rcs = follow_all( [ Session( conn, pid, rec.get( "store" ) ) for pid in rec[ "procs" ] ], report, boxes )
            if rcs is None:
                path.unlink( missing_ok = True )
                return INTERRUPTED
            rc |= max( rcs ) if rcs else 0
            if any( b.get( "lost" ) for b in boxes ):
                continue
        ssh = SimpleNamespace( **rec[ "ssh" ] ) if rec.get( "ssh" ) else None
        _bring_back( SimpleNamespace( root = root, ssh = ssh, there = Path( rec[ "there" ] ) ), rec[ "env" ], { },
                     rec.get( "pull", [ ] ) )
        path.unlink( missing_ok = True )
    return rc


# ── letting go ───────────────────────────────────────────────────────────────

def submit( env, tags, known, *, root, kinds, report, log: Path ) -> dict:
    """`--batch`: prepared here, then the run submitted and let go of. -> the place of the record."""
    where = arrive( env, tags, root )
    box : dict = { }
    rc = _prepare( env, tags, "run", known, kinds, where, report, box )
    if where.ssh is not None:                          # the plan, here, for `status`
        L.fetch( [ plans_rel( root ) ], where.ssh.host, where.there, root, where.ssh.options )
    if rc or not box.get( "plan" ):
        return { "kind": "failed", "handle": "", "error": "the preparation did not succeed" }

    reach = Reach( env, tags, "run", where, needs = box[ "plan" ].get( "needs" ),
                   time = getattr( known, "time", None ), batch = True )
    base = _requests( env, tags, "run", known, kinds, where )
    line = reach.line( { **base, "known": { **base[ "known" ], "from_plan": True, "phase": "run" } },
                       child_env_for( env, tags ) )
    logs = f"{where.there}/{batch.batch_rel( root )}"
    remote_log = f"{logs}/{log.name}"
    mkdir = f"mkdir -p {shlex.quote( logs )}"

    if reach.sched is not None:
        # `sbatch` IS the detachment: it returns as soon as the job is queued.
        place = batch._from_submission( _shell( where, f"{mkdir} && {line}" ), kind = "batch" )
    elif where.ssh is None:
        log.parent.mkdir( parents = True, exist_ok = True )
        with open( log, "wb" ) as out:
            child = subprocess.Popen( [ "sh", "-c", line ], cwd = root, stdout = out, stderr = subprocess.STDOUT,
                                      stdin = subprocess.DEVNULL, start_new_session = True )
        place = { "kind": "local", "handle": str( child.pid ), "log": str( log ) }
    else:
        # Let go over there: its own session, its output in a file, its pid said back.
        got = _shell( where, f"{mkdir} && nohup sh -c {shlex.quote( line )} > {shlex.quote( remote_log )} 2>&1 "
                             f"< /dev/null & echo ERRAND_PID=$!" )
        found = re.search( r"ERRAND_PID=(\d+)", got.stdout or "" )
        place = ( { "kind": "ssh", "handle": found.group( 1 ) } if found else
                  { "kind": "failed", "handle": "", "error": ( got.stderr or got.stdout or "" ).strip()[ : 400 ] } )
    if where.ssh is not None:
        place.update( host = where.ssh.host, remote_root = str( where.there ), options = list( where.ssh.options ),
                      log = remote_log )
    return place


def _shell( where, line: str ):
    """A line on the machine the project is on, its output captured."""
    if where.ssh is None:
        return subprocess.run( [ "sh", "-c", line ], cwd = where.root, capture_output = True, text = True )
    return L.Over( where.ssh, where.there ).shell( line, capture = True )
