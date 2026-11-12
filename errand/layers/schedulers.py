"""Schedulers: a Slurm allocation, waited for ( `srun` ), submitted ( `sbatch` ) or asked about from afar
( `watch_job` ), and `run_on`, which picks between them.
"""
from __future__ import annotations

import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field

from .base import Command, compose, Context
from .families import batch_of, Scheduler


@dataclass
class Slurm( Scheduler ):
    """A batch allocation. `srun` while you wait, `sbatch` under `--batch`.

    Not an interpreter-selecting layer: it puts the command inside an
    allocation and leaves it otherwise alone, so it stacks in front of a
    container or an environment exactly as `Ssh` does in front of it.

    EVERYTHING IS OPTIONAL, `partition` included. What is not stated is not
    passed, and Slurm then applies its own default -- which is the right answer
    far more often than a partition name copied out of somebody else's script:
    the cluster already knows which one is the default, and it is the one that
    stays correct when the cluster is rearranged.
    """
    partition: str | None = None     # None: the cluster's own default partition
    nodes    : int | None = None
    cpus     : int | None = None
    gpus     : int | None = None
    time     : str | None = None
    account  : str | None = None
    nodelist : str | list | None = None   # `node15`, `node[1-4]` or [ "node15", "node16" ]
    # A name, or a function of the time asked ( in seconds ) giving one: the clusters whose qos is a matter
    # of how long the job is
    qos      : object = None
    # Waiting through `sbatch` rather than `srun`: the job is submitted, then asked how it is going every
    # `watch` seconds at most, each time over a connection of its own ( see `watch_job` ). For a cluster that
    # does not keep a connection open as long as the queue and the job last. It sizes the job from what is
    # declared here, and needs a time ( here, or `--time` ).
    watch    : float | None = None
    # How the ranks of an entry that asks for several ( `--ranks 8` ) are spread over the nodes:
    # `--ntasks-per-node`. Their number is the entry's, never the environment's.
    ntasks_per_node: int | None = None
    # The plugin `srun` starts the ranks with ( `srun --mpi=` ). None: the one the MPI of the environment
    # speaks -- `pmix` for Open MPI, `pmi2` for MPICH ( see `errand.mpi` ).
    mpi      : str | None = None
    extra    : list = field( default_factory = list )
    when     : str | None = None
    # Held warm between commands ( "30m" ): one allocation, an agent on its first node, and every command
    # of that time runs in it -- no queue, no new job ( ADR 0005, step 6 ). Released once nothing used it
    # for that long, or at its `time`.
    keep_alive: str | float | None = None

    # The flags that say how many processes the job starts: errand runs once in the allocation, and
    # starts the ranks itself. `-n4` and `--ntasks=4` are the same flag.
    TASK_FLAGS = ( "--ntasks", "-n", "--ntasks-per-node" )

    def __post_init__( self ):
        for flag in self.extra:
            word = str( flag ).split( "=" )[ 0 ]
            if word in self.TASK_FLAGS or ( word.startswith( "-n" ) and word[ 2: ].isdigit() ):
                raise ValueError(
                    f"Slurm( extra = [ {flag!r} ] ): how many processes is the work's to say -- `--ranks 8` on the "
                    f"command line, or `ranks = 8` on the entry -- and how they spread over the nodes is "
                    f"`Slurm( ntasks_per_node = … )`. With that flag, errand itself would be started several times." )

    def flags( self, ctx: Context | None = None ):
        """What was declared, filled in from what the work asks for.

        A batch system is a queue that already exists, so errand does not hold
        a second one on top of it -- it hands the numbers over instead. What
        the environment states explicitly always wins: the person who wrote
        `cpus = 16` knew something about the partition that the entry does not.
        """
        # Preparing is one process, sized from nothing: the entries it would be
        # sized from are what it is about to find out.
        prepare = ctx is not None and ctx.phase == "prepare"
        needs = { } if prepare else ( ( ctx.needs if ctx else { } ) or { } )
        cpus = self.cpus if self.cpus is not None else needs.get( "cpus" )
        gpus = self.gpus if self.gpus is not None else needs.get( "gpus" )
        ram  = needs.get( "ram" )
        # the time asked for this command ( `--time` ) wins over the environment's
        time = ( ( ctx.needs if ctx else { } ) or { } ).get( "time" ) or self.time
        qos  = self.qos( slurm_seconds( time ) if time else None ) if callable( self.qos ) else self.qos

        # Several ranks: one task each, and what the entry asks for is what ONE rank needs
        ranks = int( needs.get( "ranks" ) or 1 )
        many  = ranks > 1
        out = [ ]
        for flag, value in ( ( "--partition", self.partition ),
                             ( "--nodes", 1 if prepare and self.nodes else self.nodes ),
                             ( "--ntasks", 1 if prepare else ranks if many else None ),
                             ( "--ntasks-per-node", self.ntasks_per_node if many else None ),
                             ( "--cpus-per-task", cpus ), ( "--gpus-per-task" if many else "--gpus", gpus ),
                             ( "--time", time ), ( "--account", self.account ), ( "--qos", qos ),
                             ( "--nodelist", self._nodelist() ) ):
            if value is not None:
                out += [ flag, str( int( value ) if isinstance( value, float ) else value ) ]
        if ram and many:
            out += [ "--mem-per-cpu", f"{-( -int( ram ) // int( cpus or 1 ) )}M" ]
        elif ram:
            out += [ "--mem", f"{int( ram )}M" ]
        if needs.get( "exclusive" ):
            out += [ "--exclusive" ]
        return out + list( self.extra )

    def _nodelist( self ):
        if isinstance( self.nodelist, ( list, tuple ) ):
            return ",".join( self.nodelist ) or None
        return self.nodelist

    def watched( self, ctx: Context ) -> bool:
        """Waited for by submitting and asking, rather than by `srun`."""
        return bool( self.watch ) and not ctx.batch and not ctx.interactive

    def wrap( self, cmd: Command, ctx: Context ) -> Command:
        if ctx.batch:
            # `sbatch` IS the detachment: it returns as soon as the job is
            # queued. `--parsable` makes it print the id and nothing else.
            return Command( [ "sbatch", "--parsable", *self.flags( ctx ),
                              "--wrap", cmd.shell() ], { } )
        if self.watched( ctx ):
            flags = self.flags( ctx )
            if "--time" not in flags:
                # the job is sized from the declaration alone: the cluster's default time is
                # its longest more often than not, which is the queue's longest wait
                raise ValueError( "a watched slurm job needs a time: `--time 1:00:00`, "
                                  "or `time =` in the environment's Slurm( ... )" )
            # what `watch_job` reads: the output, then the return code, once it is over
            log = watch_dir( ctx )
            return Command( [ "sbatch", "--parsable", *flags, "--output", f"{log}/slurm-%j.out",
                              "--wrap", f"{cmd.shell()}; echo $? > {log}/slurm-$SLURM_JOB_ID.rc" ], { } )
        if int( ( ctx.needs or { } ).get( "ranks" ) or 1 ) > 1 and not ctx.interactive and ctx.phase != "prepare":
            # The allocation is for every rank, and errand runs in it once, as one task on the first node:
            # it starts the ranks with an `srun` of its own ( `errand.mpi` ), which the step it runs in
            # must not hold the cores of ( `--overlap` ).
            return Command( [ "salloc", *self.flags( ctx ), "srun", "--nodes", "1", "--ntasks", "1", "--overlap",
                              *cmd.argv ], cmd.env )
        return Command( [ "srun", *self.flags( ctx ), *( [ "--pty" ] if ctx.interactive else [ ] ),
                          *cmd.argv ], cmd.env )

    def describe( self ):
        nodes = self._nodelist()
        return f"slurm:{self.partition or 'default partition'}" + ( f"@{nodes}" if nodes else "" )


