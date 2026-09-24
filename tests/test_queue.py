"""Sharing the machine: claims, exclusivity, and telling a corpse from a long run."""
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from errand import test, bench
from errand import queue as Q, yamlish

from _infra import write_project

import contextlib


@contextlib.contextmanager
def private_queue( ):
    """A queue of our own, so a test never waits on what the machine is really
    doing -- and puts the real one back, so the entries that run after this
    file do not inherit a directory that has been deleted."""
    before = os.environ.get( "XDG_RUNTIME_DIR" )
    with tempfile.TemporaryDirectory() as tmp:
        os.environ[ "XDG_RUNTIME_DIR" ] = tmp
        Q._capacity = None
        try:
            yield Path( tmp )
        finally:
            Q._capacity = None
            if before is None:
                os.environ.pop( "XDG_RUNTIME_DIR", None )
            else:
                os.environ[ "XDG_RUNTIME_DIR" ] = before


if test( "a size is read the way a person writes one" ):
    assert Q.parse_size( "8G" ) == 8192
    assert Q.parse_size( "512M" ) == 512
    assert Q.parse_size( "2048" ) == 2048          # bare numbers are MB
    assert Q.parse_size( "1T" ) == 1024 * 1024
    assert Q.parse_size( "8GB" ) == 8192
    assert Q.parse_size( None ) == 0


if test( "the queue is per user AND per host" ):
    # A home directory shared over NFS is normal on a cluster; a queue under it
    # would merge machines that share nothing but a filesystem, and one host
    # would end up waiting on another's benchmark.
    assert Q.host() in str( Q.queue_dir() )
    if hasattr( os, "getuid" ):
        assert str( os.getuid() ) in str( Q.queue_dir() )


if test( "a claim is held, then given back" ):
    with private_queue():
        assert Q.held() == [ ]
        with Q.claim( { "cpus": 2 }, label = "a" ) as granted:
            rows = Q.held()
            assert len( rows ) == 1 and rows[ 0 ][ "label" ] == "a" and rows[ 0 ][ "cpus" ] == 2
            assert granted.path.exists()
            assert granted.devices == [ ] and granted.env() == { }
        assert Q.held() == [ ]


def waiting_for( needs, exclusive, others ):
    return Q._fits( needs, exclusive, others )[ 0 ]


def granted_devices( needs, exclusive, others ):
    return Q._fits( needs, exclusive, others )[ 1 ]


if test( "what fits, fits" ):
    Q._capacity = { "cpus": 8.0, "ram": 16000.0, "gpus": 1.0 }
    try:
        assert waiting_for( { "cpus": 4 }, False, [ { "cpus": 4 } ] ) is None
        assert waiting_for( { "cpus": 4 }, False, [ { "cpus": 5 } ] ) is not None
        assert waiting_for( { "gpus": 1 }, False, [ { "gpus": 1, "devices": [ 0 ] } ] ) is not None
        # a dimension nobody claimed is not a reason to wait
        assert waiting_for( { "cpus": 1 }, False, [ { "ram": 8000 } ] ) is None
    finally:
        Q._capacity = None


if test( "an exclusive run waits for the machine, and holds it" ):
    have = { "cpus": 8.0, "ram": 16000.0, "gpus": 0.0 }
    Q._capacity = have
    try:
        assert waiting_for( { }, True, [ ] ) is None
        assert waiting_for( { }, True, [ { "cpus": 1, "label": "x" } ] ) is not None
        # ...and once it holds it, nothing small slips past
        assert waiting_for( { "cpus": 1 }, False, [ { "exclusive": True, "label": "bench" } ] ) is not None
    finally:
        Q._capacity = None


if test( "asking for more than exists runs alone rather than waiting for ever" ):
    Q._capacity = { "cpus": 4.0, "ram": 1000.0, "gpus": 0.0 }
    try:
        assert waiting_for( { "cpus": 64 }, False, [ ] ) is None       # nothing else running: go
        assert waiting_for( { "cpus": 64 }, False, [ { "cpus": 1 } ] ) is not None
    finally:
        Q._capacity = None


