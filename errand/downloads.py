"""`errand.download( url )` ( ADR 0013 ): a file by its contents, in a cache errand declares itself.

    <root>/errand-cache/downloads/<sha256>/<name>          the file, under the hash of its contents
    <root>/errand-cache/downloads/by-url/<hash of url>.json   which hash a URL gave ( when none was given )
    <root>/errand-cache/downloads/.errand-work/              parts, locks, answers: never part of a sync

`errand-cache` is a cache zone ( ADR 0012 ) of every project: pushed when missing over there, brought
back when missing here, never replaced nor deleted. A file is named by its hash, so two machines that
fetch it write the same bytes at the same path.

A run that cannot reach the URL asks up the chain: a `want` line in its journal ( `steps` ), said by
its session to the side that drives it ( `cli.footer.Followed`, `cli.sessions.follow` ), which asks
the host agent over there, then downloads it here and sends it ( `relay` ). `ERRAND_RELAY` says a run
is followed, so that one nobody follows does not wait for an answer that will never come.

Imported by `errand` itself: standard library only, and cheap.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ZONE    = "errand-cache"             # from the project root: a cache zone of every project
SUB     = "downloads"
RELAY   = "ERRAND_RELAY"             # set by errand on a run whose session is followed
CHUNK   = 1 << 20
WAIT    = 24 * 3600.0                # how long a run waits for the side that drives it
STALE_LOCK = 3600.0
WORK    = ".errand-work"             # in the downloads: what is under way, excluded from every sync


class DownloadError( Exception ):
    pass


class Offline( DownloadError ):
    """The URL cannot be reached from here: no route, no name, refused, timed out."""


# -- where ----------------------------------------------------------------------

def project_root( start = None ) -> Path:
    """The nearest directory above `start` ( the current one ) that holds a project file."""
    here = Path( start or Path.cwd() ).resolve()
    for d in ( here, *here.parents ):
        if any( p.is_file() for p in d.glob( "errand-*.py" ) ):
            return d
    raise FileNotFoundError( f"no project file ( errand-*.py ) in {here} or above: where does the project start?" )


def downloads_dir( root = None ) -> Path:
    return Path( root or project_root() ) / ZONE / SUB


def name_of( url: str ) -> str:
    """The file's name, from the URL's path: what a tool that reads the extension needs."""
    name = urllib.parse.unquote( urllib.parse.urlparse( url ).path.rstrip( "/" ).rsplit( "/", 1 )[ -1 ] )
    name = "".join( c if c.isalnum() or c in "._-+" else "_" for c in name ).lstrip( "." )
    return name or "download"


def _url_key( url: str ) -> str:
    return hashlib.sha256( url.encode() ).hexdigest()[ : 32 ]


def _index( d: Path, url: str ) -> Path:
    return d / "by-url" / f"{_url_key( url )}.json"


def known( d: Path, url: str, sha256: str | None, name: str ) -> Path | None:
    """The file, if it is already here: by its hash when given, else through the URL's index."""
    if sha256:
        p = d / sha256 / name
        return p if p.is_file() else None
    try:
        got = json.loads( _index( d, url ).read_text() )
    except ( OSError, ValueError ):
        return None
    p = d / got.get( "sha256", "" ) / got.get( "name", name )
    return p if got.get( "sha256" ) and p.is_file() else None


def _remember( d: Path, url: str, sha256: str, name: str ):
    p = _index( d, url )
    p.parent.mkdir( parents = True, exist_ok = True )
    part = p.with_name( f".{p.name}.{os.getpid()}.part" )
    part.write_text( json.dumps( { "url": url, "sha256": sha256, "name": name } ) )
    os.replace( part, p )


# -- one machine ----------------------------------------------------------------

class _Locked:
    """One download of a file at a time, across processes and machines that share the disk."""

    def __init__( self, path: Path ):
        self.path = path

    def __enter__( self ):
        self.path.parent.mkdir( parents = True, exist_ok = True )
        while True:
            try:
                os.mkdir( self.path )
                return self
            except OSError as err:
                if err.errno != errno.EEXIST:
                    raise
            try:
                if time.time() - self.path.stat().st_mtime > STALE_LOCK:
                    os.rmdir( self.path )
                    continue
            except OSError:
                continue
            time.sleep( 0.2 )

    def __exit__( self, *_ ):
        try:
            os.rmdir( self.path )
        except OSError:
            pass


def _offline( err: BaseException ) -> bool:
    if isinstance( err, urllib.error.HTTPError ):
        return False
    reason = getattr( err, "reason", err )
    return isinstance( reason, ( socket.gaierror, socket.timeout, TimeoutError, ConnectionError, OSError ) )


