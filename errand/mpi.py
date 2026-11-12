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


def _unset( names ) -> list:
    names = sorted( names )
    return [ "env", *( a for k in names for a in ( "-u", k ) ) ] if names else [ ]


def plugin( ) -> str:
    """The PMI `srun` speaks to the ranks: the one the MPI of the environment understands."""
    exe = _mpiexec()
    here = os.path.dirname( exe ) if exe else os.path.dirname( sys.executable )
    return "pmix" if os.path.exists( os.path.join( here, "ompi_info" ) ) else "pmi2"


def launcher( stack, n: int ) -> list | None:
    """The command that starts `n` processes in this place, or None when there is none."""
    from . import layers as L
    stack = stack or [ ]
    mpi = L.mpi_of( stack )
    if mpi is not None:
        exe = mpi.launcher
        found = shutil.which( exe ) or ( exe if os.sep in exe else None )
        return [ found, mpi.np, str( n ), *mpi.flags ] if found else None
    if os.environ.get( "SLURM_JOB_ID" ) and shutil.which( "srun" ):
        slurm = L.batch_of( stack )
        nodes = os.environ.get( "SLURM_JOB_NUM_NODES", "" )
        flags = [ a for var, flag in SLURM_PER_TASK if os.environ.get( var ) for a in ( flag, os.environ[ var ].split( "(" )[ 0 ] ) ]
        return [ *_unset( k for k in os.environ
                          if k.startswith( ( "SLURM_", "PMI_", "PMIX_" ) ) and not k.startswith( SLURM_JOB ) ),
                 shutil.which( "srun" ), "--overlap", f"--mpi={getattr( slurm, 'mpi', None ) or plugin()}",
                 *( [ "--nodes", str( min( int( nodes ), n ) ) ] if nodes.isdigit() else [ ] ), *flags, "--ntasks", str( n ) ]
    exe = _mpiexec()
    if exe is None:
        return None
    return [ *_unset( k for k in os.environ if k.startswith( ALLOCATION ) ), exe, "-n", str( n ) ]


# ── the side that launches ──────────────────────────────────────────────────

def run( e, *, n: int, stack, root: Path, leaf: Path, resolved: dict, argv: list, env: dict ):
    """Runs the entry `e` on `n` ranks. -> ( status, error, hint, results ).

    The ranks' output goes to stdout as it comes ( the caller captures it into
    `output.txt` ), each line after its rank."""
    from . import local
    start = launcher( stack, n )
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
    cmd = [ *start, sys.executable, "-m", "errand.mpi", str( e.file ), str( e.line ), str( root ), str( leaf ) ]
    i = 1 if start[ 0 ] == "env" else 0
    while i and start[ i ] == "-u":
        i += 2
    print( f"  $ {' '.join( start[ i: ] )} …", flush = True )
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
    import traceback
    from . import discovery, entries as E, local

    file, line, root, leaf = ( argv or sys.argv[ 1 : ] )[ : 4 ]
    root, leaf = Path( root ), Path( leaf )
    r, n = rank() or 0, size() or 1
    if n > 1:
        sys.stdout = _Prefixed( sys.stdout, f"[{r}] " )
        sys.stderr = _Prefixed( sys.stderr, f"[{r}] " )

    status, error, hint = "PASS", None, None
    try:
        entries, modules = discovery.select_at( Path( file ), int( line ), root )
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
        traceback.print_exc()

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
