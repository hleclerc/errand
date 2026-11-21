"""`errand stop ID`: what errand runs, stopped by the id `errand status` shows -- running, or waiting in the
machine's queue --, through its owner's `kill` ( the same as `k` in `errand tui` ). A queued run that is stopped
leaves the queue, and what waited behind it moves up."""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from errand import test

REPO = str( Path( __file__ ).resolve().parent.parent )


@contextlib.contextmanager
def scratch( ):
    d = tempfile.mkdtemp( dir = "/tmp" )
    try:
        yield Path( d )
    finally:
        shutil.rmtree( d, ignore_errors = True )


@contextlib.contextmanager
def private_queue( base: Path ):
    """A queue of our own ( `test_queue.private_queue` ): what the machine really runs is not waited for, and
    the claim of the run executing this file is not inherited by what it starts."""
    from errand import queue as Q
    keys = ( "XDG_RUNTIME_DIR", Q.CLAIM, "ERRAND_NO_QUEUE" )
    before = { k: os.environ.get( k ) for k in keys }
    os.environ[ "XDG_RUNTIME_DIR" ] = str( base )
    os.environ.pop( Q.CLAIM, None )
    os.environ.pop( "ERRAND_NO_QUEUE", None )
    try:
        yield
    finally:
        for k, v in before.items():
            if v is None:
                os.environ.pop( k, None )
            else:
                os.environ[ k ] = v


def claimer( label ):
    """A run that wants the machine to itself, and keeps it a minute once it has it."""
    line = ( "import time; from errand import queue as Q\n"
             f"with Q.claim( {{ }}, exclusive = True, label = {label!r} ):\n"
             "    time.sleep( 60 )\n" )
    return [ "sh", "-c", f'unset ERRAND_CLAIM ERRAND_NO_QUEUE; exec "{sys.executable}" -c "$0"', line ]


def until( what, within = 15 ):
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        got = what()
        if got:
            return got
        time.sleep( 0.1 )
    return what()


if sys.platform != "win32" and test( "stop: a run waiting in the queue leaves it, a running one stops, what waited moves up" ):
    from errand import agents, queue as Q
    from errand.agents import ledger, table as T
    from errand.cli import stop as S
    os.environ[ "ERRAND_AGENT" ] = "direct"
    agents._open.clear()
    with scratch() as base, private_queue( base ):
        d = base / "agents" / "s"
        conn = agents.open( { "kind": "local", "dir": str( d ), "keep_alive": 5 } )
        env = { "PYTHONPATH": REPO, "XDG_RUNTIME_DIR": str( base ) }
        here = ledger.here_name()

        def rows():
            return { r[ "id" ]: r for r in T.procs_of( d, T.served( d ) ) }

        def got():
            return [ ( here, { "time": time.time(), "procs": list( rows().values() ), "vms": [ ], "guests": [ ] }, None ) ]

        def stop( *words ):
            out = io.StringIO()
            with contextlib.redirect_stdout( out ):
                rc = S.main( base, list( words ), got = got() )
            return rc, out.getvalue()

        ids = [ ]
        try:
            ids.append( agents.start( conn, claimer( "holder" ), env = env ) )
            assert until( lambda: [ q for q in Q.held() if q.get( "label" ) == "holder" ] ), "the holder never got the machine"
            ids.append( agents.start( conn, claimer( "first" ), env = env ) )
            assert until( lambda: [ w for w in Q.waiting() if w.get( "label" ) == "first" ] )
            ids.append( agents.start( conn, claimer( "second" ), env = env ) )
            assert until( lambda: [ w[ "label" ] for w in Q.waiting() ] == [ "first", "second" ] ), Q.waiting()
            holder, first, second = ids
            assert until( lambda: ( rows().get( first ) or { } ).get( "waiting" ) ), rows()
            assert "room on" in rows()[ first ][ "waiting" ][ "what" ], rows()[ first ]

            # the one waiting first: out of the queue, out of the list; the holder still runs
            rc, said = stop( first[ : 8 ] )
            assert rc == 0 and "stopped" in said and "was waiting: room on" in said, said
            assert first not in rows(), "a stopped id is still listed"
            assert [ w[ "label" ] for w in Q.waiting() ] == [ "second" ], Q.waiting()
            assert holder in rows() and second in rows()

            # the one running: stopped, and what waited behind gets the machine
            rc, said = stop( holder[ : 8 ] )
            assert rc == 0 and "was running" in said, said
            assert holder not in rows()
            assert until( lambda: [ q for q in Q.held() if q.get( "label" ) == "second" ] ), "the next in the queue never moved up"
            assert until( lambda: not ( rows().get( second ) or { } ).get( "waiting" ) ), rows().get( second )

            # what names nothing, or too little, is said, and stops nothing
            rc, said = stop( "ffffffffffff" )
            assert rc == 1 and "nothing of errand's runs under that id" in said, said
            rc, said = stop( "ab" )
            assert rc == 2, said
            assert second in rows()
            rc, said = stop( second )
            assert rc == 0 and second not in rows(), said
        finally:
            for i in ids:
                r = rows().get( i )
                if r and r.get( "pgid" ):
                    with contextlib.suppress( OSError ):
                        os.killpg( r[ "pgid" ], 9 )
            conn.close()
            agents._open.clear()


