"""What a machine has for the services a page asks for ( ADR 0027 §4-5 ): the agent's `services` operation, `look`.

It reads files and runs nothing: the declarations, the envs and the packages that describe services ( `packages` ),
the tools ( where the description says to look, the PATH, errand's cache, the paths the user gave ) and their versions
read from files ( `Info.plist`, a directory's name, dpkg's status, snap's `meta/snap.yaml`, what errand fetched, what a
person `probe`d ), the cards, and whether the store is seen. From that, a state per service and the LINES that would
make it ready here, each with what it does; a person types them.

    look( { "services": { name: { "version", "protocol", "package": { name, version }, "described": entry,
                                  "described_by": "here" | "store" } },
            "machine": "lmo", "paths": { tool: [ "/opt/b/blender", "/opt/b/blender@5.2.2" ] },
            "store": { "paths": [ ... ], "copy": "views/<vid>", "check": [ [ rel, size ] ... ], "size": bytes, "files": n } }
          ) -> { "platform", "cards", "store": { "seen": "original" | "shared" | "copy" | "none", "path" },
                 "services": { name: { state, why, found: [ lines ], lines: [ { comment, command, described_by,
                                                                                unknown_source } ] } } }

`described`: the store's copy of the description ( or the one of a package where the page is served ). It is used to
look and to PROPOSE; to run, only a package of this machine counts ( §4 ).
"""
from __future__ import annotations

import glob
import json
import os
import platform
import plistlib
import re
import shlex
import shutil
import sys
from fnmatch import fnmatch
from pathlib import Path


# ── versions, from files ─────────────────────────────────────────────────────

def _vt( v: str ) -> tuple:
    return tuple( int( x ) for x in re.findall( r"\d+", str( v ) )[ :4 ] )


def meets( v: str | None, least: str | None ) -> bool | None:
    """whether version `v` is `least` or later ( None: unknown )"""
    if not least:
        return True
    if not v:
        return None
    return _vt( v ) >= _vt( least )


def _probes_file( ) -> Path:
    from . import bootstrap
    return bootstrap.local_cache() / "serve" / "probes.json"


def probes( ) -> dict:
    try:
        return json.loads( _probes_file().read_text() )
    except ( OSError, ValueError ):
        return { }


def _stamp( path: str ) -> str | None:
    try:
        st = os.stat( path )
        return f"{st.st_size}:{int( st.st_mtime )}"
    except OSError:
        return None


def remember_probe( path: str, version: str, how: str ):
    got = probes()
    got[ str( Path( path ).resolve() ) ] = { "stamp": _stamp( path ), "version": version, "how": how }
    f = _probes_file()
    f.parent.mkdir( parents = True, exist_ok = True )
    tmp = f.with_name( f".{f.name}.{os.getpid()}.tmp" )
    tmp.write_text( json.dumps( got, indent = 1 ) )
    os.replace( tmp, f )


def _dpkg( package: str, path: Path ) -> str | None:
    if not str( path ).startswith( "/usr/" ):
        return None
    try:
        text = Path( "/var/lib/dpkg/status" ).read_text( errors = "replace" )
    except OSError:
        return None
    for block in text.split( "\n\n" ):
        if re.search( rf"^Package: {re.escape( package )}$", block, re.M ) and "Status: install ok installed" in block:
            m = re.search( r"^Version: (?:\d+:)?([^\s-]+)", block, re.M )
            if m:
                return m.group( 1 )
    return None


def _snap( name: str, path: Path ) -> str | None:
    if not str( path ).startswith( "/snap/" ):
        return None
    try:
        for line in Path( f"/snap/{name}/current/meta/snap.yaml" ).read_text().splitlines():
            if line.startswith( "version:" ):
                return line.split( ":", 1 )[ 1 ].strip().strip( "'\"" )
    except OSError:
        pass
    return None


