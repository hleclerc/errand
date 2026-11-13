# Slurm

```python
Slurm( partition = None, nodes = None, cpus = None, gpus = None,
       time = None, account = None, nodelist = None, qos = None, watch = None,
       ntasks_per_node = None, mpi = None, extra = [ ], keep_alive = None )
```

`srun` while you wait, `sbatch` under [`--batch`](../detached) — which *is* the detachment: it
returns as soon as the job is queued.

Not an interpreter-selecting layer: it puts the command inside an allocation and leaves it otherwise
alone, so it stacks in front of a container or an environment exactly as `Ssh` does in front of it.

**Everything is optional, `partition` included.** What is not stated is not passed, and Slurm then
applies its own default — which is the right answer far more often than a partition name copied out
of somebody else's script: the cluster already knows which one is the default, and it is the one
that stays correct when the cluster is rearranged.

```python
# errand-envs.py
import errand

errand.envs[ "cluster" ] = errand.Env( [ errand.Ssh( host = "login.hpc", root = "/home/me/proj" ),   # NOT /tmp
                                         errand.Slurm( time = "2:00:00" ) ] )                        # the default partition
```

::: danger The root must be on a shared filesystem
A batch job runs on a compute node, and `/tmp` there is not the `/tmp` you pushed to. The job lands
somewhere that has never heard of your project, and says so in terms of a failed `chdir` followed by
an import error, neither of which points at the cause. errand checks for this before submitting and
tells you plainly.
:::

## What the work asks for

errand does not queue on top of a batch system: what the work asks for is **handed over** instead.

| declared | from the work | flag |
|---|---|---|
| `cpus` | `cpus = 4` | `--cpus-per-task` |
| `gpus` | `gpus = 1` | `--gpus` |
| — | `ram = "8G"` | `--mem` |
| — | `exclusive = True` | `--exclusive` |

**What the environment states explicitly wins**: whoever wrote `Slurm( cpus = 16 )` knew something
about that partition an entry cannot. A dispatched command carries several entries, so the
allocation is the largest of them, and exclusive if any one of them is. `--cpus`, `--gpus`, `--ram`
and `--ranks` on the command line count as what the work asks for.

## The other fields

`nodelist` pins the allocation to named nodes ( `--nodelist` ): a string as Slurm reads it
( `"node15"`, `"node[1-4]"` ) or a list of names.

`time` is the environment's; `--time` on the command line wins over it, for one command that
needs longer. `qos` is a name, or a function of the time asked ( in seconds ) that gives one, for a
cluster whose qos depends on how long the job is:

```python
Slurm( time = "00:20:00", qos = lambda s: "qos_dev" if s <= 2 * 3600 else "qos_long" )
```

`extra` is appended verbatim, for whatever your site needs that nothing above covers — except
the number of tasks ( `--ntasks`, `-n`, `--ntasks-per-node` ), which is refused: errand itself
would be started that many times.

## Several ranks

How many processes is the work's to say ( `--ranks 8`, or `ranks = 8` on an entry ), never the
environment's: `--ntasks` is not a field, it is the number of ranks. What the environment says is
where they go:

| declared | flag | |
|---|---|---|
| `nodes` | `--nodes` | how many nodes |
| `ntasks_per_node` | `--ntasks-per-node` | how the ranks spread over them |
| `mpi` | `srun --mpi=` | the PMI the ranks are started with; by default the one the MPI of the environment speaks: `pmix` for Open MPI, `pmi2` for MPICH |

With ranks, what the work asks for is per rank: `cpus` → `--cpus-per-task`, `gpus` →
`--gpus-per-task`, `ram` → `--mem-per-cpu`, with `--ntasks` the number of ranks — and the
environment's own `cpus` and `gpus` are per rank too.

errand runs once in that allocation, as one task on its first node ( `salloc … srun --nodes 1
--ntasks 1 --overlap`, or the batch script under `--batch` ), and starts the ranks with an `srun` of
its own, over the whole allocation, without the variables of the step it runs in. The preparation
stays one task.