if test( "stop: an id shared by several processes, a guest's, a machine that could not be asked: said, nothing sent" ):
    from errand.cli import stop as S
    now = time.time()
    row = lambda i, **kw: { "agent": "a", "id": i, "pid": 1, "pgid": 4242, "since": 1, "started": now, "state": "running",
                            "project": "/x/sdot", "what": f"run {i}", "mark": f"/m/{i}", **kw }
    got = [ ( "mac", { "time": now, "procs": [ row( "aaaa1111" ), row( "aaaa2222" ) ], "vms": [ ],
                       "guests": [ { "vm": "80103674ede5f052", "procs": [ row( "bbbb1111" ) ] } ] }, None ),
            ( "n14", { "time": now, "procs": [ row( "cccc1111", pgid = 77, waiting = { "what": "room on node14: the machine to itself" } ),
                                               row( "dddd1111", project = "/x/other" ) ], "vms": [ ], "guests": [ ] }, None ),
            ( "lmo", None, "ssh: connect timed out" ) ]
    sent = [ ]
    out = io.StringIO()
    project = Path( tempfile.mkdtemp( dir = "/tmp" ) ) / "sdot"        # its --batch records are looked for there
    project.mkdir()
    with contextlib.redirect_stdout( out ):
        rc = S.main( project, [ "aaaa", "bbbb", "cccc" ], got = got,
                     sender = lambda m, req: sent.append( ( m, req ) ) or { "ok": True, "gone": True } )
    said = out.getvalue()
    assert rc == 1, said
    assert sent == [ ( "n14", { "pgid": 77, "since": 1, "mark": "/m/cccc1111" } ) ], sent
    for want in ( "aaaa: names 2 processes", "windows guest", "cccc1111", "on n14: stopped", "was waiting: room on node14",
                  "lmo: could not be asked" ):
        assert want in said, f"{want!r} not in:\n{said}"
    # --mine: this project's, wherever they run; another project's left alone
    sent.clear()
    with contextlib.redirect_stdout( io.StringIO() ):
        S.main( project, [ ], mine = True, got = got,
                sender = lambda m, req: sent.append( ( m, req[ "mark" ] ) ) or { "ok": True } )
    assert sorted( sent ) == [ ( "mac", "/m/aaaa1111" ), ( "mac", "/m/aaaa2222" ), ( "n14", "/m/cccc1111" ) ], sent
    shutil.rmtree( project.parent, ignore_errors = True )


if test( "stop alone: what runs or waits, numbered, this project first; the answer says which" ):
    from errand.cli import stop as S
    assert S.parse_choice( "1 3", 4 ) == [ 0, 2 ] and S.parse_choice( "2-4,1", 4 ) == [ 1, 2, 3, 0 ]
    assert S.parse_choice( "all", 3 ) == [ 0, 1, 2 ]
    for wrong in ( "0", "5", "x", "3-1" ):
        try:
            S.parse_choice( wrong, 4 )
        except ValueError:
            continue
        raise AssertionError( f"{wrong!r} was taken" )
    now = time.time()
    row = lambda i, project, **kw: { "agent": "a", "id": i, "pid": 1, "pgid": 4242, "since": 1, "started": now - 60,
                                     "state": "running", "project": project, "what": f"run {i}", "mark": f"/m/{i}", **kw }
    got = [ ( "n14", { "time": now, "procs": [ row( "eeee1111", "/h/other" ),
                                               row( "ffff1111", "/h/sdot", waiting = { "what": "room on node14: the machine to itself" } ),
                                               row( "aaaa9999", "/h/sdot", kind = "agent", what = "environment agent env-1" ) ],
                       "vms": [ ], "guests": [ ] }, None ) ]
    project = Path( tempfile.mkdtemp( dir = "/tmp" ) ) / "sdot"
    project.mkdir()
    try:
        sent, asked = [ ], [ ]
        answers = iter( [ "9", "1" ] )
        out = io.StringIO()
        with contextlib.redirect_stdout( out ):
            rc = S.main( project, [ ], got = got, ask = lambda q: asked.append( q ) or next( answers ),
                         sender = lambda m, req: sent.append( req[ "mark" ] ) or { "ok": True, "gone": True } )
        said = out.getvalue()
        lines = [ l for l in said.splitlines() if l.strip()[ : 1 ].isdigit() ]
        assert "ffff1111" in lines[ 0 ] and "waiting: room on node14" in lines[ 0 ] and "eeee1111" in lines[ 1 ], said
        assert "aaaa9999" not in said, "an agent kept warm was offered"
        assert rc == 0 and sent == [ "/m/ffff1111" ] and len( asked ) == 2, ( rc, sent, said )
        sent.clear()
        with contextlib.redirect_stdout( io.StringIO() ):
            assert S.main( project, [ ], got = got, ask = lambda q: "", sender = lambda m, req: sent.append( m ) ) == 0
        assert sent == [ ], "Enter stopped something"
    finally:
        shutil.rmtree( project.parent, ignore_errors = True )
