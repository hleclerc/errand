"""A view may be a DIRECTORY ( a scene store, ADR 0017 ): named again, what changed in it comes back to the side that
drives the run; its `last` files ( an index ) are read over there first and put in place after the rest."""
import json
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from errand import test


if test( "the journal says a directory view and its last files; the session marks it so; the side that drives passes it on" ):
    from errand import steps
    from errand.cli.footer import Followed
    from errand.cli.views import Views
    d = Path( tempfile.mkdtemp( dir = "/tmp" ) ).resolve()
    try:
        leaf = d / "errand-outputs" / "runs" / "x" / "leaf"
        ( leaf / "foam.sviz" / "frames" ).mkdir( parents = True )
        journal = leaf / steps.FILE
        import os
        was = os.environ.get( steps.ENV )
        os.environ[ steps.ENV ] = str( journal )
        try:
            assert steps.view( str( leaf / "foam.sviz" ), last = "manifest.json" )
        finally:
            os.environ.pop( steps.ENV, None ) if was is None else os.environ.__setitem__( steps.ENV, was )
        lines = [ json.loads( l ) for l in journal.read_text().splitlines() if l.strip() ]
        assert lines[ -1 ][ "last" ] == [ "manifest.json" ], lines
        marks = [ ]
        with Followed( journal, lambda t: None, view = lambda p, **k: marks.append( ( p, k ) ), root = d ) as f:
            f.look()
        assert marks == [ ( "errand-outputs/runs/x/leaf/foam.sviz", { "dir": True, "last": [ "manifest.json" ] } ) ], marks

        pulled, gate = [ ], threading.Event()

        def pull( rel, **kind ):
            pulled.append( ( rel, kind ) )
            gate.wait( 5 )

        v = Views( d, pull, "far", say = lambda s: None )
        for _ in range( 3 ):
            v( { "op": "view", "path": "s/foam.sviz", "dir": True, "last": [ "manifest.json" ] } )
        gate.set()
        v.wait()
        assert pulled == [ ( "s/foam.sviz", { "dir": True, "last": [ "manifest.json" ] } ) ] * 2, pulled
    finally:
        shutil.rmtree( d, ignore_errors = True )

if test( "a directory view over there: what changed comes, the index after what it names, nothing deleted here",
         tags = [ "ssh", "slow" ] ):
    from _infra import ssh_target
    from errand import layers as L
    host, options, root_of = ssh_target()
    remote = root_of()
    here = Path( tempfile.mkdtemp( dir = "/tmp" ) ).resolve()
    sh = lambda cmd: subprocess.run( [ "ssh", *options, host, cmd ], check = True )
    try:
        sh( f"mkdir -p {remote}/r/foam.sviz/frames && cd {remote}/r/foam.sviz && echo a > frames/000000.bin && "
            f"echo '{{\"frames\":[0]}}' > manifest.json && echo page > index.html" )
        L.fetch_view( "r/foam.sviz", host, remote, here, options, say = lambda *a: None, dir = True, last = [ "manifest.json" ] )
        s = here / "r" / "foam.sviz"
        assert ( s / "frames" / "000000.bin" ).read_text() == "a\n" and json.loads( ( s / "manifest.json" ).read_text() ) == { "frames": [ 0 ] }
        ( s / "mine.txt" ).write_text( "kept" )
        sh( f"cd {remote}/r/foam.sviz && echo b > frames/000001.bin && echo '{{\"frames\":[0,1]}}' > manifest.json && rm index.html" )
        L.fetch_view( "r/foam.sviz", host, remote, here, options, say = lambda *a: None, dir = True, last = [ "manifest.json" ] )
        assert ( s / "frames" / "000001.bin" ).read_text() == "b\n" and json.loads( ( s / "manifest.json" ).read_text() ) == { "frames": [ 0, 1 ] }
        assert ( s / "index.html" ).exists() and ( s / "mine.txt" ).exists(), "nothing deleted here"
        assert not list( here.glob( ".errand-view-*" ) ), "the place aside is gone"
    finally:
        shutil.rmtree( here, ignore_errors = True )
        subprocess.run( [ "ssh", *options, host, f"rm -rf {remote}" ] )