if test( "a claim nobody breathes for is reclaimed" ):
    with private_queue():
        corpse = Q._claims_dir() / "dead.yaml"
        yamlish.write( corpse, { "label": "killed", "pid": 999999, "cpus": 8,
                                 "exclusive": True, "since": time.time() } )
        os.utime( corpse, ( time.time() - Q.STALE_AFTER - 5, ) * 2 )

        assert Q.held() == [ ], "a claim with nobody behind it must not hold the machine"
        assert not corpse.exists()


if test( "a long run is not a corpse" ):
    # The ONLY difference is whether something is still breathing for it.
    with private_queue():
        with Q.claim( { "cpus": 1 }, label = "slow but alive" ):
            claim_file = Q._claims_dir().glob( "*.yaml" ).__next__()
            os.utime( claim_file, ( time.time() - Q.STALE_AFTER - 5, ) * 2 )
            time.sleep( Q.HEARTBEAT + 1.0 )     # let the heartbeat catch up
            assert len( Q.held() ) == 1, "the heartbeat must keep a live claim alive"


if test( "two claims cannot both have the machine" ):
    with private_queue():
        Q._capacity = { "cpus": 4.0, "ram": 1000.0, "gpus": 0.0 }
        order = [ ]

        def second( ):
            with Q.claim( { "cpus": 1 }, label = "after" ):
                order.append( "after" )

        try:
            waiter = threading.Thread( target = second )
            with Q.claim( { }, exclusive = True, label = "exclusive" ):
                waiter.start()
                time.sleep( 1.0 )
                order.append( "exclusive" )
                assert order == [ "exclusive" ], "something slipped past an exclusive claim"
            waiter.join( timeout = 10 )
            assert order == [ "exclusive", "after" ]
        finally:
            Q._capacity = None


if test( "a batch system already decides, so errand does not" ):
    # A second queue on top of Slurm's would only wait for itself.
    assert Q.someone_else_is_scheduling() is None
    os.environ[ "SLURM_JOB_ID" ] = "918273"
    try:
        assert Q.someone_else_is_scheduling() == "slurm"
        with private_queue():
            with Q.claim( { "cpus": 999 }, exclusive = True, label = "x" ) as path:
                assert path is None, "inside an allocation there is nothing to claim"
            assert Q.held() == [ ]
    finally:
        del os.environ[ "SLURM_JOB_ID" ]


if test( "what an allocation is asked for is what the work needs" ):
    from errand import layers as L
    from errand.cli import aggregate_needs
    from errand.entries import Entry, TRAITS

    def an_entry( exclusive = False, **resources ):
        traits = dict( TRAITS, exclusive = exclusive )
        return Entry( "e", [ ], { }, traits, resources, "f.py", 1, "m" )

    needs = aggregate_needs( [ an_entry( cpus = 4 ), an_entry( cpus = 16, ram = "8G" ) ] )
    assert needs == { "cpus": 16.0, "ram": 8192.0 }, needs

    flags = L.Slurm( partition = "gpu" ).flags( L.Context( root = Path( "/" ), needs = needs ) )
    assert flags[ : 2 ] == [ "--partition", "gpu" ]
    assert "--cpus-per-task" in flags and flags[ flags.index( "--cpus-per-task" ) + 1 ] == "16"
    assert "--mem" in flags and flags[ flags.index( "--mem" ) + 1 ] == "8192M"

    # one exclusive entry makes the whole allocation exclusive
    needs = aggregate_needs( [ an_entry( cpus = 1 ), an_entry( exclusive = True ) ] )
    assert "--exclusive" in L.Slurm().flags( L.Context( root = Path( "/" ), needs = needs ) )


if test( "what the environment states wins over what the entry guessed" ):
    from errand import layers as L
    # `cpus = 16` on the environment knows something about the partition that
    # an entry cannot.
    ctx = L.Context( root = Path( "/" ), needs = { "cpus": 2.0 } )
    flags = L.Slurm( cpus = 16 ).flags( ctx )
    assert flags[ flags.index( "--cpus-per-task" ) + 1 ] == "16"