def version_of( path: str, rules: list, fetched: dict | None = None ) -> tuple:
    """( version, how ) of the program at `path`, from files only; ( None, None ) when no rule applies"""
    p = Path( path )
    try:
        real = p.resolve()
    except OSError:
        real = p
    known = probes().get( str( real ) )
    if known and known.get( "stamp" ) == _stamp( str( real ) ):
        return known[ "version" ], known.get( "how" ) or "probed"
    from . import bootstrap
    tools = bootstrap.local_cache() / "tools"
    if tools in real.parents:                                   # ( fetched by errand: its version was said then )
        sha = real.relative_to( tools ).parts[ 0 ]
        v = ( fetched or { } ).get( sha )
        if v:
            return v, "fetched by errand"
    for r in rules or [ ]:
        if not isinstance( r, dict ):
            continue
        try:
            if "plist" in r:
                f = ( real.parent / r[ "plist" ] ).resolve()
                if f.is_file():
                    with open( f, "rb" ) as fh:
                        v = plistlib.load( fh ).get( r.get( "key", "CFBundleShortVersionString" ) )
                    if v:
                        return str( v ), f"Info.plist ( {f} )"
            elif "dirname" in r:
                for part in reversed( real.parts ):
                    m = re.search( r[ "dirname" ], part )
                    if m:
                        return m.group( 1 ), f"its directory's name ( {part} )"
            elif "dpkg" in r:
                v = _dpkg( r[ "dpkg" ], p )
                if v:
                    return v, f"dpkg ( package {r[ 'dpkg' ]} )"
            elif "snap" in r:
                v = _snap( r[ "snap" ], real )
                if v:
                    return v, f"snap ( {r[ 'snap' ]} )"
        except ( OSError, ValueError, plistlib.InvalidFileException, re.error ):
            continue
    return None, None


# ── tools ────────────────────────────────────────────────────────────────────

def _looks( desc: dict ) -> list:
    from .install import here
    look = desc.get( "look" ) or [ ]
    if isinstance( look, dict ):
        out = [ ]
        for pat, names in look.items():
            if fnmatch( here(), pat ):
                out += list( names )
        return out
    return list( look )


def _fetched_versions( desc: dict ) -> dict:
    return { str( f.get( "sha256", "" ) ).lower(): f.get( "version" ) for f in ( desc.get( "fetch" ) or { } ).values()
             if isinstance( f, dict ) and f.get( "sha256" ) }


def candidates( name: str, desc: dict, given = ( ) ) -> list:
    """( path, said ) of every place `name` may be here: given by the user, the description's `look`, the PATH, errand's
    cache ( its fetches of this tool )"""
    from .install import tool_dir
    out, seen = [ ], set()

    def add( path, said, version = None ):
        try:
            r = str( Path( path ).resolve() )
        except OSError:
            return
        if r in seen or not os.path.isfile( r ) or not os.access( r, os.X_OK ):
            return
        seen.add( r )
        out.append( ( path, said, version ) )

    for g in given:
        path, _, v = str( g ).partition( "@" )
        add( os.path.expanduser( path ), "given", v or None )
    for c in _looks( desc ):
        if os.path.isabs( c ):
            add( c, "the usual place" )
        elif shutil.which( c ):
            add( shutil.which( c ), "on the PATH" )
    for f in ( desc.get( "fetch" ) or { } ).values():
        if isinstance( f, dict ) and f.get( "sha256" ) and f.get( "run" ):
            add( str( tool_dir( f[ "sha256" ] ) / f[ "run" ] ), "in errand's cache" )
    return out


def tools_here( tools: dict, given: dict | None = None ) -> dict:
    """{ tool: { path, version, how, ok, candidates, fetch } }: the first candidate that meets `min` ( a given one first )"""
    from .install import here
    out = { }
    for name, desc in ( tools or { } ).items():
        desc = desc or { }
        fetched = _fetched_versions( desc )
        cands = [ ]
        for path, said, v in candidates( name, desc, ( given or { } ).get( name ) or ( ) ):
            how = "given" if v else None
            if not v:
                v, how = version_of( path, desc.get( "version_from" ), fetched )
            cands.append( { "path": path, "said": said, "version": v, "how": how, "ok": meets( v, desc.get( "min" ) ) } )
        best = next( ( c for c in cands if c[ "ok" ] ), None )
        out[ name ] = { "path": best[ "path" ] if best else None, "version": best[ "version" ] if best else None,
                        "ok": bool( best ), "min": desc.get( "min" ), "candidates": cands,
                        "fetch": ( desc.get( "fetch" ) or { } ).get( here() ) }
    return out


