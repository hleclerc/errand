"""What `errand serve install` and `errand serve fetch` do on THIS machine ( ADR 0027 §4 ); the agent's `services`
operation calls them for another machine.

    fetch_url( url, sha256 )        a file from a source, checked, kept by its contents ( `<cache>/tools/<sha256>/` ),
                                    unpacked: nothing in it is run. Its program's path is known before ( `tool_path` )
    fetch_pip( spec, index, into )  a package into a dedicated env of errand's ( a uv venv, `<cache>/svc-envs/<name>-<v>` ),
                                    or into an existing env ( `into` )
    install( key, words, needs )    the declaration `name#version` written into `~/.config/errand/services-installed.json`,
                                    with the package that provides it here ( checked before every start ), or `unverified`
    install( key )                  ( no words ) the command composed from the package here that provides `key`

Sources: a fetch from a source outside `errand.sources` ( the user's list, `serve.sources` ) is refused unless the person
repeats it ( `source_ok` ): a store may NAME a source, it never vouches for one.

Nothing here is reached by a page: the page shows the lines, a person types them.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

KEYS = ( "idle", "gpus", "gpu_ram", "ram", "cpus", "exclusive", "grace", "others", "env", "label", "busy", "cwd" )


class Refused( RuntimeError ):
    pass


def here( ) -> str:
    """this platform, as descriptions name it: macos-arm64, linux-x86_64, windows-x86_64 ..."""
    sysname = { "darwin": "macos", "win32": "windows" }.get( sys.platform, sys.platform )
    m = platform.machine().lower()
    return f"{sysname}-{ { 'amd64': 'x86_64', 'aarch64': 'arm64' }.get( m, m ) }"


# ── the declarations ─────────────────────────────────────────────────────────

def installed_file( ) -> Path:
    from .serve import user_file
    return user_file().with_name( "services-installed.json" )


def installed( ) -> dict:
    """the declarations written here: { "name#version": { command, provider, ... } }"""
    try:
        got = json.loads( installed_file().read_text() )
        return got if isinstance( got, dict ) else { }
    except ( OSError, ValueError ):
        return { }


def _write( got: dict ):
    f = installed_file()
    f.parent.mkdir( parents = True, exist_ok = True )
    tmp = f.with_name( f".{f.name}.{os.getpid()}.tmp" )
    tmp.write_text( json.dumps( got, indent = 1 ) + "\n" )
    os.replace( tmp, f )


def services( ) -> dict:
    """the installed declarations as services: { key: Service }, each with `source` ( installed / adhoc ) and `provider`"""
    from .serve import Service
    out = { }
    for key, d in installed().items():
        try:
            svc = Service( d[ "command" ], ports = d.get( "ports" ) or None, **{ k: d[ k ] for k in KEYS if k in d } )
        except ( KeyError, TypeError, ValueError ):
            continue
        svc.source = "adhoc" if d.get( "adhoc" ) else "installed"
        svc.provider = d.get( "provider" )
        out[ key ] = svc
    return out


def declare( key: str, command: list, *, needs: dict | None = None, provider: str | None = None, adhoc = False,
             extra: dict | None = None ) -> dict:
    """`key` declared with `command` ( a list ): written for the keeper and every errand of this machine"""
    from .serve import Service, valid_name
    valid_name( key )
    needs = { k: v for k, v in ( needs or { } ).items() if k in KEYS and v is not None }
    decl = { "command": [ str( w ) for w in command ], **needs, **( extra or { } ) }
    Service( decl[ "command" ], ports = decl.get( "ports" ), **{ k: decl[ k ] for k in KEYS if k in decl } )   # ( refused if wrong )
    if provider:
        decl[ "provider" ] = str( provider )
    if adhoc:
        decl[ "adhoc" ] = True
    decl[ "installed" ] = time.strftime( "%Y-%m-%d %H:%M:%S" )
    got = installed()
    got[ key ] = decl
    _write( got )
    return decl


def forget( key: str ) -> bool:
    got = installed()
    if key not in got:
        return False
    del got[ key ]
    _write( got )
    return True


def check( key: str, decl: dict ) -> str | None:
    """why `key` must not start ( None: it may ): the version its provider gives now differs from the key's"""
    from . import packages as P
    name, v = P.split( key )
    prov = decl.get( "provider" )
    if not v or not prov:
        return None
    p = Path( prov )
    try:
        entry = ( json.loads( p.read_text() ).get( "services" ) or { } )[ name ]
        now = P.version( name, entry, p.parent )
    except ( OSError, ValueError, KeyError ) as err:
        return f"wrong version: its description {prov} cannot be read ( {err} )"
    if now != v:
        return f"wrong version: {prov} now gives {name}#{now}, declared as #{v}"
    return None


