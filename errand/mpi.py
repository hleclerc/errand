"""Several processes of one entry: `test( …, ranks = 4 )`, or `--ranks 4`.

errand itself runs once, in the place. An entry that asks for ranks is not
imported there: the launcher of the place ( `mpiexec -n 4`, see `layers.Mpi` )
starts `python -m errand.mpi` once per rank, and each rank imports the file and
runs the body of that one entry, as a run in process would -- the same
parameters, the same `sys.argv`, the same directory. So the body is the
program of one rank: `from mpi4py import MPI` and `MPI.COMM_WORLD` inside it,
and nothing to write around it.

What came of it is what came of every rank: each one writes its own
`rank-<r>.json` beside `output.txt`, and the entry fails when one rank failed,
is skipped when they all skipped. The results are rank 0's. A rank that fails
while the others wait for it in a collective would leave them waiting for ever,
so it aborts the world ( `MPI.COMM_WORLD.Abort` ) once its record is written,
when mpi4py is loaded.

The rank is read from the variables the launchers set, so neither errand nor a
file that only says `ranks = 4` needs mpi4py to be started.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# What MPICH / Hydra, Open MPI, PMIx and srun call the rank, and the size.
RANK_VARS = ( "PMI_RANK", "OMPI_COMM_WORLD_RANK", "PMIX_RANK", "SLURM_PROCID" )
SIZE_VARS = ( "PMI_SIZE", "OMPI_COMM_WORLD_SIZE", "SLURM_NTASKS" )

# How a rank is told what to run: the resolved parameters and the target's
# arguments, as JSON ( a value may hold a comma, a space, anything ).
RESOLVED = "ERRAND_RANK_PARAMS"
ARGV     = "ERRAND_RANK_ARGV"
# Set for the ranks: an errand started inside one does not start ranks of its own. Not the launchers'
# variables, which errand itself has under `srun` ( `SLURM_PROCID=0` ) without being a rank of anything.
RANKED   = "ERRAND_RANKED"

# The variables by which a launcher recognizes a batch allocation errand has no launcher for, and the PMI
# of a step: without them `mpiexec` starts the ranks here, on the cores errand was given -- one node.
ALLOCATION = ( "PBS_", "LSB_", "FLUX_", "OAR_", "PMI_", "PMIX_", "OMPI_" )

# Inside a Slurm job, `srun` starts the ranks, on every node of the allocation. What it must not inherit
# is the step errand itself runs in ( one task, its cores, its binding ): everything but the job's own.
SLURM_JOB = ( "SLURM_JOB_", "SLURM_CONF", "SLURM_CLUSTER_NAME" )
# What the allocation was asked per task, said again to the step of the ranks: ( variable, flag )
SLURM_PER_TASK = ( ( "SLURM_NTASKS_PER_NODE", "--ntasks-per-node" ), ( "SLURM_CPUS_PER_TASK", "--cpus-per-task" ),
                   ( "SLURM_GPUS_PER_TASK", "--gpus-per-task" ), ( "SLURM_MEM_PER_CPU", "--mem-per-cpu" ) )


def _first( names ):
    for n in names:
        if os.environ.get( n, "" ).isdigit():
            return int( os.environ[ n ] )
    return None


def rank( ) -> int | None:
    """This process's rank, when it was started by an MPI launcher."""
    return _first( RANK_VARS )


def size( ) -> int | None:
    return _first( SIZE_VARS )


def inside( ) -> bool:
    """Whether this process is one of the ranks errand started."""
    return bool( os.environ.get( RANKED ) )


def ranks_of( resources: dict, asked: dict ) -> int:
    """How many processes: the command line's `--ranks` wins over the entry's own."""
    n = asked.get( "ranks" ) or resources.get( "ranks" ) or 1
    return int( n )


def _mpiexec( ):
    # the MPI of the environment first: the one mpi4py was built against
    return shutil.which( "mpiexec", path = os.path.dirname( sys.executable ) ) or shutil.which( "mpiexec" )


def _shown( argv ) -> str:
    """A command as said to the user: without the `env -u …` in front."""
    i = 1 if argv and argv[ 0 ] == "env" else 0
    while i and i < len( argv ) and argv[ i ] == "-u":
        i += 2
    return " ".join( str( a ) for a in argv[ i : ] )


def _unset( names ) -> list:
    names = sorted( names )
    return [ "env", *( a for k in names for a in ( "-u", k ) ) ] if names else [ ]


