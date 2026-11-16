# Preload: sessions that start warm

```python
Preload( *modules, learn = True, when = None )
```

At the end of a stack, it changes how sessions start: each one is a fork of a process that has
already imported what it names, instead of a new Python. The command itself is unchanged.

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
| `learn` | also import ahead what earlier sessions used. `learn = False` sticks to the names given |

A session that imports torch with CUDA starts in about half the time.

## What it does not change

- **Each session is a process of its own.** Nothing is left over from the one before. The random
  generators of numpy and torch are reseeded in each fork.
- **The project is always read again.** Its own modules are never imported ahead. A library that
  changed on disk since it was imported has its process started anew.
- **Libraries that start threads are left out**, since a fork does not copy threads; OpenBLAS, which
  survives one, is the exception.
- **Its memory gives way.** The waiting process holds its memory in the [machine's queue](../machine)
  as kept warm. A command that needs the room gets it, and the process goes.

Without the layer, every session is a new Python. `ERRAND_WARM=0` does the same for one command.
The process lives beside the environment's [agent](../agents), and goes with it.
