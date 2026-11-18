"""`errand.download` ( ADR 0013 ): a file by its contents, in the project's cache zone, and, with no route
to it, asked up the chain: the host agent over there, then here."""
import contextlib
import hashlib
import http.server
import json
import os
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path

from errand import test
from errand import downloads as D

BODY = b"a measured sinogram\n" * 1000
SHA = hashlib.sha256( BODY ).hexdigest()


@contextlib.contextmanager
def server( ):
    """A local HTTP server: `/data/sino.h5` is BODY, the rest is 404. -> its base URL, and the hits."""
    hits = [ ]

    class H( http.server.BaseHTTPRequestHandler ):
        def do_GET( self ):
            hits.append( self.path )
            if self.path != "/data/sino.h5":
                self.send_error( 404 )
                return
            self.send_response( 200 )
            self.send_header( "Content-Length", str( len( BODY ) ) )
            self.end_headers()
            self.wfile.write( BODY )

        def log_message( self, *_ ):
            pass

    s = http.server.ThreadingHTTPServer( ( "127.0.0.1", 0 ), H )
    threading.Thread( target = s.serve_forever, daemon = True ).start()
    try:
        yield f"http://127.0.0.1:{s.server_address[ 1 ]}", hits
    finally:
        s.shutdown()


def closed_port( ) -> str:
    with socket.socket() as s:
        s.bind( ( "127.0.0.1", 0 ) )
        port = s.getsockname()[ 1 ]
    return f"http://127.0.0.1:{port}"


def project( ) -> Path:
    root = Path( tempfile.mkdtemp( dir = "/tmp" ) ).resolve()        # short: an agent's socket lives beside
    ( root / "errand-project.py" ).write_text( "" )
    return root


if test( "a download lands under its hash, is found again without the network, checked when a hash is given" ):
    root = project()
    with server() as ( url, hits ):
        p = D.download( f"{url}/data/sino.h5", root = root )
        assert p == root / "errand-cache/downloads" / SHA / "sino.h5" and p.read_bytes() == BODY, p
        assert D.download( f"{url}/data/sino.h5", root = root ) == p and len( hits ) == 1, "the index, not the network"
        assert D.download( "http://elsewhere.invalid/x/sino.h5", SHA, root = root ) == p, "by its hash alone"
        try:
            D.download( f"{url}/data/sino.h5", "0" * 64, name = "other.h5", root = root )
            assert False, "a wrong hash was taken"
        except D.DownloadError as err:
            assert SHA in str( err ) and "0" * 64 in str( err ), err
        assert not ( root / "errand-cache/downloads" / ( "0" * 64 ) ).exists()
        assert not list( ( root / "errand-cache/downloads" / D.WORK / "parts" ).iterdir() ), "no part left"
        try:
            D.download( f"{url}/missing.h5", root = root )
            assert False
        except D.Offline:
            assert False, "a 404 is not a missing route"
        except D.DownloadError as err:
            assert "404" in str( err ), err


if test( "with no route and nobody to ask, the error says how to bring the file" ):
    root = project()
    try:
        D.download( f"{closed_port()}/sino.h5", root = root, relay = False )
        assert False
    except D.DownloadError as err:
        assert not isinstance( err, D.Offline ) and "errand download" in str( err ), err


if test( "two runs that want one file: one downloads, the other waits and finds it" ):
    root = project()
    with server() as ( url, hits ):
        got = [ ]
        ts = [ threading.Thread( target = lambda: got.append( D.download( f"{url}/data/sino.h5", root = root ) ) )
               for _ in range( 4 ) ]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert len( set( got ) ) == 1 and len( hits ) == 1, ( got, hits )


if test( "errand.download and the project's root: from a subdirectory, by the project file" ):
    import errand
    root = project()
    ( root / "sub" ).mkdir()
    old = os.getcwd()
    with server() as ( url, _ ):
        try:
            os.chdir( root / "sub" )
            assert errand.download( f"{url}/data/sino.h5" ) == root / "errand-cache/downloads" / SHA / "sino.h5"
        finally:
            os.chdir( old )


if test( "the cache of downloads is every project's cache zone; what is under way never crosses" ):
    from errand.layers import gateways
    from errand import sync as S
    sel = gateways.selection( Path( tempfile.mkdtemp() ) )
    assert sel.zone( "errand-cache" ) == S.Zone( "/errand-cache", "cache" ) and "errand-cache" in gateways.cache_zones()
    assert sel.skips( "errand-cache/downloads/.errand-work", ".errand-work" )


