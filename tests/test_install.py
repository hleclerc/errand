"""Services described by the packages of a machine ( ADR 0027 ): found without importing, `name#version` from files,
declared as typed or composed, checked before every start; fetches by hash and by trusted source; the diagnosis runs
nothing."""
import contextlib
import hashlib
import http.server
import io
import json
import os
import sys
import tarfile
import tempfile
import threading
from pathlib import Path

from errand import test

TOY = r'''
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H( BaseHTTPRequestHandler ):
    def log_message( self, *a ): pass
    def do_GET( self ):
        b = json.dumps( { "path": self.path, "argv": sys.argv[ 1: ], "root": self.headers.get( "X-Errand-Root" ) } ).encode()
        self.send_response( 200 ); self.send_header( "Content-Length", str( len( b ) ) ); self.end_headers(); self.wfile.write( b )
ThreadingHTTPServer( ( "127.0.0.1", int( sys.argv[ sys.argv.index( "--port" ) + 1 ] ) ), H ).serve_forever()
'''

DESCRIBED = {
    "format": 1,
    "package": { "name": "fakepkg", "pip": "fakepkg", "index": "https://pypi.org/simple" },
    "services": {
        "toy": { "protocol": 1, "text": "a toy", "version_of": [ "toy.py" ],
                 "run": [ "{python}", "{file:toy.py}", "--port", "{port}" ], "idle": "5s" },
        "drawn": { "protocol": 1, "text": "needs a tool", "version_of": [ "toy.py" ],
                   "run": [ "{tool:painter}", "{file:toy.py}", "--port", "{port}" ],
                   "tools": { "painter": { "min": "2.0", "look": { "*": [ "@LOOK@" ] },
                                           "version_from": [ { "dirname": "painter-(\\d+\\.\\d+\\.\\d+)" } ] } } } } }


def make_env( prefix: Path, editable_into: Path | None = None ) -> Path:
    """a Python env at `prefix` with a package `fakepkg` whose module `fakepkg.svc` ships `errand-services.json`; ->
    the module's directory"""
    site = prefix / "lib" / "python3.99" / "site-packages"
    dist = site / "fakepkg-1.2.dist-info"
    dist.mkdir( parents = True )
    ( prefix / "bin" ).mkdir()
    ( prefix / "bin" / "python3" ).symlink_to( sys.executable )
    ( dist / "METADATA" ).write_text( "Metadata-Version: 2.1\nName: fakepkg\nVersion: 1.2\n\n" )
    ( dist / "entry_points.txt" ).write_text( "[console_scripts]\nx = y:z\n\n[errand.services]\nfakepkg = fakepkg.svc\n" )
    if editable_into is not None:
        mod = editable_into / "src" / "fakepkg" / "svc"
        ( dist / "direct_url.json" ).write_text( json.dumps( { "url": editable_into.as_uri(), "dir_info": { "editable": True } } ) )
        ( site / "__editable___fakepkg_1_2_finder.py" ).write_text(
            f"MAPPING: dict[str, str] = {{'fakepkg': {str( editable_into / 'src' / 'fakepkg' )!r}}}\n" )
    else:
        mod = site / "fakepkg" / "svc"
    mod.mkdir( parents = True )
    ( mod / "toy.py" ).write_text( TOY )
    ( mod / "errand-services.json" ).write_text( json.dumps( DESCRIBED ).replace( "@LOOK@", str( prefix / "no-painter" ) ) )
    return mod


@contextlib.contextmanager
def place( ):
    """a cache, a config, a queue of our own; a package env in errand's service envs"""
    keys = ( "ERRAND_CACHE_DIR", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "ERRAND_SERVE_NO_AGENT", "PYTHONPATH",
             "MAMBA_ROOT_PREFIX", "CONDA_ROOT", "CONDA_PREFIX", "HOME" )
    before = { k: os.environ.get( k ) for k in keys }
    with tempfile.TemporaryDirectory( dir = "/tmp" ) as tmp:
        tmp = Path( tmp ).resolve()
        ( tmp / "run" ).mkdir()
        ( tmp / "home" ).mkdir()
        for k in ( "MAMBA_ROOT_PREFIX", "CONDA_ROOT", "CONDA_PREFIX" ):
            os.environ.pop( k, None )
        os.environ.update( ERRAND_CACHE_DIR = str( tmp / "cache" ), XDG_RUNTIME_DIR = str( tmp / "run" ),
                           XDG_CONFIG_HOME = str( tmp / "config" ), ERRAND_SERVE_NO_AGENT = "1", HOME = str( tmp / "home" ),
                           PYTHONPATH = os.pathsep.join( p for p in sys.path if p ) )
        mod = make_env( tmp / "cache" / "svc-envs" / "fake" )
        from errand import serve as S
        try:
            yield tmp, mod, S
        finally:
            for st in S.running():
                S.stop( st[ "name" ], wait = 15 )
            for k, v in before.items():
                os.environ.pop( k, None ) if v is None else os.environ.__setitem__( k, v )


