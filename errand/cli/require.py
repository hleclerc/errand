"""`errand require --gpus 1 --gpu-ram 75%`: what `errand.require` does, for a run in any language ( ADR 0014 ).

It grows the claim of the run it is in ( `ERRAND_CLAIM_FILE` ), waits until it is granted, then prints
what to set in the run's process, one `NAME=value` per line:

    CUDA_VISIBLE_DEVICES=1
    HIP_VISIBLE_DEVICES=1
    ROCR_VISIBLE_DEVICES=1
    ERRAND_CLAIM=1

Nothing is printed outside errand, with `--no-queue`, or in an allocation of somebody else's. Stopped
in a cycle ( `errand.Rerun` ), it exits with `RERUN`: errand runs the work again, with its needs up front.
"""
from __future__ import annotations

import argparse
import os
import sys

RERUN = 75          # EX_TEMPFAIL: stopped, to be run again


def main( argv ) -> int:
    from .. import entries, queue
    p = argparse.ArgumentParser( prog = "errand require", allow_abbrev = False,
                                 description = "grow the claim of the run this is in, then print what to set" )
    p.add_argument( "--gpus", default = None, help = "cards it needs" )
    p.add_argument( "--gpu-ram", dest = "gpu_ram", default = None,
                    help = "memory it takes on each card: a size ( 40G ) or a share ( 75%% )" )
    p.add_argument( "--ram", default = None, help = "memory it needs, e.g. 8G" )
    p.add_argument( "--cpus", default = None, help = "cores it needs" )
    p.add_argument( "-x", "--exclusive", action = "store_true", help = "the machine to itself" )
    known = p.parse_args( argv )
    needs = { k: getattr( known, k ) for k in ( "gpus", "gpu_ram", "ram", "cpus" ) if getattr( known, k ) is not None }
    path = os.environ.get( queue.CLAIM_FILE )
    if not path:
        entries._check_allocation( needs )
        return 0
    try:
        got = queue.grow( path, needs, exclusive = known.exclusive,
                          echo = lambda m: print( f"errand require: {m.strip()}", file = sys.stderr, flush = True ) )
    except entries.Rerun as r:
        print( f"errand require: stopped, {r}", file = sys.stderr, flush = True )
        return RERUN
    except ( RuntimeError, ValueError ) as err:
        print( f"errand require: {err}", file = sys.stderr, flush = True )
        return 1
    if got:
        listed = ",".join( str( d ) for d in got )
        for name in ( *entries._DEVICE_VARS, queue.CLAIM ):
            print( f"{name}={listed}" )
    return 0