if test( "a want in the journal is told once, whole lines only" ):
    from errand.cli import footer
    j = Path( tempfile.mkdtemp() ) / "steps.jsonl"
    seen = [ ]
    f = footer.Followed( j, lambda _: None, want = seen.append )
    j.write_text( json.dumps( { "t": 1, "text": "x" } ) + "\n" + json.dumps( { "t": 2, "want": { "id": "a" } } ) + "\n"
                  + '{"t": 3, "want": {"id": "b"' )
    f.look()
    assert seen == [ { "id": "a" } ], seen
    with open( j, "a" ) as out:
        out.write( '}}\n' )
    f.seen = None
    f.look()
    f.seen = None
    f.look()
    assert seen == [ { "id": "a" }, { "id": "b" } ], seen


# -- up the chain, with a `local` agent standing for the host over there ------------------

def agent( d ):
    from errand import agents
    os.environ[ "ERRAND_AGENT" ] = "direct"
    return agents.open( { "kind": "local", "dir": str( d ), "keep_alive": 5 } )


class Offline:
    """The host agent, as one with no route either: its `download` answers so, the rest goes through."""

    def __init__( self, conn ):
        self.conn = conn

    def open( self, req ):
        if req.get( "op" ) != "download":
            return self.conn.open( req )
        return type( "Call", ( ), { "reply": lambda self, timeout = 0: { "ok": False, "offline": True,
                                                                          "failed": "no route" },
                                    "close": lambda self: None } )()


if test( "up the chain: the host agent downloads into the copy, and answers the run" ):
    from errand.cli import relay
    with server() as ( url, _ ):
        there, here = project(), project()
        d = D.downloads_dir( there )
        want = { "id": "w1", "url": f"{url}/data/sino.h5", "sha256": None, "name": "sino.h5", "dir": str( d ),
                 "answer": str( d / D.WORK / "answers/w1/answer.json" ) }
        conn = agent( Path( tempfile.mkdtemp( dir = "/tmp" ) ) )
        said = [ ]
        relay.serve( lambda: conn, here, want, "the host", said.append )
        assert ( d / SHA / "sino.h5" ).read_bytes() == BODY and "downloaded on the host" in said[ -1 ], said
        assert json.loads( Path( want[ "answer" ] ).read_text() ) == { "sha256": SHA }
        assert not ( here / "errand-cache" ).exists(), "nothing downloaded here"


if test( "up the chain to here: a run with no route gets the file this side downloads and sends" ):
    from errand.cli import footer, relay
    from errand import steps
    with server() as ( url, _ ):
        there, here = project(), project()
        conn = agent( Path( tempfile.mkdtemp( dir = "/tmp" ) ) )
        said = [ ]
        serve = relay.through( lambda: Offline( conn ), here, "the host", said.append )
        real = D.fetch

        def fetch( u, d, *a, **kw ):                  # the run, over there, has no route
            if str( d ).startswith( str( there ) ):
                raise D.Offline( f"{u}: no route" )
            return real( u, d, *a, **kw )
        D.fetch = fetch
        journal = Path( tempfile.mkdtemp() ) / "steps.jsonl"
        os.environ[ steps.ENV ] = str( journal )
        try:
            with footer.Followed( journal, lambda _: None, want = serve ):
                p = D.download( f"{url}/data/sino.h5", root = there, relay = True, wait = 30 )
        finally:
            D.fetch = real
            os.environ.pop( steps.ENV, None )
        assert p == there / "errand-cache/downloads" / SHA / "sino.h5" and p.read_bytes() == BODY, p
        assert ( here / "errand-cache/downloads" / SHA / "sino.h5" ).read_bytes() == BODY, "kept here too"
        assert any( "downloaded here, sent to the host" in s for s in said ), said
        assert not ( there / "errand-cache/downloads" / D.WORK / "answers" / "x" ).exists()
        assert not list( ( there / "errand-cache/downloads" / D.WORK / "answers" ).iterdir() ), "the answer, removed"
        # and the next call over there needs nobody
        assert D.download( f"{url}/data/sino.h5", root = there, relay = False ) == p


if test( "up the chain, and nobody can: the run is told why" ):
    from errand.cli import relay
    there, here = project(), project()
    d = D.downloads_dir( there )
    url = closed_port()
    want = { "id": "w2", "url": f"{url}/s.h5", "sha256": None, "name": "s.h5", "dir": str( d ),
             "answer": str( d / D.WORK / "answers/w2/answer.json" ) }
    conn = agent( Path( tempfile.mkdtemp( dir = "/tmp" ) ) )
    said = [ ]
    relay.serve( lambda: Offline( conn ), here, want, "the host", said.append )
    got = json.loads( Path( want[ "answer" ] ).read_text() )
    assert "nor from here" in got[ "error" ], got