```python
errand.envs[ "two-nodes" ] = errand.Env( [ errand.Ssh( host = "login.hpc", root = "/scratch/me/proj" ),
                                           errand.Slurm( nodes = 2, ntasks_per_node = 4, time = "1:00:00" ),
                                           errand.Micromamba( "dist", packages = [ "mpi4py", "mpich" ] ) ] )
```

## Waiting from afar: `watch`

`srun` waits over the connection that started it, for the whole time in the queue and then in the
job. Where that connection does not last as long ( a chain of ssh hops cut after two hours ),
`watch = 300` waits differently: the job is submitted with `sbatch`, and then asked about every
5 minutes at most — sooner at first, the intervals doubling from 10 s — each time over a connection
of its own. What it writes is shown as it comes, and errand returns with its return code once it is
over, having brought back what the run wrote, as it would after `srun`.

- A connection that drops loses one question, never the job.
- ctrl-C cancels the job, as it would cancel an `srun`.
- A job killed by slurm ( its time ran out, it was cancelled ) fails, with slurm's word for why.
- It is one job: preparing and running happen in the same allocation, sized from what the layer
  declares rather than from the plan — so it needs a `time`, here or
  from `--time`, rather than the partition's default, which is its longest more often than not.
- `--batch` still lets go at once, and `errand shell` still goes through `srun`.

A command run inside the job that calls errand again ( a script driving many runs ) is inside
that environment already, and runs there directly: one allocation for all of it.

## Held warm: `keep_alive`

```python
errand.Slurm( nodelist = [ "node15", "node17" ], nodes = 2, ntasks_per_node = 4,
              time = "4:00:00", keep_alive = "30m" )
```

The first command submits a job that holds the allocation, and the commands that follow within
`keep_alive` run in it at once: no queue, no new job. A run that took the queue's minutes takes a
second.

Without `keep_alive`, the allocation is held for **one minute**: long enough for the run to find the
allocation its preparation had, and for the next command typed right after. One `errand run` is then
one job, not one for the preparation and one for the run. `keep_alive = 0` asks for a job per
command, as `srun` alone would; `watch` is one job of its own, and is never held.

The allocation is named after the machine and the declaration, not after the environment. Two
environments that go through the same `Ssh` and the same `Slurm` and then differ ( a venv, a
container ) share it, each with an environment agent of its own in it.

The job's batch step is an agent, on the first node. The layers after `Slurm` are entered once, by an
environment agent it starts, and are built there too. A venv or an environment in a node's local
`/tmp` is built on that node. An entry's ranks are started from that first node with the allocation's
own `srun`. The allocation is sized from what is declared, since it outlives the command that started
it: ranks fit when `nodes × ntasks_per_node` is enough for them.

A command runs in it only if it fits: its ranks within the allocation's tasks, its cores and cards
per task within those declared, `exclusive` only if the allocation is, its `--time` within what the
job has left. Otherwise it gets a job of its own, sized for it, and the warm allocation is given back
first if nothing runs in it, since it may hold the very nodes. No `srun` ever asks more than was
allocated.

Once nothing has used it for `keep_alive`, the agent goes, the job ends, and the allocation is
released; at the latest, its `time` releases it. On a cluster other people share, a short
`keep_alive` is the polite one. Nothing has to be remembered, and nothing stays
held by mistake. Its job and its directory are in `~/.cache/errand/alloc/` ( or `$ERRAND_CACHE_DIR/alloc/` ) on the cluster, and go
with the job.
→ [Fast, and nothing lost](../agents)

## Preparing and running: two allocations

The preparation — resolving targets, building, collecting — runs in the allocation held warm, as the
run does: one job for both. When they want different allocations, they are two `Slurm` layers with a
[`when`](./index#when) each, each held warm on its own; `when = "phase=run"` alone prepares on the
machine `Ssh` leads to, with no allocation at all. See
[Preparing, then running](../environments#preparing-then-running).

## Inside an allocation, errand does not queue

Inside a Slurm, PBS, OAR, LSF, SGE or Flux allocation, `errand` does not take a claim in
[the queue](../machine): the scheduler has already decided what this process may have, and a second
queue on top of it would only wait for itself. Slurm is the only batch system with a layer of its own
so far; the others are recognized, not driven.

