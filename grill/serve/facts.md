# errand serve: facts from the code (2026-11-19)

- queue.py: claims are files kept by a 5 s heartbeat thread (stale after 30 s). `hold` = `python -m errand.queue hold '{json}'`:
  prints `granted d0,d1`, reads `warm`/`busy` on stdin, prints `evict` once per warm period, releases on stdin EOF.
  `_acquire` evicts preemptible claims when the request would fit without them; the holder must release itself.
- **Order:** only exclusive and growing requests write `waiting/`; a plain non-exclusive waiter is recorded nowhere and can be
  overtaken by a later request that fits. Hugo's "sans être doublée" needs every waiter recorded (round 2).
- VM: `vm/claim.py` uses `queue hold` through a remote agent (keep False), `vm/keeping.py` flips preemptible on use.
  Zygote: `try_claim` + `touch`, ram need resized with RSS.
- Agents: `Proc` meta + pgid, stop = INT, TERM 2 s, KILL 5 s on the group; `cancel` file = on_stop. `keep=True` procs outlive
  their client (VM keeper). A live proc keeps the agent alive indefinitely.
- Transport: frames IN/OUT carry raw bytes (rsync over rsh already); no socket op, no port forward (web docs say ssh -L).
  A forward = one channel per TCP connection, through a socket<->stdio bridge or a native op.
- Listing: `errand queue` shows held claims with `( kept warm: gives way )`; `errand status` does not list queue claims yet.
- Web: a thread of the host agent, lifetime = the agent's; page use in the last 30 s keeps the agent alive.
