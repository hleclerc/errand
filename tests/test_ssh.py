"""Going to another machine, when there is another machine.

None of this can be committed: reaching a host, or a batch queue, depends on
who is running the suite. So it is asked for by name, and the entries that
need it are SKIPPED -- loudly, saying what to write and where -- rather than
passing on nothing.

    # errand.local.py at the project root, not tracked
    ssh_host = "gpu-box"
    ssh_root = "/home/me/scratch/errand-test"
"""
import subprocess

from errand import test, need, have, skip
from errand import layers as L


if test( "it reaches the host at all", tags = [ "ssh" ] ):
    host = need( "ssh_host", "a machine you can ssh to without being asked for a password",
                 example = "gpu-box" )
    got = subprocess.run( [ "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                            host, "true" ] )
    assert got.returncode == 0, ( f"ssh {host} failed. errand.local.py names it, so this is "
                                  f"a broken setup rather than a missing one." )


if test( "a stack is folded against the REMOTE root", tags = [ "ssh" ] ):
    # No machine needed: what crosses is a shell string, and it must speak of
    # paths over there, not of paths here.
    ssh = L.Ssh( host = "somewhere", root = "/remote/proj" )
    inner = [ L.Apptainer( image = "c/cuda.sif" ) ]
    remote_ctx = L.Context( root = ssh.remote_root( L.Context( root = "/local/proj" ) ),
                            remote = True )
    line = L.compose( inner, L.Command( [ "python3", "-m", "errand" ] ), remote_ctx ).shell()
    assert "/remote/proj/c/cuda.sif" in line
    assert "/local/proj" not in line


if test( "a round trip brings the results back", tags = [ "ssh", "slow" ] ):
    host = need( "ssh_host", "a machine you can ssh to without being asked for a password",
                 example = "gpu-box" )
    root = need( "ssh_root", "a directory on that machine errand may rsync into",
                 example = "/home/me/scratch/errand-test" )
    skip( "not written yet -- waits on the dispatch protocol being wired end to end" )


if test( "a batch queue takes the submission", tags = [ "slurm" ] ):
    partition = need( "slurm_partition", "a Slurm partition you may submit to",
                      example = "gpu" )
    skip( f"not written yet -- would submit to {partition}" )


if test( "the local file says what it has" ):
    # Always runs: it is the one that makes a missing setup visible rather than
    # silent, by reporting what the rest of this file will and will not do.
    from errand import local
    print( local.status() )
    for key in ( "ssh_host", "ssh_root", "slurm_partition" ):
        print( f"  {key}: {'yes' if have( key ) else 'no'}" )