# ── the machine ──────────────────────────────────────────────────────────────

def cards( ) -> list:
    from .agents import resources
    try:
        got = [ { "name": g.get( "name" ), "kind": "cuda", "total": g.get( "total" ), "used": g.get( "used" ) }
                for g in resources.gpus() ]
    except Exception:
        got = [ ]
    if not got and sys.platform == "darwin" and platform.machine() == "arm64":
        got = [ { "name": "Apple GPU", "kind": "metal" } ]
    return got


def store_seen( store: dict | None ) -> dict:
    """where this machine sees the store: one of its `paths` holding the files `check` names at their sizes, or errand's
    copy, or none"""
    from . import bootstrap
    if not store:
        return { "seen": "none" }

    def same( root: Path ) -> bool:
        if not root.is_dir():
            return False
        for rel, size in store.get( "check" ) or [ ]:
            try:
                if ( root / rel ).stat().st_size != int( size ):
                    return False
            except OSError:
                return False
        return True

    for i, p in enumerate( store.get( "paths" ) or [ ] ):
        root = Path( os.path.expanduser( p ) )
        if same( root ):
            return { "seen": "original" if i == 0 and store.get( "original" ) else "shared", "path": str( root ) }
    if store.get( "copy" ):
        root = bootstrap.local_cache() / store[ "copy" ]
        if same( root ):
            return { "seen": "copy", "path": str( root ) }
    return { "seen": "none", "size": store.get( "size" ), "files": store.get( "files" ) }


# ── a service, here ──────────────────────────────────────────────────────────

def _short( path: str ) -> str:
    home = str( Path.home() )
    return "~" + path[ len( home ): ] if path.startswith( home + os.sep ) else path


def _cmd( words: list ) -> str:
    """the words as a person types them: quoted for a shell, `{port}` as it is, paths in full ( a `~` typed here would be
    this machine's home, not the one over there )"""
    return " ".join( w if re.fullmatch( r"\{port(:[a-z][a-z0-9_]*)?\}", w ) else shlex.quote( w ) for w in words )


def _human( n ) -> str:
    n = float( n or 0 )
    for unit in ( "B", "kB", "MB", "GB", "TB" ):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ( "B", "kB" ) else f"{n:.1f} {unit}"
        n /= 1000