def slurm_seconds( time: str ) -> int:
    """`MM`, `MM:SS`, `HH:MM:SS`, `D-HH`, `D-HH:MM`, `D-HH:MM:SS`: slurm's ways of saying how long."""
    days, _, rest = str( time ).rpartition( "-" )
    parts = [ int( p ) for p in rest.split( ":" ) ]
    if days:
        parts += [ 0 ] * ( 3 - len( parts ) )          # after a day, the first number is hours
        h, m, s = parts
    else:
        h, m, s = { 1: [ 0, parts[ 0 ], 0 ], 2: [ 0, *parts ], 3: parts }[ len( parts ) ]
    return ( ( int( days or 0 ) * 24 + h ) * 60 + m ) * 60 + s


def watch_dir( ctx: Context ) -> str:
    """Where a watched job writes its output and return code, over there."""
    from .. import config
    return str( ctx.root / config.state_rel( ctx.root ) / "batch" )


def run_on( host, stack, cmd: Command, ctx: Context, echo = print ) -> int:
    """`cmd` through `stack`, from `host`: waited for as each layer waits, or,
    under a watched scheduler, submitted and then asked about ( `watch_job` )."""
    wrapped = compose( stack, cmd, ctx )
    sched = batch_of( stack )
    if not ( isinstance( sched, Slurm ) and sched.watched( ctx ) ):
        return host.shell( wrapped.shell(), tty = ctx.interactive ).returncode
    return watch_job( host, wrapped, watch_dir( ctx ), sched.watch, echo )


