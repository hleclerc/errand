"""Agents say what changes ( ADR 0024 ): a subscription waits for its agent's pokes and its bell, sends a full state then
deltas, measures resources only when asked; the watcher applies them and tells its listeners; `errand web` turns them
into notices on `/events`."""
import contextlib
import http.client
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

from errand import test


@contextlib.contextmanager
def scratch( ):
    d = Path( tempfile.mkdtemp( dir = "/tmp" ) ).resolve()
    was = os.environ.get( "ERRAND_CACHE_DIR" )
    os.environ[ "ERRAND_CACHE_DIR" ] = str( d / "cache" )
    try:
        yield d
    finally:
        os.environ.pop( "ERRAND_CACHE_DIR", None ) if was is None else os.environ.__setitem__( "ERRAND_CACHE_DIR", was )
        shutil.rmtree( d, ignore_errors = True )


class Writer:
    """what a subscription sends, kept"""

    def __init__( self ):
        self.events, self.cond = [ ], threading.Condition()

    def send( self, channel, kind, payload ):
        with self.cond:
            self.events.append( json.loads( payload ) )
            self.cond.notify_all()

    def wait( self, pred, timeout = 10.0 ):
        with self.cond:
            return self.cond.wait_for( lambda: any( pred( e ) for e in self.events ), timeout )


if test( "a bell: rung from anywhere on this machine, it wakes the subscriptions of its host agent" ):
    from errand.agents import look
    with scratch() as d:
        root = d / "cache" / "agents" / "host-test-box"
        root.mkdir( parents = True )
        look._bell_reader[ 0 ] = None
        assert look.listen( root ), "a named pipe here"
        w = look.Watch( Writer(), 1, { }, root = None )
        look._watching.add( w )
        try:
            look.ring( [ "p7" ] )
            assert w.poke.wait( 5 ) and "p7" in w.outputs, w.outputs
        finally:
            look._watching.discard( w )
            look._bell_reader[ 0 ] = None

if test( "a subscription: a full state, then deltas when poked; nothing read again while idle; resources when asked" ):
    from errand.agents import look, seen
    with scratch() as d:
        calls = [ 0 ]
        real = seen.runs

        def counted( limit = 50 ):
            calls[ 0 ] += 1
            return real( limit )
        seen.runs = counted
        out = Writer()
        w = look.Watch( out, 1, { "limit": 10, "guests": False } ).start()
        try:
            assert out.wait( lambda e: "seen" in e ) and out.wait( lambda e: "table" in e ), out.events
            time.sleep( 1.5 )
            idle = calls[ 0 ]
            time.sleep( 2.0 )
            assert calls[ 0 ] == idle, "nothing read again while nothing happens"
            leaf = d / "runs" / "r1"
            leaf.mkdir( parents = True )
            seen.note( leaf, d, "a.py::c", "jax" )
            look.nudge()
            assert out.wait( lambda e: "runs" in e and any( r[ "leaf" ] == str( leaf ) for r in e[ "runs" ][ "put" ] ) ), out.events
            assert not any( "resources" in e for e in out.events ), "not asked: not measured"
            w.write( json.dumps( { "resources": True } ).encode() )
            assert out.wait( lambda e: "resources" in e ), out.events
            shutil.rmtree( leaf )
            look.nudge()
            assert out.wait( lambda e: "runs" in e and str( leaf ) in e[ "runs" ][ "drop" ] ), out.events
            look.nudge( [ "p1" ] )
            assert out.wait( lambda e: e.get( "output" ) == [ "p1" ] )
        finally:
            w.detach()
            seen.runs = real

if test( "the watcher: a delta applied to the history, its listeners told" ):
    from errand.tui import machines as TM
    m = TM.Machine( "box" )
    m.history = { "runs": [ { "leaf": "/a", "started": 1 }, { "leaf": "/b", "started": 2 } ] }
    heard = [ ]
    listen = lambda mm, e: heard.append( e )
    TM.LISTENERS.append( listen )
    try:
        m.event( { "runs": { "put": [ { "leaf": "/c", "started": 3 }, { "leaf": "/a", "started": 1, "status": "PASS" } ], "drop": [ "/b" ] } } )
    finally:
        TM.LISTENERS.remove( listen )
    assert [ ( r[ "leaf" ], r.get( "status" ) ) for r in m.history[ "runs" ] ] == [ ( "/c", None ), ( "/a", "PASS" ) ], m.history
    assert heard and "runs" in heard[ 0 ]

if test( "errand web: what agents say becomes notices; `/events` pushes them to a page" ):
    from errand import web as W
    from errand.tui import machines as TM
    from errand.web.server import Web
    with scratch() as d:
        m = TM.Machine( "box" )
        m.table = { "procs": [ { "id": "p1", "leaf": "/x/leaf", "what": "a.py::b" } ] }
        w = Web.start( d / "cache", port = 0, machines_of = lambda: [ m ] )
        try:
            w.machines()
            n0 = w._said_n
            m.event( { "output": [ "p1" ] } )
            n, lists, details = w.notices( n0, wait = 2 )
            assert n > n0 and not lists and json.dumps( [ "work", "box", "/x/leaf" ] ) in details, ( lists, details )
            c = http.client.HTTPConnection( "127.0.0.1", w.port, timeout = 10 )
            cookie = None
            c2 = http.client.HTTPConnection( "127.0.0.1", w.port, timeout = 10 )
            c2.request( "GET", f"/?o={W.once()}", headers = { "Host": f"127.0.0.1:{w.port}" } )
            r = c2.getresponse(); r.read()
            cookie = r.getheader( "Set-Cookie" ).split( ";" )[ 0 ]
            c.request( "GET", "/events", headers = { "Host": f"127.0.0.1:{w.port}", "Cookie": cookie } )
            r = c.getresponse()
            assert r.status == 200 and r.getheader( "Content-Type" ) == "text/event-stream"
            assert r.fp.readline().startswith( b": open" )
            r.fp.readline()
            threading.Timer( 0.3, lambda: m.event( { "table": m.table } ) ).start()
            line = r.fp.readline()
            assert line.startswith( b"data: " ) and json.loads( line[ 6 : ] )[ "lists" ] is True, line
            c.close()
        finally:
            w.stop()
