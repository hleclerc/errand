"""Questions about a whole stack: which layer of which kind, and what is worth a warning.
"""
from __future__ import annotations

from .families import batch_of, Container, Interpreter
from .launchers import Mpi
from .gateways import Ssh


# Paths that a compute node does not generally share with the machine you
# submitted from. Getting this wrong fails deep inside the job, with a message
# from the batch system about chdir and then an import error -- nothing that
# points at the actual cause.
NODE_LOCAL = ( "/tmp", "/var/tmp", "/dev/shm", "/scratch/local", "/localscratch" )


def warnings_for( stack, root ) -> list:
    """What is about to go wrong in a way the error will not explain."""
    out = [ ]
    if batch_of( stack ) is not None:
        where = str( root )
        if any( where == p or where.startswith( p + "/" ) for p in NODE_LOCAL ):
            out.append(
                f"{where} is node-local: a batch job runs on a compute node, which does not "
                f"share it with the machine you submit from.\n"
                f"  the job will not find the project -- put the root on a shared filesystem "
                f"( your home, /scratch, /work )" )
    return out


def container_of( stack ):
    """The innermost container in a stack, for `{place}` in the output path."""
    for layer in reversed( stack ):
        if isinstance( layer, Container ):
            return layer.container
    return None


def interpreters_of( stack ):
    """The layers of `stack` that only CHOOSE AN INTERPRETER ( a venv, a micromamba or conda environment, a uv venv ), in order:
    what a command that only needs errand itself goes through -- the submission a `--batch` preparation makes from inside its
    allocation -- where a container, a module or a variable is not wanted."""
    return [ l for l in stack if isinstance( l, Interpreter ) and not isinstance( l, Container ) ]


def chooses_python( stack ) -> bool:
    """Whether a layer of `stack` replaces `python` with an interpreter of its own."""
    return any( isinstance( l, Interpreter ) for l in stack )


def mpi_of( stack ):
    return next( ( l for l in stack if isinstance( l, Mpi ) ), None )


def ssh_of( stack ):
    return stack[ 0 ] if stack and isinstance( stack[ 0 ], Ssh ) else None


def vm_of( stack ):
    """A machine errand boots ( `errand.Windows` ), recognized by what it says
    of itself so that this module need not import the one that defines it.
    First, or right after the `Ssh` that leads to the machine it runs on."""
    return next( ( l for l in stack if getattr( l, "is_vm", False ) ), None )
