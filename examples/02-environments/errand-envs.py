"""Where this project runs, for whoever runs it. Not versioned in a real project -- the
environments depend on the user and the machine -- but committed here, because they ARE the example.

Ordinary Python, loaded once, with every other `errand-*.py`. There is no entry point to call and
nothing to return: `errand.envs` holds what you put in it.
"""
import errand

# Shared pieces are shared with plain Python. There is no second mechanism for
# this, and none is wanted: a list is a list.

CUDA = [
    errand.Apptainer(
        image  = "containers/cuda.sif",
        recipe = "containers/cuda.def",   # what to (re)build the image from
        flags  = [ "--nv" ],
        pip    = [ "jax[cuda13]" ],       # installed INTO the container
    ),
]

# A layer may read the tags that were SELECTED rather than fix a value, with a
# default for when nothing asked. Without this there would be a `local32`
# beside every `local` and a `gpu32` beside every `gpu`, with the precision
# written twice in each -- once to be matched by `--fp`, once to be handed to
# the child process.

FTYPE = [ errand.Vars( lambda t: { "DEMO_FTYPE": f"FP{ t.get( 'fp', '64' ) }" } ) ]


# --- the environments -------------------------------------------------------
#
# The first one declared is the default; `errand.default_env = "gpu"` says otherwise.
#
# Keyword arguments are TAGS: what this environment is. Nothing declares them
# in advance -- every name used here becomes a flag of its own (--driver,
# --cuda, --fp), and an environment that omits one matches any value of it.
#
# Nothing says `fp` below: an environment that does not mention a dimension
# covers every value of it, so `--fp 32,64` is two runs in ONE environment.
# `cluster` pins it, and is therefore not selected by `--fp 32`.

errand.envs[ "local" ] = errand.Env(
     [ errand.Micromamba( "demo", python = "3.13", requirements = "requirements.txt" ) ] + FTYPE,
     driver = "cpu" )

errand.envs[ "gpu" ] = errand.Env(
     CUDA + FTYPE,
     driver = "cuda", cuda = True )

# The same idea where apptainer does not exist -- a mac, a laptop without root.
# Only the layer changes: same tags, same fingerprint, same output paths.

errand.envs[ "boxed" ] = errand.Env(
     [ errand.Docker( image = "errand-demo:1", recipe = "containers/Dockerfile" ) ] + FTYPE,
     driver = "cpu", boxed = True )

# A remote machine is not a separate concept. `Ssh` first, then the same
# layers as anywhere else -- they run over there instead of here.

errand.envs[ "box" ] = errand.Env(
     [ errand.Ssh( host = "gpu-box", root = "/home/me/demo" ) ] + CUDA + FTYPE,
     driver = "cuda", cuda = True, remote = True )

# ...and a batch system is one more layer, not a separate mode. `--batch`
# turns the `srun` below into an `sbatch`; everything else is unchanged.

errand.envs[ "cluster" ] = errand.Env(
     [ errand.Ssh( host = "login.hpc", root = "/scratch/me/demo" ),
       errand.Slurm( partition = "gpu", gpus = 1, cpus = 16, time = "2:00:00" ) ] + CUDA + FTYPE,
     driver = "cuda", cuda = True, fp = "64", remote = True )