def fetch( url: str, d: Path, name: str, sha256: str | None = None, say = None, timeout = 30.0 ) -> str:
    """`url` into `d/<its hash>/name`, checked against `sha256` when given. -> its hash. `Offline` when it
    cannot be reached; a `DownloadError` for anything else ( an HTTP error, a hash that does not match )."""
    from .steps import step
    parts = d / WORK / "parts"
    parts.mkdir( parents = True, exist_ok = True )
    part = parts / f"{name}.{os.getpid()}.{time.time_ns()}"
    h = hashlib.sha256()
    try:
        try:
            got = urllib.request.urlopen( urllib.request.Request( url, headers = { "User-Agent": "errand" } ),
                                          timeout = timeout )
        except ( urllib.error.URLError, OSError ) as err:
            if _offline( err ):
                raise Offline( f"{url}: {getattr( err, 'reason', err )}" ) from None
            raise DownloadError( f"{url}: {err}" ) from None
        with got, open( part, "wb" ) as f:
            total = int( got.headers.get( "Content-Length" ) or 0 )
            size, said = 0, 0.0
            while True:
                try:
                    chunk = got.read( CHUNK )
                except ( OSError, urllib.error.URLError ) as err:
                    raise DownloadError( f"{url}: cut after {size} bytes ( {err} )" ) from None
                if not chunk:
                    break
                f.write( chunk )
                h.update( chunk )
                size += len( chunk )
                if time.monotonic() - said > 0.5:
                    said = time.monotonic()
                    step( f"download {name}: {size / 1e6:.1f} MB" + ( f" of {total / 1e6:.1f}" if total else "" ),
                          done = size / total if total else None )
        digest = h.hexdigest()
        if sha256 and digest != sha256.lower():
            raise DownloadError( f"{url}: its sha256 is {digest}, not {sha256} as asked -- removed" )
        target = d / digest / name
        target.parent.mkdir( parents = True, exist_ok = True )
        os.replace( part, target )
        if say:
            say( f"downloaded {name} ( {size / 1e6:.1f} MB, sha256 {digest} )" )
        return digest
    finally:
        try:
            part.unlink()
        except OSError:
            pass


def download( url: str, sha256: str | None = None, name: str | None = None, *, root = None,
              relay: bool | None = None, wait = WAIT ) -> Path:
    """The path of the file at `url`, downloaded into the project's cache if it is not there yet
    ( ADR 0013 ). `sha256`, when given, is checked; it is never required. `name`: the file's name,
    else the last part of the URL's path.

    With no route to the URL, a run that errand follows asks the side that drives it, which tries
    the host over there, then itself ( `relay`, by default when errand says the run is followed )."""
    d = downloads_dir( root )
    name = name or name_of( url )
    sha256 = sha256.lower() if sha256 else None
    found = known( d, url, sha256, name )
    if found is not None:
        return found
    with _Locked( d / WORK / "locks" / _url_key( url ) ):
        found = known( d, url, sha256, name )             # fetched by another run meanwhile
        if found is not None:
            return found
        try:
            digest = fetch( url, d, name, sha256 )
        except Offline as err:
            if relay is None:
                relay = bool( os.environ.get( RELAY ) )
            if not relay:
                raise DownloadError( f"{err}. No way from here, and nothing up the chain to ask: download it where "
                                     f"there is one ( `errand download {url}` ), and the next push brings it" ) from None
            digest = ask_up( d, url, sha256, name, wait = wait )
        _remember( d, url, digest, name )
    return d / digest / name


# -- up the chain -----------------------------------------------------------------

def ask_up( d: Path, url: str, sha256: str | None, name: str, wait = WAIT ) -> str:
    """Ask the side that drives this run, and wait for its answer. -> the file's hash."""
    from .steps import _current, step
    ident = f"{os.getpid()}-{time.time_ns()}"
    answer = d / WORK / "answers" / ident / "answer.json"
    want = { "id": ident, "url": url, "sha256": sha256, "name": name, "dir": str( d.resolve() ),
             "answer": str( answer.resolve() ) }
    journal = _current()
    if journal is None:
        raise DownloadError( f"{url}: no way from here, and no journal to ask through" )
    journal.add( { "want": want }, now = True )
    step( f"download {name}: asked up the chain" )
    deadline = time.monotonic() + wait
    try:
        while time.monotonic() < deadline:
            try:
                got = json.loads( answer.read_text() )
            except ( OSError, ValueError ):
                time.sleep( 0.5 )
                continue
            if got.get( "error" ):
                raise DownloadError( f"{url}: {got[ 'error' ]}" )
            digest = got[ "sha256" ]
            if not ( d / digest / name ).is_file():
                raise DownloadError( f"{url}: answered, but {d / digest / name} is not there" )
            return digest
        raise DownloadError( f"{url}: no answer from up the chain in {wait:.0f} s" )
    finally:
        shutil.rmtree( answer.parent, ignore_errors = True )


def write_answer( path, answer: dict ):
    """What a run waits for: written whole, then renamed."""
    path = Path( path )
    path.parent.mkdir( parents = True, exist_ok = True )
    part = path.with_name( f".{path.name}.part" )
    part.write_text( json.dumps( answer ) )
    os.replace( part, path )


def serve_want( want: dict ) -> dict:
    """Over there, in an agent: the file a run wants, fetched into its `dir`, and the answer written
    where it waits. -> { "sha256" } or { "error", "offline" }."""
    d = Path( want[ "dir" ] )
    try:
        # No lock: the run that asks holds it, and waits for this.
        found = known( d, want[ "url" ], want.get( "sha256" ), want[ "name" ] )
        digest = found.parent.name if found is not None else \
            fetch( want[ "url" ], d, want[ "name" ], want.get( "sha256" ) )
    except Offline as err:
        return { "error": str( err ), "offline": True }
    except DownloadError as err:
        write_answer( want[ "answer" ], { "error": str( err ) } )
        return { "error": str( err ) }
    write_answer( want[ "answer" ], { "sha256": digest } )
    return { "sha256": digest }
