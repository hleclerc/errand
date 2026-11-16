"""A warm allocation ( ADR 0005, step 6 ): `Slurm( keep_alive = "30m" )` held between commands.

    login node        host agent ── the script below ── srun --overlap ──┐
    first node        node agent ( the job's batch step ) ── env agent ── sessions, ranks

The allocation is an `sbatch` job whose batch step IS an agent -- a bare one,
on the Python `bootstrap` finds there -- so it holds the allocation for as long
as it serves, and goes once nothing used it for `keep_alive`: the job ends,
the allocation is released, nobody has to remember to. The job and the agent's
directory are written under `~/.cache/errand/alloc/<name>/` ( or `$ERRAND_CACHE_DIR` ) on the cluster, and
go with the job: what sessions write is kept in the project ( `errand-outputs/state/procs/` ).

A command reaches that agent through the host agent of the login node: a
script that finds the job ( or submits it, and waits for it to run ), then
`srun --jobid --overlap` onto its first node, where the `connect` bridge meets
the agent. The environment agent is started by that node agent, through the
layers after the scheduler -- so they are inside the allocation, and built
there too ( `setup` asks `inside` ). An MPI entry's ranks are started from it
with the allocation's own `srun`.
"""
from __future__ import annotations

import hashlib
import shlex

from .. import agents, bootstrap, layers as L
from ..agents import arrival
from ..agents import upstream as U

ALLOC = "alloc"                   # in errand's per-user directory


def scheduler( stack ):
    """The scheduler of `stack` when its commands go through an allocation with an agent: always,
    unless it is watched ( `watch`: one job of its own, asked about from afar ). `keep_alive = 0`
    is an allocation for one command, given back as soon as it is over ( ADR 0009 )."""
    s = L.batch_of( stack )
    if s is None or getattr( s, "watch", None ) or not hasattr( s, "keep_alive" ):
        return None
    return s


def seconds( sched ) -> int:
    from ..vm.common import _seconds
    keep = sched.keep_alive if sched.keep_alive is not None else getattr( sched, "KEEP_WARM", "1m" )
    return int( _seconds( keep or 0 ) )