def composed( key: str ) -> tuple:
    """( words, needs, text ): `key`'s command as the package here that provides it describes it, with this machine's
    tools; nothing written"""
    from . import packages as P
    from .diagnose import tools_here
    name, _ = P.split( key )
    provs = P.providing( key )
    if not provs:
        raise Refused( f"no package here provides {key}: give the command after --, or fetch the package first" )
    prov = provs[ 0 ]
    entry = prov.services()[ name ]
    found = tools_here( entry.get( "tools" ) or { } )
    missing = [ t for t, f in found.items() if not f[ "ok" ] ]
    if missing:
        raise Refused( f"{key}: no {', '.join( missing )} here that will do ( errand serve look shows what to fetch )" )
    try:
        words = P.compose( prov, name, { t: f[ "path" ] for t, f in found.items() } )
    except P.Unresolved as err:
        raise Refused( str( err ) )
    import shlex
    text = f"service {key}, as {prov.package} {prov.dist_version} in {prov.env} describes it:\n  " + shlex.join( words )
    return words, P.needs_of( entry ), text


def install( key: str, words: list | None = None, *, needs: dict | None = None, ask = None, echo = None ) -> dict:
    """`errand serve install KEY [-- WORDS]` here. With WORDS: a person typed them, declared as they are, with the package
    here that provides KEY ( or `unverified` ). Without: composed from that package, shown, a yes asked."""
    from . import packages as P
    name, v = P.split( key )
    if not v:
        raise Refused( f"{key}: name#version ( the version is the store's, e.g. blender#3fa29c1e )" )
    provs = P.providing( key )
    prov = provs[ 0 ] if provs else None
    if words is None:
        words, more, text = composed( key )
        needs = { **more, **( needs or { } ) }
        if ask is None or not ask( text ):
            raise Refused( "not installed: no yes" )
    decl = declare( key, words, needs = needs, provider = prov.file if prov else None,
                    extra = None if prov else { "unverified": True } )
    if echo and prov is None:
        echo( f"{key}: no package here provides this version: declared as typed, unverified" )
    return decl


# ── sources ──────────────────────────────────────────────────────────────────

def trusted( url: str ) -> bool:
    """whether `url` ( or a `pip:` / conda source ) is in the user's `errand.sources`"""
    from .serve import sources
    u = str( url )
    return any( u == s or u.startswith( s.rstrip( "/" ) + "/" ) for s in sources )


def _source_ok( url: str, source_ok ) -> None:
    if trusted( url ):
        return
    if source_ok and any( url == s or url.startswith( str( s ).rstrip( "/" ) + "/" ) for s in source_ok ):
        return
    raise Refused( f"{url}: not in errand.sources ( an unknown source ): repeat it with --source to fetch it all the same" )


# ── fetch: a file ────────────────────────────────────────────────────────────

URL_SHA = re.compile( r"^(?P<url>[^#]+)#sha256=(?P<sha>[0-9a-fA-F]{64})$" )


def tool_dir( sha256: str ) -> Path:
    from . import bootstrap
    return bootstrap.local_cache() / "tools" / sha256.lower() / "unpacked"


def tool_path( sha256: str, run: str | None ) -> str:
    """where the program of a fetched file is ( known before it is fetched )"""
    return str( tool_dir( sha256 ) / ( run or "" ) )


def fetch_url( url: str, sha256: str, *, run: str | None = None, source_ok = ( ), echo = None ) -> str:
    """the file downloaded ( or already ), checked, unpacked -> its directory ( or the program `run` in it )"""
    _source_ok( url, source_ok )
    sha256 = sha256.lower()
    done = tool_dir( sha256 )
    home = done.parent
    if not done.is_dir():
        home.mkdir( parents = True, exist_ok = True )
        fname = url.rsplit( "/", 1 )[ -1 ].split( "?" )[ 0 ] or "download"
        part = home / ( fname + ".part" )
        if echo:
            echo( f"downloading {url}" )
        h = hashlib.sha256()
        with urllib.request.urlopen( url, timeout = 60 ) as r, open( part, "wb" ) as f:
            for chunk in iter( lambda: r.read( 1 << 20 ), b"" ):
                h.update( chunk )
                f.write( chunk )
        if h.hexdigest() != sha256:
            part.unlink( missing_ok = True )
            raise Refused( f"{url}: sha256 {h.hexdigest()}, expected {sha256}: nothing kept" )
        arch = home / fname
        part.replace( arch )
        tmp = Path( tempfile.mkdtemp( dir = home ) )
        _unpack( arch, tmp )
        tmp.replace( done )
        arch.unlink( missing_ok = True )
        ( home / "source.json" ).write_text( json.dumps( { "url": url, "sha256": sha256, "at": time.strftime( "%Y-%m-%d %H:%M:%S" ) } ) )
    out = done / ( run or "" )
    if run and not out.exists():
        raise Refused( f"{run!r} is not in what was downloaded ( {done} )" )
    if run and out.is_file():
        out.chmod( out.stat().st_mode | 0o111 )
    return str( out )