def plugin( ) -> str:
    """The PMI `srun` speaks to the ranks: the one the MPI of the environment understands."""
    exe = _mpiexec()
    here = os.path.dirname( exe ) if exe else os.path.dirname( sys.executable )
    return "pmix" if os.path.exists( os.path.join( here, "ompi_info" ) ) else "pmi2"


def _srun( stack, n: int, exe: str ) -> list:
    """`srun` starting `n` ranks over the whole allocation, without the variables of the step errand runs in."""
    from . import layers as L
    slurm = L.batch_of( stack )
    nodes = os.environ.get( "SLURM_JOB_NUM_NODES", "" )
    flags = [ a for var, flag in SLURM_PER_TASK if os.environ.get( var ) for a in ( flag, os.environ[ var ].split( "(" )[ 0 ] ) ]
    return [ *_unset( k for k in os.environ
                      if k.startswith( ( "SLURM_", "PMI_", "PMIX_" ) ) and not k.startswith( SLURM_JOB ) ),
             exe, "--overlap", f"--mpi={getattr( slurm, 'mpi', None ) or plugin()}",
             *( [ "--nodes", str( min( int( nodes ), n ) ) ] if nodes.isdigit() else [ ] ), *flags, "--ntasks", str( n ) ]


def outside( stack, n: int ) -> list | None:
    """The launcher of a place whose ranks start OUTSIDE its container, or None.

    In a container, errand runs inside it, and so would the launcher: `srun` is
    not in an image, and a `mpiexec` of the image starts every rank on one node.
    So when the stack names its launcher before the container -- a Slurm
    allocation, or an `Mpi` layer -- the ranks are started out there, each
    entering the container on its own ( `srun … apptainer exec image python …` ),
    the MPI of the image speaking to the launcher's PMI. An `Mpi` after the
    container is the image's own, and starts the ranks inside it."""
    from . import layers as L
    box = next( ( i for i, l in enumerate( stack ) if isinstance( l, L.Container ) ), None )
    if box is None:
        return None
    mpi = L.mpi_of( stack )
    if mpi is not None:
        return [ mpi.launcher, mpi.np, str( n ), *mpi.flags ] if stack.index( mpi ) < box else None
    slurm = L.batch_of( stack )
    if slurm is not None and stack.index( slurm ) < box and os.environ.get( "SLURM_JOB_ID" ):
        return _srun( stack, n, "srun" )
    return None


def launcher( stack, n: int, place: dict | None = None ) -> list | None:
    """The command that starts `n` processes in this place, or None when there is none.

    `place`: `{ "env": name, "tags": { … } }`, what a launcher outside a container
    needs to enter it again for each rank ( see `outside` )."""
    from . import layers as L
    stack = stack or [ ]
    out = outside( stack, n )
    if out is not None:
        return _relay( out, place )
    mpi = L.mpi_of( stack )
    if mpi is not None:
        exe = mpi.launcher
        found = shutil.which( exe ) or ( exe if os.sep in exe else None )
        return [ found, mpi.np, str( n ), *mpi.flags ] if found else None
    if os.environ.get( "SLURM_JOB_ID" ) and shutil.which( "srun" ):
        return _srun( stack, n, shutil.which( "srun" ) )
    exe = _mpiexec()
    if exe is None:
        return None
    return [ *_unset( k for k in os.environ if k.startswith( ALLOCATION ) ), exe, "-n", str( n ) ]


# ── outside the container ───────────────────────────────────────────────────

# The agent outside the layers errand runs in, which started the bridge of its own agent ( `Agent.outer` ):
# the allocation's node agent under Slurm, the host agent over ssh.
OUTER = "ERRAND_OUTER_AGENT_DIR"
# Said to the launcher out there, which has its own environment otherwise: errand's variables, and the
# path errand and the project's sources are found on. Not the container's PATH, nor its libraries.
FORWARDED = ( "PYTHONPATH", "PYTHONUNBUFFERED" )
NOT_FORWARDED = ( "ERRAND_AGENT_DIR", "ERRAND_AGENT_KEEP", "ERRAND_AGENT_PID", OUTER, "ERRAND_PROC_DIR" )


