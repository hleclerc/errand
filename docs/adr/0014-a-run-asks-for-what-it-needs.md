---
status: proposed
date: 2026-11-18
---

# A run asks for what it needs: on the command line, or from its code

ADR 0011 took the needs off the entries (`test( gpus = 1 )`, `exclusive`…). Nobody declared them,
and the per-case cut that carried them is gone. A run is now one invocation of a tool, and it
claims what the command line asks (`--cpus`, `--ram`, `--gpus`, `-x`), or one cpu.

Some work needs more, and only its code knows it. A computation with Jax on a GPU takes nearly all
of the card's memory at its first array, so two such runs on one card fail, or measure nothing.
Before ADR 0011, runners had to find that out from the files, which was intrusive and is gone.
Writing `--gpus 1 -x` on every command line is forgotten, and does not travel with the code.

The queue (`queue.py`) is per machine. A run's claim is taken before its process starts, held by
the errand process that started it (a file, kept alive by its heartbeat), and inherited
(`ERRAND_CLAIM` lists the cards given), so that nothing inside the run queues again.

## Decision

**Three ways to ask, one claim.** From the most general to the most precise, each one over the one
before:

- **The environment**: `Env( [ … ], needs = { "gpus": 1, "gpu_ram": "75%", "ram": "16G" } )`.
  What every run in it takes, known before anything starts. An environment that runs Jax on a GPU
  knows that a run takes a card and 75 % of its memory (Jax's preallocation), whatever the run.
- **The command line**, as today: `errand run --gpus 1 --gpu-ram 40G --ram 20G x.py::y`, `-x` for
  the machine to itself. It is checked again end to end after ADR 0011.
- **The code**: `errand.require( gpus = 1, gpu_ram = "75%", ram = "20G", exclusive = False )`,
  called early, before what it protects is allocated. For Jax, before `import jax`. It can only
  add to the claim: it is the run saying what the others could not know.

**The memory of a card is a resource.** `gpu_ram` is what a run takes on each of its cards: a size
(`40G`) or a share of the card (`75%`). The queue counts it per card, as it counts `ram` per
machine: two runs that each take 30 % share a card, two that take 75 % do not. A run with
`gpus` and no `gpu_ram` takes its cards whole, as today. A card's size is read with `nvidia-smi`
(or `rocm-smi`) when the queue reads the machine's capacity.

**`require` grows the run's claim, and waits.** errand hands the run the path of its claim
(`ERRAND_CLAIM_FILE`, beside `ERRAND_CLAIM`). `require` asks the queue to grow that claim to what
it says, under the queue's lock, and blocks until it fits, as `_acquire` does for a new claim. The
claim stays held by the errand process that started the run: `require` only rewrites what it holds.
Once granted, it returns the cards, and sets `CUDA_VISIBLE_DEVICES` (and the HIP / ROCR ones) in
its own process, which a framework reads at its first use of the device. A `require` that asks for
no more than the claim holds returns at once.

*Added 2026-11-18*: `require` asks for that much **in all** ( the larger of what is held and what is
asked, a share and a size compared on the smallest card held: a claim never shrinks ), or, with
`extra = True`, for that much **more** than the run was started with by its environment and command
line ( the claim's `base` ), several calls adding up. What is remembered is the total the code came to
( `wanted` ), not the calls, so that an `extra` call is not added again on top of what is claimed up
front.

**errand can remember, so that the next run asks up front.** What a run required is written in its
record. With `errand.configure( remember_needs = True )` (off by default: what a run claims is then
only what it is told and what its code requires, nothing it did before), it is also kept in the
machine's state, by environment and target (`errand-outputs/state/needs.json`). The next run of
that target claims it before it starts, as if it had been on the command line. It then rarely grows while running, and the cards are known from
its first line. A target that no longer calls `require` drops what was remembered after one run.
What is remembered is the machine's own: another machine, another capacity, learns its own.

**Growing waits in order, and a cycle is broken by running again.** A claim that grows is ahead of
any new claim (as an exclusive request already is), so a stream of small runs does not starve it.
Two runs that grow at once can wait for each other: each holds what the other needs. Then the run
whose claim is younger is stopped by its `require` (`errand.Rerun`, raised under errand only), and
run again, once, with its needs now known up front. This is cheap because `require` comes first in
the code; it is said, with the reason, in the run's output.

**Not intrusive.** Outside errand (no `ERRAND_CLAIM_FILE`), with `--no-queue`, or inside an allocation
of Slurm, PBS, OAR… (the scheduler already decided), `require` does nothing and returns at once. In
an allocation, it says once if the allocation is smaller than what is asked. A program run by hand
never waits, never fails, and sees its environment unchanged.

**Every language.** The claim is a file and the queue's lock is a directory, but a protocol that
several languages reimplement is one that drifts. So the one implementation is errand's:
`$ERRAND_PYTHON -m errand require --gpus 1` waits, then prints what to set (`CUDA_VISIBLE_DEVICES=1`).
The helper of each language is a few lines: no `ERRAND_CLAIM_FILE`, return; otherwise call that,
and set what it prints in the process.

- Python: `errand.require` (in `errand`, standard library only).
- Shell: `require --gpus 1` from `eval "$ERRAND_STEPS_SH"`, as `step`.
- C++: a header-only `errand/require.hpp` (`errand::require( { .gpus = 1 } )`), shipped with errand
  and found by a runner's build line as `-I{errand_include}`.
- Rust: a function to copy, or a crate if one is asked for.

## Considered options

- **Declared by the entries again** (`test( gpus = 1 )`). ADR 0011's reasons stand: a run is no
  longer an entry, and nobody declared them.
- **Read from the source before running** (look for `require(` in the files). Fragile, and blind
  to what a library requires on its own.
- **Only the command line.** Correct, and kept, but it is forgotten, and a library cannot ask.
- **`require` without waiting**: it only records, for the next run. The first run of a target on a
  busy machine would then share a card it needs alone.
- **A cycle broken by letting the younger run through anyway.** A card shared by two Jax runs is
  an out-of-memory error later, far from its cause. Running again is visible and correct.

## Consequences

An environment says once what all its runs take. Work that needs more says so in its code, once. It is correct from the first run
(it waits), and, when the project asks errand to remember, efficient from the second (claimed up
front, cards known before it starts). A
program run without errand is unchanged. The queue gains a claim that grows, a priority for it,
and a rerun for the rare cycle. `ERRAND_CLAIM_FILE` joins the variables errand sets for a run;
it is errand's own, not a value forwarded from the user's environment.

## Order of work

1. Check that `--gpus`, `--ram`, `-x` reach the claim after ADR 0011, here and over `Ssh`.
   *Done 2026-11-18*: here ( `run_entries` ) and over `Ssh` ( `agents/ops.py` `session`, which gets
   them through `KNOWN` ) both claim with what `Ask` read. Tested here end to end
   ( `tests/test_require.py` ); the `Ssh` test ( `tests/test_ssh.py`, tag `ssh` ) is skipped without a
   host to reach.
2. `Env( needs = … )`, and `gpu_ram` in the queue: a card's memory read, counted per card,
   cards given by what they have left. *Done 2026-11-18*: `needs` checked when declared, under the
   command line, and in the plan an allocation is sized from; `card_ram` in `capacity()`
   ( `nvidia-smi`, else `rocm-smi` ), a claim writes what it takes on each card ( `card_ram` ), a card
   whose size is unknown is taken whole; `--gpu-ram`.
3. `ERRAND_CLAIM_FILE`, the growing claim in `queue.py` (priority, cycle), `errand.require`, the
   `errand require` command and the shell function. Tests on this machine with fake capacities.
   *Done 2026-11-18*: `queue.grow`, growth requests in `waiting/` ( ahead of new claims ), the younger
   of a cycle stopped with `errand.Rerun` and the claim marked, the run claimed again once
   ( `needs.run_claimed` ); `errand require` exits 75 when stopped.
4. What is remembered: the record, `needs.json`, the claim up front. *Done 2026-11-18*:
   `errand/needs.py`, keyed by host, environment and `file::name`; `required` in `result.yaml`.
   Made optional the same day, off by default: `configure( remember_needs = True )`. A run stopped
   in a cycle is run again with what its claim says it required, remembered or not. Tried on lmo's
   2080 Ti: its size read ( 11264 MiB ), `--gpu-ram 30%` claimed over `Ssh`, `require( gpu_ram = "50%" )`
   grown in place. Not tried: Jax itself on a shared card.
5. The C++ header, with a test through the Catch2 runner. Then otrec and sdot-ffi call
   `require( gpus = 1 )` where they use Jax on a GPU: a card is assigned, never shared, so that is
   already the card to itself; `exclusive` is the whole machine (a benchmark). *The header done
   2026-11-18*: `errand/include/errand/require.hpp`, C++17 ( designated initializers in C++20 ),
   `errand::Rerun` on exit 75, `{errand_include}` in runners' build lines; tested here with a plain
   binary, and through the Catch2 runner on lmo. *otrec and sdot-ffi marked 2026-11-18*: rather than
   `require( gpus = 1 )` in each entry ( loom's default device is the card: every run of a card
   framework uses it ), the environments say it: in `~/Projects/errand-envs.py`, `gpus` on lmo, n22,
   n22x2 for torch and cupy, with `gpu_ram = "75%"` for Jax ( and on Jean Zay ); `gpus = 1` on otrec's
   own environments. The benchmarks ( sdot-ffi's `bench/bench_*.py` and `pd accelerated`, otrec's
   `bench/eval.py` ) call `require( exclusive = True )`, which ADR 0011 had taken from `bench`. Tried
   on lmo ( `otrec/bench/eval.py` ). Two rules found on the way: a card asked on a machine with none
   is not waited for, and the younger growers make way when an older one waits only for them ( three
   benchmarks under `-j` growing to the whole machine, which no pair shows ).