def watch_job( host, submit: Command, log: str, every: float, echo = print, first = 10.0,
               show = None, cancel = None ) -> int:
    """Submit, then ask how the job is going until it is over, and say how it went.

    Each question is a connection of its own, at growing intervals ( `first`
    seconds, doubling up to `every` ): a connection that drops loses one
    question, never the job. What the job writes is shown as it comes, and its
    return code is the one it wrote ( absent: killed -- the time ran out, it was
    cancelled -- and slurm's own account says which ).

    Interrupted here ( ctrl-C ), the job is cancelled, as `srun` would be -- or when
    `cancel` ( a threading.Event ) is set, for a caller that waits on a thread.
    `show( text )` takes what the job writes, as it comes ( default: printed ).
    """
    show = show or ( lambda text: print( text, end = "", flush = True ) )
    got = host.shell( f"mkdir -p {shlex.quote( log )} && {submit.shell()}", capture = True )
    lines = [ l.strip() for l in ( got.stdout or "" ).splitlines() ]
    job = next( ( l.split( ";" )[ 0 ] for l in reversed( lines ) if re.fullmatch( r"\d+(;\S+)?", l ) ), None )
    if got.returncode or job is None:
        echo( f"  could not submit: {( got.stderr or got.stdout or '' ).strip()[ -400 : ]}" )
        return got.returncode or 1
    out, rc = f"{log}/slurm-{job}.out", f"{log}/slurm-{job}.rc"
    echo( f"  slurm job {job}, asked about every {int( every )} s at most ( ctrl-C cancels it )" )

    shown, state, wait, lost = 0, None, first, False
    try:
        while True:
            if cancel is not None:
                if cancel.wait( wait ):
                    raise KeyboardInterrupt
            else:
                time.sleep( wait )
            wait = min( wait * 2, every )
            # one connection: the state, then what was written since the last time
            try:
                q = host.shell( f"squeue -h -j {job} -o '%T %N' 2>/dev/null; echo ERRAND_SEP; "
                                f"tail -c +{shown + 1} {out} 2>/dev/null", capture = True, timeout = 300 )
            except subprocess.TimeoutExpired:
                q = None
            if q is None or "ERRAND_SEP" not in ( q.stdout or "" ):
                if not lost:
                    echo( f"  ( cannot ask about job {job} right now: asking again later )" )
                lost = True
                continue
            lost = False
            now, _, text = q.stdout.partition( "ERRAND_SEP\n" )
            if text:
                show( text )
                shown += len( text.encode() )
            now = now.strip().splitlines()[ -1 ] if now.strip() else ""
            if now and now != state:
                echo( f"  job {job}: {now.lower()}" )
                state = now
            if not now:
                break
    except KeyboardInterrupt:
        host.shell( f"scancel {job}", quiet = True, timeout = 120 )
        echo( f"  job {job} cancelled" )
        return 130
    end = host.shell( f"tail -c +{shown + 1} {out} 2>/dev/null; echo ERRAND_RC=$( cat {rc} 2>/dev/null )",
                      capture = True, timeout = 300 )
    text, _, code = ( end.stdout or "" ).rpartition( "ERRAND_RC=" )
    if text:
        show( text )
    if code.strip().isdigit():
        return int( code.strip() )
    how = host.shell( f"sacct -n -X -P -j {job} -o State", capture = True, timeout = 120 )
    echo( f"  job {job} ended without a return code: {( how.stdout or '' ).strip() or 'killed'}" )
    return 1