def _relay( start: list, place: dict | None ) -> list:
    """The prefix that has the outer agent start `start`, each rank entering the layers again ( `through` )."""
    from . import local
    from .agents import endpoint
    outer = os.environ.get( OUTER )
    # In a job errand submitted, the agent was started on the node just before the container: it may
    # still be on its way.
    import time
    deadline = time.monotonic() + 20
    while outer and endpoint.reach( Path( outer ) ) is None and time.monotonic() < deadline:
        time.sleep( 0.2 )
    if not outer or endpoint.reach( Path( outer ) ) is None:
        raise local.Skipped( "the ranks start outside the container, and no errand agent is there to start them",
                             "it is the allocation's agent under Slurm, the host's over ssh: an `apptainer exec` "
                             "with --cleanenv or --containall hides it ( or put an `errand.Mpi` after the "
                             "container: the ranks then start inside it, on one node )" )
    if place is None:
        raise ValueError( "a launcher outside a container needs the place ( env, tags ) to enter it again" )
    spec = { "outer": outer, "start": start, "env": place[ "env" ], "tags": dict( place.get( "tags" ) or { } ) }
    return [ sys.executable, "-m", "errand.mpi", "through", json.dumps( spec ) ]


def after_outer( stack ) -> list:
    """The layers between the outer agent and the work: after the allocation, else after the gateway;
    the launcher itself not among them."""
    from . import layers as L
    cut = max( ( i + 1 for i, l in enumerate( stack ) if L.is_scheduler( l ) or isinstance( l, L.Gateway ) ), default = 0 )
    return [ l for l in stack[ cut : ] if not isinstance( l, L.Launcher ) ]


def through( spec: dict, payload: list ) -> int:
    """Run in the container: has the outer agent start `start` + `payload` through the layers again, and
    relays its output and its exit code. Stopped, it stops what it started out there."""
    import signal
    import socket
    from . import config, layers as L
    from .agents import client as C, endpoint, frames as F
    root = Path.cwd()
    config.load( root, warn = lambda m: None )
    env = config.envs.get( spec[ "env" ] )
    stack = env.stack_for( "run" ) if env is not None else [ ]
    ctx = L.Context( root = root, tags = spec[ "tags" ], remote = L.ssh_of( stack ) is not None )
    cmd = L.compose( after_outer( stack ), L.Command( list( payload ) ), ctx )
    sent = { k: v for k, v in os.environ.items()
             if k in FORWARDED or ( k.startswith( "ERRAND_" ) and k not in NOT_FORWARDED ) }
    argv = [ *spec[ "start" ], *cmd.argv ]
    sock = endpoint.reach( Path( spec[ "outer" ] ) )
    if sock is None:
        print( f"errand: the agent outside the container ( {spec[ 'outer' ]} ) does not answer", file = sys.stderr )
        return 1
    print( f"  $ {_shown( argv )}   ( outside the container )", flush = True )
    conn = C.Connection( sock.recv, sock.sendall, lambda: sock.shutdown( socket.SHUT_RDWR ) )
    call = conn.open( { "op": "spawn", "argv": argv, "cwd": str( root ), "env": { **sent, **cmd.env }, "keep": False } )
    call.reply()
    call.send( F.EOF )

    def interrupted( signum, frame ):
        raise KeyboardInterrupt
    signal.signal( signal.SIGTERM, interrupted )
    stopping = False
    while True:
        try:
            kind, data = call.next()
        except KeyboardInterrupt:
            if not stopping:
                C.stop( call )             # the agent out there stops the launcher and every rank
                stopping = True
            continue
        if kind is None:
            print( "errand: the connection to the agent outside the container was lost", file = sys.stderr )
            return 1
        if kind in ( F.OUT, F.ERR ):
            view = memoryview( data )
            while view:
                view = view[ os.write( 1 if kind == F.OUT else 2, view ) : ]
        elif kind == F.EXIT:
            return int( F.load( data ).get( "code", 1 ) )


# ── the side that launches ──────────────────────────────────────────────────

def run( e, *, n: int, stack, root: Path, leaf: Path, resolved: dict, argv: list, env: dict, place = None ):
    """Runs the entry `e` on `n` ranks. -> ( status, error, hint, results ).

    The ranks' output goes to stdout as it comes ( the caller captures it into
    `output.txt` ), each line after its rank."""
    from . import local
    start = launcher( stack, n, place )
    if start is None:
        raise local.Skipped( f"needs an MPI launcher for {n} ranks",
                             "install one in the environment ( micromamba install -c conda-forge mpich mpi4py ), "
                             "or name it: errand.Mpi( \"mpirun\" ) in its stack" )
    for old in leaf.glob( "rank-*.json" ):
        old.unlink()
    here = str( Path( __file__ ).resolve().parent.parent )          # errand itself, wherever it is
    path = os.pathsep.join( p for p in ( env.get( "PYTHONPATH" ) or os.environ.get( "PYTHONPATH" ), here ) if p )
    child = { **os.environ, **env, "PYTHONPATH": path, "PYTHONUNBUFFERED": "1",
              RESOLVED: json.dumps( resolved ), ARGV: json.dumps( argv ), RANKED: "1" }
    cmd = [ *start, sys.executable, "-m", "errand.mpi", str( e.file ), e.at, str( root ), str( leaf ) ]
    if "through" not in start[ 1 : 4 ]:            # the relay says its own
        print( f"  $ {_shown( start )} …", flush = True )
    proc = subprocess.Popen( cmd, cwd = str( root ), env = child, text = True, errors = "replace",
                             stdout = subprocess.PIPE, stderr = subprocess.STDOUT )
    for line in proc.stdout:
        sys.stdout.write( line )
        sys.stdout.flush()
    code = proc.wait()
    return gather( leaf, n, code )