class Allocation:
    def __init__( self, env, tags, where, phase = "run", needs = None ):
        """`needs`: a command's own, for one that does not fit in the allocation of the declaration
        ( `fits` ): an allocation of its size, shared in turn by whatever fits in it."""
        from dataclasses import replace
        self.env, self.tags, self.where = env, tags, where
        stack = env.stack_for( phase, tags )
        declared = scheduler( stack )
        self.after = stack[ stack.index( declared ) + 1 : ]
        self.keep = seconds( declared )
        # What is asked of Slurm for the allocation, apart from the commands it serves
        # ( `Slurm( allocation = { "time": "2:00:00" } )` ): the qos is computed from it.
        sized = dict( getattr( declared, "allocation", None ) or { } )
        # A command's own allocation is of its size: what it needs wins over what is declared.
        sized.update( { k: needs[ k ] for k in ( "cpus", "gpus", "nodes" ) if ( needs or { } ).get( k ) } )
        self.sched = replace( declared, **sized ) if sized else declared
        # Sized from the declaration alone, in either phase: it outlives the command that started it,
        # and the run must find the allocation its preparation had. Ranks fit when
        # it says how many tasks: `nodes` times `ntasks_per_node`.
        n = ( self.sched.nodes or 0 ) * ( self.sched.ntasks_per_node or 0 )
        ctx = L.Context( root = where.there, tags = tags, remote = where.ssh is not None, phase = "run",
                         needs = { **( { "ranks": n } if n > 1 else { } ), **( needs or { } ) } )
        self.flags = self.sched.flags( ctx )
        # Named from what it is, not from the environment: another environment through the same
        # machine and the same declaration finds it, with an environment agent of its own in it.
        shape = f"{' '.join( self.flags )}\0{bootstrap.sources_key()}"
        self.name = f"{L.fingerprint( shape )}"
        self.cache = where.cache or str( bootstrap.local_cache() )
        self.dir = f"{self.cache}/{ALLOC}/{self.name}"
        self.boot = f"{self.cache}/{bootstrap.boot_rel()}" if where.ssh is not None else str( bootstrap.PACKAGE / "_boot.py" )

    def node_keep( self ) -> int:
        """How long the node agent stays unused: a share of `keep_alive`, a few seconds at 0."""
        return max( 30, self.keep // 4 ) if self.keep else 5

    def agent_keep( self ) -> int:
        return max( 5, self.keep )

    def _python( self, then: str ) -> str:
        """`sh -c '<find a python>; <then>'`: a bare python of the node, as a host agent's."""
        return " ".join( shlex.quote( a ) for a in ( "sh", "-c", bootstrap._script( then, "python3" ) ) )

    def script( self ) -> str:
        # The node agent waits little once nothing runs: what is used is the environment agent,
        # whose stream the hub closes after keep_alive -- then the allocation goes.
        # Once it went on its own, the job leaves nothing behind: its directory, its output, the
        # word that it was the one. A job that failed keeps its output, for the next command to say.
        d = shlex.quote( self.dir )
        # Nobody waits for it any more ( every waiter's lease is stale, ADR 0009 ): it goes at once.
        # What runs in it carves it in errand's queue of the node ( `ERRAND_ALLOCATION` ).
        # Nobody will read what it would say: it leaves nothing behind.
        serve = self._python( f'[ -n "$( find {d} -maxdepth 1 -name "wanted-*" -mmin -1 2>/dev/null )" ] || '
                              f'{{ [ "$( cat {d}/job 2>/dev/null )" = "$SLURM_JOB_ID" ] && rm -f {d}/job; '
                              f'rm -f {d}/slurm-"$SLURM_JOB_ID".out; rmdir {d} 2>/dev/null; exit 0; }}\n'
                              f'export ERRAND_ALLOCATION="$SLURM_JOB_ID"\n'
                              f'"$py" {shlex.quote( self.boot )} -m errand.agents serve '
                              f'{d}/"$SLURM_JOB_ID" {self.node_keep()} || exit $?\n'
                              f'rm -rf {d}/"$SLURM_JOB_ID" {d}/slurm-"$SLURM_JOB_ID".out\n'
                              f'[ "$( cat {d}/job 2>/dev/null )" = "$SLURM_JOB_ID" ] && rm -f {d}/job\n'
                              f'rmdir {d} 2>/dev/null; exit 0\n' )
        connect = self._python( f'exec "$py" {shlex.quote( self.boot )} -m errand.agents connect "$1" "$2"\n' )
        flags = " ".join( shlex.quote( f ) for f in self.flags )
        from ..agents.table import allocation_mark
        # Started through `rsh`, with no directory: its first line says whose it is, for `status`.
        mark = allocation_mark( project = str( self.where.there ), env = self.env.name, name = self.name )
        return f'''{mark}
{arrival.SHELL_WAITING}
d={d}; mkdir -p "$d"
# this command's lease: the allocation's agent leaves at once when nobody's is fresh ( ADR 0009 )
# ( a stop is a signal, which `sh` does not take as an EXIT )
touch "$d/wanted-$$"; trap 'rm -f "$d/wanted-$$"' EXIT; trap 'exit 1' INT TERM HUP
j=$( cat "$d/job" 2>/dev/null )
st=""; [ -n "$j" ] && st=$( squeue -h -j "$j" -o %T 2>/dev/null )
case "$st" in
    RUNNING|PENDING|CONFIGURING) ;;
    *)  rm -rf "$d"/[0-9]* "$d"/slurm-*.out          # what jobs before this one left
        j=$( sbatch --parsable {flags} --job-name errand-alive --output "$d/slurm-%j.out" --wrap {shlex.quote( serve )} ) || exit 1
        j=${{j%%;*}}; echo "$j" > "$d/job"
        echo "errand: holding an allocation for {self.env.name}: job $j ( released after {self.keep} s of nothing )" >&2 ;;
esac
said=""
until [ "$( squeue -h -j "$j" -o %T 2>/dev/null )" = RUNNING ] && [ -S "$d/$j/sock" ]; do
    st=$( squeue -h -j "$j" -o %T 2>/dev/null )
    if [ -z "$st" ]; then echo "errand: job $j is gone:" >&2; tail -5 "$d/slurm-$j.out" >&2 2>/dev/null; rm -f "$d/job"; exit 1; fi
    [ "$said" = "$st" ] || {{ echo "errand: job $j: $( echo "$st" | tr A-Z a-z )" >&2; waiting "slurm job $j $( echo "$st" | tr A-Z a-z ), held warm" "$j"; }}; said=$st
    # whoever started this loop ( sshd, an agent ) is gone: nobody waits any more ( sshd sends no
    # signal to a command without a terminal when its client goes )
    kill -0 "$PPID" 2>/dev/null || exit 1
    touch "$d/wanted-$$"
    sleep 2
done
rm -f "$d/wanted-$$"
arrived
node=$( scontrol show hostnames "$( squeue -h -j "$j" -o %N )" | head -1 )
# -u: srun holds a task's output back until a newline, and frames are not lines
exec srun -u --jobid="$j" --overlap -N1 -n1 -w "$node" {connect} sh "$d/$j" {self.agent_keep()}
'''

    def node_target( self ) -> dict:
        """The node agent, through the host agent of the machine `Ssh` leads to."""
        ssh = self.where.ssh
        line = f"sh -c {shlex.quote( self.script() )}"
        if ssh is None:
            argv = [ "sh", "-c", self.script() ]
        else:
            # a process of the login node's agent: `status` shows it, a stop reaches it ( ADR 0009 )
            argv = [ *U.rsh_argv( ssh.host, ssh.options, via = None ), ssh.host, line ]
        return { "kind": "cmd", "id": f"{ssh.host if ssh else 'here'}:alloc-{self.name}", "argv": argv,
                 "keep_alive": self.keep }

    def env_target( self ) -> dict:
        """The environment agent, started by the node agent through the layers after the scheduler."""
        ctx = L.Context( root = self.where.there, tags = self.tags, remote = True, phase = "run" )
        node = self.node_target()

        def line_for( where_ ):
            cmd = L.Command( [ "python", "-m", "errand.agents", "connect", where_, str( self.agent_keep() ) ] )
            sent = bootstrap.command( cmd, self.after, self.cache, "python3", boot = self.boot )
            return f"cd {shlex.quote( str( self.where.there ) )} && {L.compose( self.after, sent, ctx ).shell()}"

        digest = hashlib.sha1( line_for( "@" ).encode() ).hexdigest()[ : 10 ]
        # its directory is the job's: a socket of a job that is over must not be mistaken for this one's
        line = line_for( f"{self.dir}/JOB/env-{digest}" ).replace( f"{self.dir}/JOB/", f'{self.dir}/"$SLURM_JOB_ID"/' )
        argv = [ *U.rsh_argv_to( node ), "node", f'exec "${{SHELL:-/bin/sh}}" -ic {shlex.quote( line )}' ]
        return { "kind": "cmd", "id": f"{node[ 'id' ]}:env-{digest}", "argv": argv, "keep_alive": self.keep }

    def inside( self ):
        """Where the layers after the scheduler are built: in the allocation, by its node agent."""
        conn = agents.open( self.node_target() )
        return L.Context( root = self.where.there, tags = self.tags, remote = True, phase = "run",
                          host = NodeHost( conn, self.where.there ) )


class NodeHost:
    """`ctx.host` for a layer built inside the allocation: its lines run by the node agent."""
    remote = True

    def __init__( self, conn, root ):
        self.conn, self.root = conn, root

    def shell( self, line: str, *, quiet = False, tty = False, capture = False, input = None, timeout = None ):
        return agents.shell( self.conn, f"cd {shlex.quote( str( self.root ) )} && {line}", quiet = quiet,
                             capture = capture, input = input, timeout = timeout, login = True )

    def describe( self ):
        return "the allocation"


def _left( line: str ) -> int | None:
    """`squeue -o %L`: `D-HH:MM:SS`, `HH:MM:SS`, `MM:SS`, `UNLIMITED` -> seconds, None for no limit."""
    line = line.strip()
    if not line or line.upper() in ( "UNLIMITED", "NOT_SET", "INVALID" ):
        return None
    parts = line.split( "-" )
    days = int( parts[ 0 ] ) if len( parts ) == 2 else 0
    hms = [ int( x ) for x in parts[ -1 ].split( ":" ) ]
    while len( hms ) < 3:
        hms.insert( 0, 0 )
    return days * 86400 + hms[ 0 ] * 3600 + hms[ 1 ] * 60 + hms[ 2 ]


def fits( alloc: "Allocation", needs: dict, time = None, host = None ):
    """Can this command run in the allocation held warm, without going beyond it? -> ( yes, why not ).

    Its ranks within the allocation's tasks, its cores and cards per task within those declared,
    `exclusive` only in an exclusive one, its time within what the job has left -- or, with no job
    yet, within the time the job will be given. Never an `srun` that asks more than was allocated."""
    from ..layers import slurm_seconds
    s, needs = alloc.sched, needs or { }
    tasks = ( s.nodes or 1 ) * ( s.ntasks_per_node or 1 )
    ranks = int( needs.get( "ranks" ) or 1 )
    if ranks > tasks:
        return False, f"{ranks} ranks, {tasks} task{'s' if tasks > 1 else ''} allocated"
    for key, have in ( ( "cpus", s.cpus or 1 ), ( "gpus", s.gpus or 0 ) ):
        want = float( needs.get( key ) or 0 )
        if want > have:
            return False, f"{key}={want:g} per task, {have:g} allocated"
    if needs.get( "exclusive" ) and "--exclusive" not in alloc.flags:
        return False, "the machine to itself, in a shared allocation"
    if time:
        want = slurm_seconds( time )
        left = None
        if host is not None:
            got = host.shell( f'j=$( cat {shlex.quote( alloc.dir )}/job 2>/dev/null ) && '
                              f'squeue -h -j "$j" -o "%T %L" 2>/dev/null', capture = True )
            said = ( got.stdout or "" ).strip().split()
            if len( said ) == 2 and said[ 0 ] == "RUNNING":
                left = _left( said[ 1 ] )
        if left is None and s.time:
            left = slurm_seconds( s.time )
        if left is not None and want > left:
            return False, f"--time {time}, {left} s left in it"
    return True, None


def release_if_idle( alloc: "Allocation", host ) -> bool:
    """Give the allocation held warm back -- if nothing runs in it: a session that does is never cut."""
    d = shlex.quote( alloc.dir )
    got = host.shell( f'j=$( cat {d}/job 2>/dev/null ) || exit 0; '
                      f'for p in {d}/"$j"/env-*/proc/*/; do [ -d "$p" ] && [ ! -f "$p/exit" ] && exit 3; done; '
                      f'scancel "$j" && rm -f {d}/job && echo released', capture = True )
    return "released" in ( got.stdout or "" )