def service( name: str, want: dict, machine: str, given: dict, found_cards: list ) -> dict:
    """one service the page asks for, on this machine"""
    from . import install as I, packages as P, serve as S
    from .install import here
    v = want.get( "version" )
    key = f"{name}#{v}" if v else name
    out = { "key": key, "found": [ ], "lines": [ ] }
    decls = S.declared( cwd = str( S.home() ) )
    mine = { k: s for k, s in decls.items() if P.split( k )[ 0 ] == name }
    # ( the declarations of this name, and their states )
    for k, s in sorted( mine.items() ):
        st = S.state( k ).get( "state", "stopped" )
        bad = I.check( k, { "provider": getattr( s, "provider", None ) } ) if P.split( k )[ 1 ] else None
        out[ "found" ].append( f"{k} declared ( {getattr( s, 'source', 'services.py' )} )"
                               + ( f" — {bad}" if bad else "" ) + ( f", {st}" if st not in ( "stopped", "failed" ) else "" ) )
    provs = [ p for p in P.providers() if name in p.services() ]
    exact = [ p for p in provs if p.provided().get( name ) == v ] if v else provs
    for p in provs:
        got = p.provided().get( name )
        where = f"{p.package} {p.dist_version} in {p.env}" + ( f" ( editable: {p.editable} )" if p.editable else "" )
        out[ "found" ].append( f"{where} — provides {name}#{got}" + ( ", the version this store asks for" if got == v else
                                                                     f", the store asks #{v}" if v else "" ) )
    pkg = want.get( "package" ) or { }
    if not provs and pkg.get( "name" ):
        old = P.installs_of( pkg[ "name" ] )
        for env, ver, editable in old:
            out[ "found" ].append( f"{pkg[ 'name' ]} {ver} in {env}" + ( f" ( editable: {editable} )" if editable else "" )
                                   + " describes no service: no entry point `errand.services` in its install"
                                   + ( f" ( installed before it was added? pip install -e {editable} again in that env )"
                                       if editable else "" ) )
        if not old:
            out[ "found" ].append( f"no env here has {pkg[ 'name' ]}" + ( f" ( the store was written by {pkg[ 'name' ]} "
                                                                          f"{pkg.get( 'version' )} )" if pkg.get( "version" ) else "" ) )
    # ( the description: of a package here that provides it, else the one sent )
    if exact:
        entry, described_by = exact[ 0 ].services()[ name ], "this machine"
    else:
        entry, described_by = want.get( "described" ) or { }, want.get( "described_by" ) or "store"
    needs = entry.get( "needs" ) or { }
    # ( needs that nothing typed can meet )
    plats = needs.get( "platforms" )
    if plats and not any( fnmatch( here(), p ) for p in plats ):
        out.update( state = "unavailable", why = f"{here()}: not one of {', '.join( plats )}" )
        return out
    if needs.get( "gpus" ):
        kind = needs.get( "gpu_kind", "any" )
        fit = [ c for c in found_cards if kind in ( "any", None ) or c.get( "kind" ) == kind ]
        if len( fit ) < int( needs[ "gpus" ] ):
            out.update( state = "unavailable", why = "no card" if not fit else f"{len( fit )} card(s), {needs[ 'gpus' ]} needed" )
            return out
    # ( the tools )
    tools = tools_here( entry.get( "tools" ) or { }, given )
    fetches = { }
    for t, f in tools.items():
        if f[ "candidates" ]:
            for c in f[ "candidates" ]:
                ver = c[ "version" ] or "version unknown"
                tail = "" if c[ "ok" ] else ( f" — this service needs {f[ 'min' ]} or later" if c[ "ok" ] is False else
                                               " — its version cannot be read from its files" )
                out[ "found" ].append( f"{_short( c[ 'path' ] )} · {ver}" + ( f" ( {c[ 'how' ]} )" if c[ "how" ] else "" ) + tail )
        else:
            out[ "found" ].append( f"no {t} on the PATH, nor in its usual places, nor in errand's cache" )
        if not f[ "ok" ]:
            if f[ "fetch" ]:
                fetches[ t ] = f[ "fetch" ]
            elif not any( c[ "ok" ] is None for c in f[ "candidates" ] ):
                out.update( state = "unavailable", why = f"no {t} for {here()}" )
                return out
    # ( the state )
    if v in [ P.split( k )[ 1 ] for k in mine ]:
        st = S.state( key ).get( "state", "stopped" )
        bad = I.check( key, { "provider": getattr( mine[ key ], "provider", None ) } )
        if bad:
            out.update( state = "wrong version", why = bad )
        elif getattr( mine[ key ], "provider", None ) is None and getattr( mine[ key ], "source", "" ) == "installed":
            out.update( state = "unverified", why = "declared by hand: no package here provides this version" )
            return out
        else:
            out.update( state = "running" if st not in ( "stopped", "failed", "gave up" ) else "ready", why = "" )
            return out
    # ( the lines )
    lines = [ ]
    unknown_version = [ c for f in tools.values() if not f[ "ok" ] for c in f[ "candidates" ] if c[ "ok" ] is None ]
    for c in unknown_version:
        lines.append( { "comment": f"runs {_short( c[ 'path' ] )} --version once, on {machine}, to read its version",
                        "command": f"errand serve probe --on {machine} -- {_cmd( [ c[ 'path' ], '--version' ] )}",
                        "described_by": described_by, "unknown_source": False } )
    blocked = [ t for t, f in tools.items() if not f[ "ok" ] and t not in fetches ]
    if blocked:                                          # ( only a version that cannot be read stands in the way )
        out.update( state = "unknown", lines = lines,
                    why = f"the version of {', '.join( blocked )} cannot be read from its files: probe it, or give it "
                          f"( a path with @VERSION )" )
        return out
    tool_paths = { t: f[ "path" ] for t, f in tools.items() if f[ "ok" ] }
    for t, f in fetches.items():
        url, sha = f.get( "url" ), str( f.get( "sha256", "" ) ).lower()
        if not url or not sha:
            continue
        size = f" ( {_human( f[ 'size' ] )}," if f.get( "size" ) else " ("
        lines.append( { "comment": f"{t} {f.get( 'version' ) or ''} from {url.split( '/' )[ 2 ]} into errand's cache on {machine}"
                                   f"{size} checked against its sha256 {sha[ :4 ]}…{sha[ -4: ]} ); nothing in it is run",
                        "command": f"errand serve fetch --on {machine} {url}#sha256={sha}",
                        "described_by": described_by, "unknown_source": not I.trusted( url ) } )
        tool_paths[ t ] = I.tool_path( sha, f.get( "run" ) )
    gpus = needs.get( "gpus" )
    flags = ( f" --gpus {gpus}" if gpus else "" ) + ( f" --idle {entry[ 'idle' ]}" if entry.get( "idle" ) else "" )
    what = ( f", GPU {gpus}" if gpus else "" ) + ( f", stopped after {entry[ 'idle' ]} unused" if entry.get( "idle" ) else "" )
    if exact:
        p = exact[ 0 ]
        try:
            words = P.compose( p, name, tool_paths )
        except P.Unresolved as err:
            out.update( state = "unavailable", why = str( err ) )
            return out
        lines.append( { "comment": f"the service {key}, as {p.package} {p.dist_version} in {Path( p.env ).name} describes it{what}",
                        "command": f"errand serve install --on {machine}{flags} {key} -- {_cmd( words )}",
                        "described_by": described_by, "unknown_source": False } )
    else:
        pk = ( entry.get( "package" ) or want.get( "package_block" ) or { } )
        pip = pk.get( "pip" ) or pkg.get( "name" )
        if not pip:
            out.update( state = "unavailable", why = f"no package here provides {key}, and its description says no way to get one" )
            return out
        spec = f"{pip}=={pkg[ 'version' ]}" if pkg.get( "version" ) else pip
        index = pk.get( "index" ) or I.PYPI
        lines.append( { "comment": f"{spec} from {index.split( '/' )[ 2 ]} into a new env of errand's on {machine} "
                                   f"( {I.env_dir( spec ).name} ), which touches no other env",
                        "command": f"errand serve fetch --on {machine} pip:{spec}" + ( f" --index {index}" if index != I.PYPI else "" ),
                        "described_by": described_by, "unknown_source": not I.trusted( index ) } )
        lines.append( { "comment": f"the service {key}, composed from that package once it is there: shown, then asked{what}",
                        "command": f"errand serve install --on {machine}{flags} {key}",
                        "described_by": described_by, "unknown_source": False } )
    out.update( state = "installable", why = "", lines = lines )
    return out


def look( req: dict ) -> dict:
    """the agent's `services` operation, `look`: read-only"""
    from .install import here
    machine = str( req.get( "machine" ) or "here" )
    given = { str( k ): list( v ) for k, v in ( req.get( "paths" ) or { } ).items() }
    found_cards = cards()
    out = { "platform": here(), "cards": found_cards, "store": store_seen( req.get( "store" ) ), "services": { } }
    for name, want in ( req.get( "services" ) or { } ).items():
        try:
            out[ "services" ][ name ] = service( str( name ), want or { }, machine, given, found_cards )
        except Exception as err:
            out[ "services" ][ name ] = { "state": "unknown", "why": f"{type( err ).__name__}: {err}", "found": [ ], "lines": [ ] }
    return out