def gather( leaf: Path, n: int, code: int ):
    """What the ranks wrote, as one outcome."""
    got = { }
    for r in range( n ):
        try:
            got[ r ] = json.loads( ( leaf / f"rank-{r}.json" ).read_text() )
        except ( OSError, ValueError ):
            pass
    results = got.get( 0, { } ).get( "results", { } )
    failed = [ ( r, g ) for r, g in sorted( got.items() ) if g[ "status" ] == "FAIL" ]
    if failed:
        r, g = failed[ 0 ]
        more = f" ( and {len( failed ) - 1} other rank{'s' if len( failed ) > 2 else ''} )" if len( failed ) > 1 else ""
        return "FAIL", f"rank {r}: {g[ 'error' ]}{more}", None, results
    missing = [ r for r in range( n ) if r not in got ]
    if missing:
        which = ", ".join( map( str, missing[ : 8 ] ) ) + ( "…" if len( missing ) > 8 else "" )
        return "FAIL", f"rank{'s' if len( missing ) > 1 else ''} {which} said nothing ( launcher exit {code} )", None, results
    if all( g[ "status" ] == "SKIP" for g in got.values() ):
        return "SKIP", got[ 0 ][ "error" ], got[ 0 ].get( "hint" ), results
    if code != 0:
        return "FAIL", f"launcher exit {code}", None, results
    return "PASS", None, None, results


# ── the side of one rank ────────────────────────────────────────────────────

class _Prefixed:
    """A stream whose lines start with the rank: several ranks write to one output."""

    def __init__( self, stream, prefix ):
        self.stream, self.prefix, self.fresh = stream, prefix, True

    def write( self, text ):
        out = [ ]
        for piece in text.splitlines( keepends = True ):
            out.append( ( self.prefix if self.fresh else "" ) + piece )
            self.fresh = piece.endswith( "\n" )
        self.stream.write( "".join( out ) )
        return len( text )

    def __getattr__( self, name ):
        return getattr( self.stream, name )


def main( argv = None ):
    from . import discovery, entries as E, local

    argv = argv or sys.argv[ 1 : ]
    if argv[ : 1 ] == [ "through" ]:
        return through( json.loads( argv[ 1 ] ), argv[ 2 : ] )
    file, line, root, leaf = argv[ : 4 ]
    root, leaf = Path( root ), Path( leaf )
    r, n = rank() or 0, size() or 1
    if n > 1:
        sys.stdout = _Prefixed( sys.stdout, f"[{r}] " )
        sys.stderr = _Prefixed( sys.stderr, f"[{r}] " )

    status, error, hint = "PASS", None, None
    try:
        entries, modules = discovery.select_at( Path( file ), line, root )
        if not entries:
            raise RuntimeError( f"no entry at {file}:{line}" )
        e = entries[ 0 ]
        E.begin_run( e, json.loads( os.environ.get( RESOLVED, "{}" ) ), leaf )
        sys.argv = [ str( e.file ), *json.loads( os.environ.get( ARGV, "[]" ) ) ]
        discovery.import_file( modules[ e.module ], root )
    except local.Skipped as s:
        status, error, hint = "SKIP", s.reason, s.hint
    except KeyboardInterrupt:
        raise
    except BaseException as exc:                    # SystemExit included, as in process
        status, error = "FAIL", f"{type( exc ).__name__}: {exc}"
        from .cli.tracebacks import print_failure
        print_failure( exc )

    record = { "status": status, "error": error, "hint": hint,
               "results": dict( E.results ) if r == 0 else { } }
    try:
        ( leaf / f"rank-{r}.json" ).write_text( json.dumps( record, default = str ) )
    except OSError:
        pass
    sys.stdout.flush()
    sys.stderr.flush()
    if status == "FAIL" and n > 1 and "mpi4py.MPI" in sys.modules:
        # the others may be waiting for this one in a collective
        sys.modules[ "mpi4py.MPI" ].COMM_WORLD.Abort( 1 )
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit( main() )
