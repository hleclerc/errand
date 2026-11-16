# 3 · A cluster, a Windows VM, and what is running

You have a laptop, an account on a Slurm cluster reached over ssh, and a Linux server in the lab.
You train on the cluster, and your C++ code must also build on Windows. This tutorial does both
from the laptop, then answers the question that follows: what is still running, and where?

::: info Written from the code
This walkthrough was written from errand's source, not recorded from a session. To reproduce it you
need a Slurm cluster, and a Linux x86-64 host with QEMU and KVM for the Windows VM. Sample outputs
are illustrative: their format is the one errand prints, the names and numbers are made up.
:::

## The places

```python
# errand-envs.py
import errand

errand.envs[ "cluster" ] = errand.Env( [
    errand.Ssh( host = "login.hpc", root = "/scratch/me/myproject" ),   # shared with the compute nodes
    errand.Slurm( partition = "gpu", gpus = 1, cpus = 8,
                  keep_alive = "30m",                          # kept 30 minutes once unused
                  allocation = { "time": "4:00:00" } ),        # what is asked of Slurm
    errand.Apptainer( image = "containers/train.sif", recipe = "containers/train.def", flags = [ "--nv" ] ),
] )

errand.envs[ "win" ] = errand.Env( [
    errand.Ssh( host = "lab-server", root = "/home/me/myproject" ),     # Linux, x86-64, KVM
    errand.Windows( cpus = 8, ram = "16G", fetch = [ "build" ], keep = "15m" ),
] )
```

Read each stack from the outside in. `cluster` is: the login node, then an allocation, then the
container, then your command. `win` is: the lab server, then a Windows VM that errand installs and
boots there, then your command.

- `keep_alive = "30m"` keeps the allocation, with an agent on its first node, for 30 minutes after
  the last command used it. Without it, one minute.
- `allocation = { "time": "4:00:00" }` sizes the job apart from the commands it serves: Slurm is
  asked for 4 hours, and commands run in it as long as they fit in what is left.
- `fetch = [ "build" ]` brings the guest's `build/` back after each command.

→ [Slurm](/guide/layers/slurm) · [Windows](/guide/layers/windows) · [Containers](/guide/layers/containers)

```bash
errand setup --env cluster     # the image, built over there
errand setup --env win         # the Windows install, once: 20 to 60 minutes
```

## A training, results brought back

```bash
errand run --env cluster -o --pull checkpoints train.py --epochs 50
```

The project is pushed to `/scratch/me/myproject`. Slurm gets a job; while it is pending, errand
says so. Once it runs, an agent starts on its first node, enters the container once, and runs
`train.py` there. The output streams to your terminal as it comes.

When the script ends, two things come back to the laptop:

- `-o`: the run's own directory under `errand-outputs/runs/`, which the script finds in
  `$ERRAND_OUT_DIR`;
- `--pull checkpoints`: that directory of the project, as the script left it.

→ [Results and records](/guide/output)

## The next command starts faster

```bash
errand run --env cluster -o eval.py --checkpoint checkpoints/last.pt
```

The allocation is still there, kept warm. No new job is submitted, no container is entered again:
the command goes straight to the agent on the node. It runs in the allocation if it fits: its cores
and GPUs within those declared, its `--time` within what the job has left. Otherwise it gets an
allocation of its own, and a warm one that nothing uses is given back first.

A command that runs in the allocation takes all of it unless it says what it needs (`--cpus`,
`--gpus`). A second one waits for room, and says so.

## Windows, from a Mac

```bash
errand run --env win cmake -B build -G Ninja
errand run --env win cmake --build build
errand run --env win ctest --test-dir build
```

The Mac cannot boot Windows; the lab server does. The first command boots the VM there, copies the
project in, and runs `cmake` in `cmd.exe` with the Visual Studio tools set up. `build/` comes back
to your Mac after each command. The VM stays up 15 minutes after the last one, so the next command
starts at once, and the build directory is still there for it.