def _unpack( arch: Path, into: Path ):
    n = arch.name.lower()
    if n.endswith( ".zip" ):
        with zipfile.ZipFile( arch ) as z:
            z.extractall( into )
    elif ".tar" in n or n.endswith( ( ".tgz", ".txz" ) ):
        with tarfile.open( arch ) as t:
            t.extractall( into, filter = "tar" )
    elif n.endswith( ".dmg" ):
        mnt = Path( tempfile.mkdtemp() )
        subprocess.run( [ "hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str( mnt ), str( arch ) ],
                        check = True, capture_output = True )
        try:
            for item in mnt.iterdir():
                if not item.is_symlink():
                    subprocess.run( [ "ditto", str( item ), str( into / item.name ) ], check = True )
        finally:
            subprocess.run( [ "hdiutil", "detach", str( mnt ) ], capture_output = True )
    else:                                                # ( a bare program )
        shutil.copy2( arch, into / arch.name )
        ( into / arch.name ).chmod( 0o755 )


# ── fetch: a package ─────────────────────────────────────────────────────────

PIP_SPEC = re.compile( r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?(==[A-Za-z0-9.+!_-]+)?$" )
PYPI = "https://pypi.org/simple"


def env_dir( spec: str ) -> Path:
    from . import bootstrap
    name = re.sub( r"[^A-Za-z0-9._-]+", "-", spec.replace( "==", "-" ) ).strip( "-" )
    return bootstrap.local_cache() / "svc-envs" / f"errand-svc-{name}"


def _uv( ) -> str | None:
    from . import bootstrap
    for c in ( shutil.which( "uv" ), str( Path.home() / ".local" / "bin" / "uv" ), str( bootstrap.local_cache() / "uv" / "uv" ) ):
        if c and Path( c ).is_file():
            return c
    return None


def fetch_pip( spec: str, *, index: str | None = None, into: str | None = None, source_ok = ( ), echo = None ) -> str:
    """the package `spec` ( `sdot==2026.11.3` ) into errand's dedicated env, or into the env `into` -> the env's prefix"""
    if not PIP_SPEC.match( spec ):
        raise Refused( f"{spec!r}: a package and its version ( sdot==2026.11.3 )" )
    index = index or PYPI
    _source_ok( index, source_ok )
    from . import packages as P
    if into:
        prefix = Path( into ).expanduser()
        if not prefix.is_dir():
            matches = [ e for e in P.envs() if e.name == into ]
            if not matches:
                raise Refused( f"{into}: no such env here" )
            prefix = matches[ 0 ]
        py = P.python_of( prefix )
        if py is None:
            raise Refused( f"{prefix}: no Python in it" )
        argv = [ py, "-m", "pip", "install", "--index-url", index, spec ]
    else:
        prefix = env_dir( spec )
        uv = _uv()
        if not ( prefix / "bin" / "python" ).exists() and not ( prefix / "Scripts" / "python.exe" ).exists():
            prefix.parent.mkdir( parents = True, exist_ok = True )
            mk = [ uv, "venv", "--seed", str( prefix ) ] if uv else [ sys.executable, "-m", "venv", str( prefix ) ]
            if echo:
                echo( " ".join( mk ) )
            subprocess.run( mk, check = True )
        py = P.python_of( prefix )
        argv = ( [ uv, "pip", "install", "--python", py, "--index-url", index, spec ] if uv
                 else [ py, "-m", "pip", "install", "--index-url", index, spec ] )
    if echo:
        echo( " ".join( argv ) )
    got = subprocess.run( argv )
    if got.returncode:
        raise Refused( f"{spec}: the install failed ( exit {got.returncode} )" )
    return str( prefix )
