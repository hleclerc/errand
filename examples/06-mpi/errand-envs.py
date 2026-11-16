"""Where this example runs: here, and on a Slurm cluster in an Apptainer image.

Committed because it IS the example; in a project of yours, adapt the host, the paths and the
partition, or put this file aside from version control.
"""
import errand

# Here: MPICH and mpi4py in a micromamba environment. `--ranks N` starts the ranks with the
# `mpiexec` of that environment, on this machine.
errand.envs[ "here" ] = errand.Env( [
    errand.Micromamba( "errand-mpi-demo", python = "3.12", packages = [ "numpy", "mpi4py", "mpich" ] ),
] )

# A cluster: the login node, then an allocation of 2 nodes and 4 tasks on each, then an image.
#
# errand runs once, in the image, on the first node. The ranks are started OUTSIDE the image, by
# the allocation's own `srun` over both nodes, and each enters the image on its node:
#
#     srun --mpi=pmix --nodes 2 --ntasks 8 apptainer exec containers/mpi.sif python heat.py …
#
# The MPI of the image ( Open MPI, built with PMIx ) is told its rank and its peers by Slurm.
errand.envs[ "cluster" ] = errand.Env( [
    errand.Ssh( host = "login.hpc", root = "/scratch/me/mpi-demo" ),      # shared with the compute nodes
    errand.Slurm( nodes = 2, ntasks_per_node = 4, time = "0:30:00" ),
    errand.Apptainer( image = "containers/mpi.sif", recipe = "containers/mpi.def" ),
] )