`errand shell --env win` opens `cmd.exe` in the guest, if you want to look around.

## What is running

Three commands, in three terminals:

```bash
errand run --env cluster -o train.py --epochs 500
errand run --env cluster --gpus 2 sweep.py
errand run --env win ctest --test-dir build
```

Then, in a fourth:

```bash
errand status
```

```text
running   ( on laptop, lab-server, login.hpc: this machine, and every machine work was sent to from it )
  myproject
    login.hpc    7c01d2aa  run train.py --epochs 500  --env cluster  42 min  running
    login.hpc    a41c09d2  run sweep.py  --env cluster  3 min  waiting: slurm job 81234 pending, held warm, 3 min
    lab-server > windows 80103674 5be1c0a7  run ctest --test-dir build  --env win  1 min  running
  thesis-figures: 1 running on login.hpc
  lab-server: windows vm 80103674 ready, 8 cpus 16G
```

- The training runs in the allocation kept warm.
- The sweep did not fit (two GPUs, one declared), so it asked for a job of its own. That job is
  pending: the line says so, and since when.
- The tests run in the Windows guest, and the VM is listed with the machine that runs it.
- Another project of yours gets one line. `errand status --all` shows it in full.

Nothing is started to answer: errand reads what each machine's agents wrote down, over one ssh per
machine. → [What is running](/guide/status)

What is kept between commands, the allocation included:

```bash
errand agents
```

```text
  hub  pid 79636  up 48 min   ~/.cache/errand/hub-c81a3d1d455a
    lab-server                                       last used 1 min ago; kept 15 min unused
    login.hpc                                        last used 40 s ago; kept 15 min unused
    login.hpc:alloc-9f3e2c71a04b5d18                 last used 40 s ago, 1 open; kept 30 min unused
    login.hpc:alloc-9f3e2c71a04b5d18:env-3c1d0e9a7f  last used 40 s ago; kept 30 min unused
```

## Close the laptop

The training does not need the laptop. Its agent writes its output to disk on the cluster. When the
connection drops, errand says:

```text
  the connection to the environment was lost: the work goes on over there ( errand attach )
```

Later, from the same project:

```bash
errand status     # its "left running" part lists it, still running or finished
errand attach     # the output from the start, then the end, then the results brought back
```

`errand attach` brings back what `-o` and `--pull` asked for, as if you had never left.
→ [Let it run](/guide/detached)

## Ctrl-C stops it, through every layer

Ctrl-C in front of `errand run` or `errand attach` reaches the training on the compute node,
through ssh, the allocation and the container. The agent there sends an interrupt, then a terminate
after 2 seconds, then a kill after 5 seconds, to the whole process group. errand exits with code 130.

Ctrl-C while a job is still pending lets go of it. errand cancels nothing in the queue, but the job
finds that nobody waits for it any more when it starts, and is given back at once.

The allocation itself stays warm for its `keep_alive`, ready for the next command.

## Stopping everything

```bash
errand agents stop            # every agent, then the hub; a warm allocation goes with its agent
errand agents stop --force    # the same, even where something still runs
errand vm stop                # the Windows VMs, here and on each machine an Ssh leads to
```

An agent with something running is left alone, and says so; `--force` stops it anyway. You do not
have to do any of this: the allocation goes after 30 minutes unused, the VM after 15, the agents
after 15 minutes with nothing to do.

## What you did not do

- No `sbatch` script, no `squeue` to watch, no `scp` of the results.
- No Windows machine to keep, no RDP, no copying the build back by hand.
- No list of what you left running: `errand status` has it.

Add `-v` to any command to see every command errand starts, here and over there.

## Next

[Agents and keeping warm](/guide/agents) · [Sharing the machine](/guide/machine) ·
[Slurm](/guide/layers/slurm) · [Windows](/guide/layers/windows) · [CLI reference](/reference/cli)
