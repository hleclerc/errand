# Preload: sessions that start warm

```python
Preload( *modules, learn = True, when = None )
```

At the end of a stack, it says how sessions start. They no longer start as a new Python: each one
is a fork of a process that has already imported what it names. It changes nothing in the command.

```python
# errand-envs.py
import errand

errand.envs[ "gpu" ] = errand.Env( [ errand.Ssh( host = "gpu-box" ),
                                     errand.Micromamba( "torch" ),
                                     errand.Preload( "torch", "jax" ) ] )
```

| | |
|---|---|
| `modules` | imported ahead, before the first session asks |
| `learn` | also import ahead what earlier sessions used. `learn = False` sticks to the names |

A session that imports torch with CUDA takes 1.5 s instead of 2.9 s.

- **Each session is a process of its own.** Nothing is left over from the one before. The random
  generators of numpy and torch are reseeded in each fork.
- **The project is always read again.** The project's own modules are never imported ahead. A
  library that changed on disk since it was imported has its process started anew.
- **Libraries that start threads are left out**, since a fork does not copy threads, except
  OpenBLAS, which survives one.
- **Its memory gives way.** The process waiting with torch imported holds its memory in the
  [machine's queue](../machine) as kept warm. A command that needs the room gets it, and the process
  goes.

Without the layer, every session is a Python started anew. `ERRAND_WARM=0` does the same for one
command. The process lives beside the [environment agent](../agents), and goes with it.
