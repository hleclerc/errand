"""A view ( `errand.view` ) is said where it opens: `OUTPUT: file://...` on the machine that drives the run,
the file brought back as soon as it is named when the run is elsewhere -- not at the run's end."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from errand import test

from _infra import run_errand, ssh_target, write_project


@contextlib.contextmanager
def scratch( ):
    d = tempfile.mkdtemp( dir = "/tmp" )
    try:
        yield Path( d ).resolve()
    finally:
        shutil.rmtree( d, ignore_errors = True )


@contextlib.contextmanager
def environ( **values ):
    kept = { k: os.environ.get( k ) for k in values }
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop( k, None )
            else:
                os.environ[ k ] = v
        yield
    finally:
        for k, v in kept.items():
            if v is None:
                os.environ.pop( k, None )
            else:
                os.environ[ k ] = v


if test( "a view says itself where it opens when nobody drives the run, once; nothing outside errand" ):
    from errand import steps
    with scratch() as d:
        out = io.StringIO()
        with environ( **{ steps.ENV: None, steps.RELAY: None } ), contextlib.redirect_stdout( out ):
            assert steps.view( d / "a.html", content = "<p/>" ) is False
        assert out.getvalue() == "", out.getvalue()

        journal = d / steps.FILE
        out = io.StringIO()
        with environ( **{ steps.ENV: str( journal ), steps.RELAY: None } ), contextlib.redirect_stdout( out ):
            assert steps.view( "b.html", content = "<p>1</p>" ) is True
            assert steps.view( "b.html", content = "<p>2</p>" ) is True
        assert out.getvalue() == f"OUTPUT: {( d / 'b.html' ).as_uri()}\n", out.getvalue()
        assert ( d / "b.html" ).read_text() == "<p>2</p>"

        out = io.StringIO()
        with environ( **{ steps.ENV: str( journal ), steps.RELAY: "1" } ), contextlib.redirect_stdout( out ):
            assert steps.view( "c.html", content = "x" ) is True
        assert out.getvalue() == "", "followed: the side that drives it says it"
        assert [ e[ "view" ] for e in steps.read( journal ) if "view" in e ] == [ "b.html", "b.html", "c.html" ]

        got = subprocess.run( [ "sh", "-c", 'eval "$ERRAND_STEPS_SH"; view p.html; view p.html; view /abs/q.svg' ],
                              capture_output = True, text = True,
                              env = { **{ k: v for k, v in os.environ.items() if k != steps.RELAY },
                                      steps.ENV: str( d / "sh.jsonl" ), steps.SH_ENV: steps.SHELL_STEPS } )
        assert got.stdout == f"OUTPUT: file://{d}/p.html\nOUTPUT: file:///abs/q.svg\n", got.stdout


if test( "a session says each view by its path from the copy's root, the last one too" ):
    from errand import steps
    from errand.cli.footer import Followed
    with scratch() as d:
        leaf = d / "errand-outputs" / "runs" / "x" / "leaf"
        leaf.mkdir( parents = True )
        journal = leaf / steps.FILE
        views = [ ]
        with Followed( journal, lambda t: None, view = views.append, root = d ) as f:
            with open( journal, "a" ) as j:
                j.write( json.dumps( { "t": 1, "view": "plot.html" } ) + "\n" )
                j.write( json.dumps( { "t": 2, "view": "/elsewhere/q.html" } ) + "\n" )
            f.look()
            with open( journal, "a" ) as j:          # just before the end: no poll sees it, the exit does
                j.write( json.dumps( { "t": 3, "view": str( d / "top.html" ) } ) + "\n" )
        assert views == [ "errand-outputs/runs/x/leaf/plot.html", "/elsewhere/q.html", "top.html" ], views


if test( "views: one file brought at a time, the last state always, said once where it opens" ):
    from errand.cli.views import Views
    with scratch() as d:
        said, pulled = [ ], [ ]
        gate = threading.Event()

        def pull( rel ):
            pulled.append( rel )
            gate.wait( 5 )
            ( d / rel ).parent.mkdir( parents = True, exist_ok = True )
            ( d / rel ).write_text( str( len( pulled ) ) )

        v = Views( d, pull, "far", say = said.append )
        for _ in range( 5 ):                         # named five times while the first is on its way
            v( { "op": "view", "path": "runs/a.html" } )
        v( { "op": "view", "path": "/not/in/the/copy.html" } )
        time.sleep( 0.1 )
        gate.set()
        v.wait()
        assert pulled == [ "runs/a.html", "runs/a.html" ], pulled
        assert said == [ "OUTPUT: far:/not/in/the/copy.html", f"OUTPUT: {( d / 'runs/a.html' ).as_uri()}" ], said

        said = [ ]
        def broken( rel ):
            raise OSError( "no route" )
        v = Views( d, broken, "far", say = said.append )
        v( { "path": "b.html" } ); v.wait()
        v( { "path": "b.html" } ); v.wait()
        assert len( said ) == 1 and "not brought back from far" in said[ 0 ], said

        said = [ ]
        v = Views( d, None, say = said.append )      # the run is here: only said
        v( { "path": "c.html" } ); v( { "path": "c.html" } )
        assert said == [ f"OUTPUT: {( d / 'c.html' ).as_uri()}" ], said


SHOWN = '''
import errand
from errand import experiment

if p := experiment( "shown" ):
    errand.view( "page.html", content = "<p>there</p>" )
'''


if test( "a run in a session of its own has its view said by the side that drives it", tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ).resolve() / "proj",
                                 'import errand\nerrand.envs[ "vars" ] = errand.Env( [ errand.Vars( { "A": "1" } ) ] )\n',
                                 { "exp_shown.py": SHOWN } )
        code, output = run_errand( project, "run", "-o", "--env", "vars", "exp_shown.py::*" )
        assert code == 0, output
        page = next( ( project / "errand-outputs" / "runs" ).rglob( "page.html" ) )
        assert output.count( "OUTPUT: " ) == 1 and f"OUTPUT: {page.as_uri()}" in output, output


if test( "a view over there comes here as soon as it is named, and is said by its path here", tags = [ "ssh", "slow" ] ):
    host, options, root_of = ssh_target()
    remote_root = root_of()
    PROJECT = ( 'import errand\nerrand.configure( exclude = [ "_lib" ] )\n'
                f'errand.envs[ "over-there" ] = errand.Env( [ errand.Ssh( host = {host!r}, root = {remote_root!r}, '
                f'options = {options!r} ), errand.Vars( {{ "PYTHONPATH": "{remote_root}/_lib" }} ) ] )\n' )
    # The run waits until the page is here: it can only end if the view came before its end.
    WAITS = '''
import os, time
import errand
from errand import experiment, Param

if p := experiment( "waits", local = Param( "" ) ):
    errand.view( "page.html", content = "<p>there</p>" )
    deadline = time.time() + 60
    while not os.path.exists( p.local ) and time.time() < deadline:
        time.sleep( 0.2 )
    p.results[ "seen" ] = os.path.exists( p.local )
'''
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ).resolve() / "proj", PROJECT, { "exp_waits.py": WAITS }, vendor = True )
        flag = f"{remote_root}/flag-over-there"           # what the run waits for, over there
        watcher_stop = threading.Event()

        def watch():                                 # the page here makes the flag the run waits for
            while not watcher_stop.is_set():
                if any( ( project / "errand-outputs" ).rglob( "page.html" ) ):
                    subprocess.run( [ "ssh", *options, host, f"touch {flag}" ] )
                    return
                time.sleep( 0.2 )

        t = threading.Thread( target = watch, daemon = True )
        t.start()
        code, output = run_errand( project, "run", "-o", "--env", "over-there", "exp_waits.py::*",
                                   "--local", flag )
        watcher_stop.set()
        assert code == 0, output
        page = next( ( project / "errand-outputs" / "runs" ).rglob( "page.html" ) )
        assert f"OUTPUT: {page.as_uri()}" in output and output.count( "OUTPUT: " ) == 1, output
        from errand import yamlish
        rec = yamlish.read( next( ( project / "errand-outputs" / "runs" ).rglob( "result.yaml" ) ) )
        assert rec[ "results" ][ "seen" ] is True, "the page came only with the run's end"
    subprocess.run( [ "ssh", *options, host, f"rm -rf {remote_root}" ] )
