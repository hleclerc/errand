"""Going to another machine, and coming back with the results.

`ssh localhost` stands in for a second machine: a real ssh, a real rsync, a
real remote shell, a real round trip through a directory that is not the
project's. Only the hardware is shared, and the hardware is not what is being
tested. Name a real host in `errand-envs.py` to use that instead:

    ssh_host    = "gpu-box"
    ssh_root    = "/home/me/scratch/errand-test"   # optional
    ssh_options = [ "-p", "2222" ]                 # optional
"""
import subprocess
import tempfile
from pathlib import Path

from errand import test, have
from errand import layers as L, yamlish

from _infra import run_errand, ssh_target, write_project


PROJECT = '''
import errand

# `_lib` holds a copy of errand that travelled with the push, so the other side
# needs nothing installed. Discovery must not walk into it: its files mention
# `errand` and would be imported as if they declared work.
errand.configure( exclude = [ "_lib" ] )

errand.envs[ "over-there" ] = errand.Env(
     [ errand.Ssh( host = {host!r}, root = {root!r}, options = {options!r} ),
       errand.Vars( {{ "PYTHONPATH": "{root}/_lib", "MARK": "crossed" }} ) ],
     where = "remote" )
'''

WORK = '''
import os, socket
from errand import bench, Param

if p := bench( "over there", n = Param( 3 ) ):
    p.results[ "n" ]    = p.n
    p.results[ "mark" ] = os.environ.get( "MARK" )
    p.results[ "host" ] = socket.gethostname()
'''


if test( "a stack is folded against the REMOTE root", tags = [ "ssh" ] ):
    # No machine needed: what crosses is a shell string, and it must speak of
    # paths over there, not of paths here.
    ssh = L.Ssh( host = "somewhere", root = "/remote/proj" )
    inner = [ L.Apptainer( image = "c/cuda.sif" ) ]
    remote_ctx = L.Context( root = ssh.remote_root( L.Context( root = Path( "/local/proj" ) ) ),
                            remote = True )
    line = L.compose( inner, L.Command( [ "python3", "-m", "errand" ] ), remote_ctx ).shell()
    assert "/remote/proj/c/cuda.sif" in line
    assert "/local/proj" not in line


if test( "rsync is given the same options as ssh", tags = [ "ssh" ] ):
    # Reaching a different machine than ssh does would be a very quiet bug.
    assert L._rsh( [ ] ) == [ ]
    flag, command = L._rsh( [ "-p", "2222" ] )
    assert flag == "-e" and command == "ssh -p 2222"


if test( "it reaches the machine at all", tags = [ "ssh" ] ):
    host, options, _ = ssh_target()
    got = subprocess.run( [ "ssh", *options, host, "echo reached" ],
                          capture_output = True, text = True, timeout = 30 )
    assert got.returncode == 0 and "reached" in got.stdout, got.stderr


if test( "a round trip brings the results back", tags = [ "ssh", "slow" ] ):
    host, options, root_of = ssh_target()
    remote_root = root_of()

    with tempfile.TemporaryDirectory() as tmp:
        project = write_project(
            Path( tmp ) / "proj",
            PROJECT.format( host = host, root = remote_root, options = options ),
            { "bench_work.py": WORK }, vendor = True,
        )
        code, output = run_errand( project, "-k", "bench", "--env", "over-there", "--n", "3,4" )
        assert code == 0, output

        # The run happened over there -- and what it produced is HERE, at the
        # path this side worked out before the run existed.
        leaves = sorted( ( project / "runs" ).rglob( "result.yaml" ) )
        assert len( leaves ) == 2, f"{[ str( p ) for p in leaves ]}\n{output}"

        for leaf in leaves:
            got = yamlish.read( leaf )
            assert got[ "status" ] == "PASS", got
            assert got[ "results" ][ "mark" ] == "crossed", "the Vars layer did not cross"
            assert got[ "tags" ] == { "where": "remote" }, got[ "tags" ]

        assert { yamlish.read( p )[ "results" ][ "n" ] for p in leaves } == { 3, 4 }, \
            "the matrix must be expanded on this side, one plain run per combination"

        summaries = sorted( ( project / "runs" ).rglob( "summary.yaml" ) )
        assert summaries, "the summaries are part of what comes back"

    subprocess.run( [ "ssh", *options, host, f"rm -rf {remote_root}" ] )


if test( "only what this invocation asked for comes back", tags = [ "ssh", "slow" ] ):
    host, options, root_of = ssh_target()
    remote_root = root_of()

    with tempfile.TemporaryDirectory() as tmp:
        project = write_project(
            Path( tmp ) / "proj",
            PROJECT.format( host = host, root = remote_root, options = options ),
            { "bench_work.py": WORK }, vendor = True,
        )
        # Something older, unrelated, sitting in the remote output tree. The
        # push does not clear it (the output tree is excluded), so the pull is
        # the only thing standing between it and this machine.
        stale = f"{remote_root}/runs/someone_elses/run/2000-01-01_00h00m00-place"
        subprocess.run( [ "ssh", *options, host,
                          f"mkdir -p {stale} && echo 'name: old' > {stale}/result.yaml" ],
                        check = True )

        code, output = run_errand( project, "-k", "bench", "--env", "over-there" )
        assert code == 0, output
        assert not ( project / "runs" / "someone_elses__run" ).exists(), \
            "the pull must name the paths it wants, not drag the whole tree home"

    subprocess.run( [ "ssh", *options, host, f"rm -rf {remote_root}" ] )


if test( "the local file says what it has" ):
    # Always runs: it is what makes a thin setup visible rather than silent.
    from errand import local
    print( local.status() )
    for key in ( "ssh_host", "ssh_root", "ssh_options", "slurm_host", "slurm_partition" ):
        print( f"  {key}: {'yes' if have( key ) else 'no'}" )