if test( "two invocations do not trample each other", tags = [ "slow" ] ):
    # The real point of the whole thing: not one process being tidy with
    # itself, but two, in two terminals, on two projects.
    WORK = '''
import time
from errand import bench, test

if p := bench( "greedy" ):
    time.sleep( 2.0 )
    p.results[ "done" ] = 1
'''
    with private_queue() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "bench_greedy.py": WORK } )

        env = dict( os.environ )
        env[ "XDG_RUNTIME_DIR" ] = str( tmp )
        env[ "PYTHONPATH" ] = str( Path( __import__( "errand" ).__file__ ).resolve().parent.parent )

        started = time.perf_counter()
        both = [ subprocess.Popen( [ sys.executable, "-m", "errand", "-k", "bench" ],
                                   cwd = project, env = env,
                                   stdout = subprocess.PIPE, stderr = subprocess.STDOUT,
                                   text = True ) for _ in range( 2 ) ]
        outputs = [ p.communicate( timeout = 300 )[ 0 ] for p in both ]
        elapsed = time.perf_counter() - started

        assert all( p.returncode == 0 for p in both ), outputs
        # Two exclusive two-second benchmarks cannot have overlapped.
        assert elapsed > 3.5, f"they ran at the same time ({elapsed:.1f}s)\n{outputs}"
        assert any( "waiting for" in o for o in outputs ), outputs


# --- devices ----------------------------------------------------------------

if test( "a card is ASSIGNED, not merely counted" ):
    # Two entries that both asked for "a gpu" and both picked the first would
    # share it, and neither would measure anything.
    Q._capacity = { "cpus": 8.0, "ram": 16000.0, "gpus": 4.0 }
    try:
        assert granted_devices( { "gpus": 2 }, False, [ ] ) == [ 0, 1 ]
        assert granted_devices( { "gpus": 2 }, False, [ { "devices": [ 0, 1 ] } ] ) == [ 2, 3 ]
        assert waiting_for( { "gpus": 3 }, False, [ { "devices": [ 0, 1 ] } ] ) is not None
        # asking for none is asking for none, not for all of them
        assert granted_devices( { "cpus": 1 }, False, [ ] ) == [ ]
        # the whole machine means every card on it
        assert granted_devices( { }, True, [ ] ) == [ 0, 1, 2, 3 ]
    finally:
        Q._capacity = None


if test( "what a child has to be told about the cards it was given" ):
    granted = Q.Granted( path = Path( "/x" ), devices = [ 1, 3 ] )
    assert granted.env() == { "CUDA_VISIBLE_DEVICES": "1,3",
                              "HIP_VISIBLE_DEVICES": "1,3",
                              "ROCR_VISIBLE_DEVICES": "1,3" }
    assert Q.Granted( path = Path( "/x" ), devices = [ ] ).env() == { }


if test( "a nested claim hands down its own numbering, not the outer one" ):
    # CUDA_VISIBLE_DEVICES renumbers from zero for whoever it is set on: a
    # process given cards 2 and 5 sees 0 and 1, and must pass 0 and 1 on.
    before = os.environ.get( "CUDA_VISIBLE_DEVICES" )
    os.environ[ "CUDA_VISIBLE_DEVICES" ] = "2,5"
    Q._capacity = None
    try:
        assert Q.devices() == [ 0, 1 ]
    finally:
        Q._capacity = None
        if before is None:
            os.environ.pop( "CUDA_VISIBLE_DEVICES", None )
        else:
            os.environ[ "CUDA_VISIBLE_DEVICES" ] = before


if test( "the lock carries the host, like everything else in the queue" ):
    # A queue directory that somehow ends up shared -- a TMPDIR on a network
    # mount -- must separate machines rather than merge them.
    with private_queue():
        with Q.claim( { "cpus": 1 }, label = "x" ):
            pass
        names = [ p.name for p in Q.queue_dir().iterdir() ]
        assert any( n.startswith( f"lock-{Q.host()}" ) for n in names ), names