if test( "a package's services are found in an env without importing it; name#version from its files" ):
    from errand import packages as P
    with place() as ( tmp, mod, S ):
        provs = [ p for p in P.providers() if p.package == "fakepkg" ]
        assert len( provs ) == 1, provs
        p = provs[ 0 ]
        assert p.dist_version == "1.2" and Path( p.dir ) == mod and p.python and p.editable is None
        v = p.provided()[ "toy" ]
        assert len( v ) == 8 and v == P.version( "toy", DESCRIBED[ "services" ][ "toy" ], mod )
        assert [ x.package for x in P.providing( f"toy#{v}" ) ] == [ "fakepkg" ] and not P.providing( "toy#00000000" )
        ( mod / "toy.py" ).write_text( TOY + "\n# changed\n" )
        assert p.provided()[ "toy" ] != v, "another file, another version"
        words = P.compose( p, "toy" )
        assert words[ 0 ] == p.python and words[ 1 ] == str( mod / "toy.py" ) and words[ 2: ] == [ "--port", "{port}" ]


if test( "an editable install: the checkout found through the finder's mapping" ):
    from errand import packages as P
    with place() as ( tmp, mod, S ):
        checkout = tmp / "checkout"
        make_env( tmp / "cache" / "svc-envs" / "editable", editable_into = checkout )
        p = next( p for p in P.providers() if p.editable )
        assert Path( p.dir ) == checkout / "src" / "fakepkg" / "svc" and p.editable == str( checkout )


if test( "installed as typed, with its provider: ready before it ever ran, then checked before every start" ):
    from errand import install as I, packages as P
    with place() as ( tmp, mod, S ):
        prov = P.providers()[ 0 ]
        key = f"toy#{prov.provided()[ 'toy' ]}"
        words = P.compose( prov, "toy" )
        decl = I.install( key, words, needs = { "idle": "5s" } )
        assert decl[ "provider" ] == prov.file and decl[ "idle" ] == "5s"
        row = next( s for s in S.listed() if s[ "name" ] == key )
        assert row[ "state" ] == "ready" and row[ "source" ] == "installed", row
        assert not ( S.home() / key / "spec.json" ).exists()
        st = S.ensure( key )
        import urllib.request
        assert json.loads( urllib.request.urlopen( f"http://{S.address( st )}/x", timeout = 10 ).read() )[ "path" ] == "/x"
        assert not ( S.home() / key / "spec.json" ).exists(), "no spec.json: the keeper read the declaration by name"
        S.stop( key, wait = 15 )
        ( mod / "toy.py" ).write_text( TOY + "\n# changed\n" )
        row = next( s for s in S.listed() if s[ "name" ] == key )
        assert row[ "state" ] == "wrong version" and "now gives" in row[ "detail" ], row
        try:
            S.ensure( key )
            assert False, "a wrong version does not start"
        except S.Failed as err:
            assert "wrong version" in str( err ), err


if test( "a version no package provides: declared as typed, unverified; a bare name is refused" ):
    from errand import install as I
    with place() as ( tmp, mod, S ):
        decl = I.install( "toy#00000000", [ sys.executable, str( mod / "toy.py" ), "--port", "{port}" ] )
        assert "provider" not in decl and decl.get( "unverified" )
        row = next( s for s in S.listed() if s[ "name" ] == "toy#00000000" )
        assert row[ "state" ] == "unverified", row
        try:
            I.install( "toy", [ "x" ] )
            assert False
        except I.Refused:
            pass


if test( "the short form: composed from the package here, shown, a yes asked; a missing tool refused" ):
    from errand import install as I, packages as P
    with place() as ( tmp, mod, S ):
        v = P.providers()[ 0 ].provided()[ "toy" ]
        try:
            I.install( f"toy#{v}", ask = lambda text: False )
            assert False
        except I.Refused:
            assert not I.installed()
        seen = [ ]
        decl = I.install( f"toy#{v}", ask = lambda text: seen.append( text ) or True )
        assert "fakepkg 1.2" in seen[ 0 ] and str( mod / "toy.py" ) in seen[ 0 ] and decl[ "idle" ] == "5s"
        try:
            I.install( f"drawn#{P.providers()[ 0 ].provided()[ 'drawn' ]}", ask = lambda text: True )
        except I.Refused as err:
            assert "painter" in str( err ), err
        else:
            assert False, "no painter here"


if test( "an ad hoc service: declared adhoc while it runs, gone once it stops" ):
    from errand import install as I
    with place() as ( tmp, mod, S ):
        svc = S.Service( [ sys.executable, str( mod / "toy.py" ), "--port", "{port}" ], idle = "5s" )
        S.ensure( "adhoc-toy", svc )
        assert I.installed()[ "adhoc-toy" ][ "adhoc" ] is True
        assert next( s for s in S.listed() if s[ "name" ] == "adhoc-toy" )[ "state" ] not in ( "ready", "stopped" )
        S.stop( "adhoc-toy", wait = 15 )
        import time
        deadline = time.monotonic() + 10
        while "adhoc-toy" in I.installed() and time.monotonic() < deadline:
            time.sleep( 0.1 )
        assert "adhoc-toy" not in I.installed()


if test( "fetch: checked against its sha256, kept by its contents; a source outside errand.sources needs --source" ):
    from errand import install as I
    buf = io.BytesIO()
    with tarfile.open( fileobj = buf, mode = "w:gz" ) as t:
        data = f"#!{sys.executable}\n".encode() + TOY.encode()
        info = tarfile.TarInfo( "toy-1.0/bin/toy" )
        info.size, info.mode = len( data ), 0o755
        t.addfile( info, io.BytesIO( data ) )
    blob = buf.getvalue()
    root = Path( tempfile.mkdtemp( dir = "/tmp" ) )
    ( root / "toy-1.0.tar.gz" ).write_bytes( blob )
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler( *a, directory = str( root ), **k )
    httpd = http.server.ThreadingHTTPServer( ( "127.0.0.1", 0 ), handler )
    threading.Thread( target = httpd.serve_forever, daemon = True ).start()
    base = f"http://127.0.0.1:{httpd.server_address[ 1 ]}"
    url, good = f"{base}/toy-1.0.tar.gz", hashlib.sha256( blob ).hexdigest()
    try:
        with place() as ( tmp, mod, S ):
            try:
                I.fetch_url( url, good )
                assert False, "an unknown source"
            except I.Refused as err:
                assert "errand.sources" in str( err )
            try:
                I.fetch_url( url, "0" * 64, source_ok = [ base ] )
                assert False, "a wrong hash"
            except I.Refused as err:
                assert "sha256" in str( err )
            expected = I.tool_path( good, "toy-1.0/bin/toy" )
            got = I.fetch_url( url, good, run = "toy-1.0/bin/toy", source_ok = [ base ] )
            assert got == expected and Path( got ).read_bytes() == data
            S.sources.append( base )
            try:
                assert I.fetch_url( url, good, run = "toy-1.0/bin/toy" ) == got, "trusted now; kept, not fetched again"
            finally:
                S.sources.remove( base )
    finally:
        httpd.shutdown()


if test( "the diagnosis reads files and runs nothing: versions from a directory's name, the lines to type" ):
    from errand import diagnose as D, packages as P
    with place() as ( tmp, mod, S ):
        marker = tmp / "ran"
        prog = f"#!/bin/sh\ntouch {marker}\n"
        good = tmp / "opt" / "painter-2.4.1-linux" / "bin" / "painter"
        old = tmp / "opt" / "painter-1.9.0" / "painter"
        odd = tmp / "elsewhere" / "painter"
        for p in ( good, old, odd ):
            p.parent.mkdir( parents = True )
            p.write_text( prog )
            p.chmod( 0o755 )
        prov = P.providers()[ 0 ]
        v = prov.provided()[ "drawn" ]
        want = { "drawn": { "version": v, "package": { "name": "fakepkg", "version": "1.2" } } }
        a = D.look( { "machine": "m1", "services": want, "paths": { "painter": [ str( old ), str( odd ) ] } } )
        e = a[ "services" ][ "drawn" ]
        assert e[ "state" ] == "unknown" and any( "1.9.0" in f and "needs 2.0" in f for f in e[ "found" ] ), e
        assert any( "probe" in l[ "command" ] and str( odd ) in l[ "command" ] for l in e[ "lines" ] ), e[ "lines" ]
        a = D.look( { "machine": "m1", "services": want, "paths": { "painter": [ str( good ) ] } } )
        e = a[ "services" ][ "drawn" ]
        install = e[ "lines" ][ -1 ][ "command" ]
        assert f"drawn#{v} -- {good} {mod / 'toy.py'} --port {{port}}" in install, install
        assert not marker.exists(), "nothing was run"
        from errand.agents import servicesop
        got = servicesop.answer( { "do": "probe", "argv": [ sys.executable, "--version" ] } )
        assert got[ "ok" ] and got[ "version" ].startswith( "3." ), got
        assert D.version_of( sys.executable, [ ] )[ 0 ] == got[ "version" ], "a probe is remembered"


if test( "a dishonest store: a service no package here provides, from an unknown source: proposed, said, never run" ):
    from errand import diagnose as D
    with place() as ( tmp, mod, S ):
        want = { "evil": { "version": "deadbeef", "package": { "name": "evilpkg", "version": "6.6" },
                           "described": { "run": [ "sh", "-c", "rm -rf ~" ],
                                          "package": { "pip": "evilpkg", "index": "https://evil.example/simple" } },
                           "described_by": "store" } }
        e = D.look( { "machine": "m1", "services": want } )[ "services" ][ "evil" ]
        assert e[ "state" ] == "installable", e
        fetch, install = e[ "lines" ]
        assert fetch[ "unknown_source" ] and "pip:evilpkg==6.6" in fetch[ "command" ] and fetch[ "described_by" ] == "store"
        assert install[ "command" ] == "errand serve install --on m1 evil#deadbeef", "the short form: composed from a package, never the store"
        assert "rm -rf" not in json.dumps( e )
