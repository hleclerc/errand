"""The packages of a machine that describe services ( ADR 0027 §1-2 ): found, read and composed, nothing imported or run.

A package describes its services in a file it ships, `errand-services.json`, beside their code; an entry point names the
module that holds it:

    [project.entry-points."errand.services"]
    sdot = "sdot.viz.services"

    { "format": 1, "package": { "name": "sdot", "pip": "sdot", "index": "https://pypi.org/simple" },
      "services": { "blender": { "protocol": 1, "text": "...", "version_of": [ "blender.py", "../store.py" ],
                                 "run": [ "{tool:blender}", "-b", "-P", "{file:blender.py}", "--", "--port", "{port}" ],
                                 "needs": { "gpus": 1 }, "idle": "10m", "tools": { "blender": { ... } } } } }

    envs( )                   the Python environments of this machine ( conda / micromamba roots, errand's own, this one )
    providers( )              every package of them that describes services: a `Provider` each
    version( name, entry, base )  `name#version` of a service: 8 hex digits of a sha256 over its `version_of` files
    compose( provider, name, tools )  the words of its command on this machine ( `{port}` left for the keeper )

Everything here reads files: `entry_points.txt` and `direct_url.json` in an env's `*.dist-info`, the editable finders'
mapping, the package's own files. A package is never imported, a program never run.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

FILE   = "errand-services.json"
GROUP  = "errand.services"
WORDS  = re.compile( r"\{(python|file:[^{}]+|tool:[A-Za-z0-9_.-]+|port(?::[a-z][a-z0-9_]*)?)\}" )


# ── a service's version ──────────────────────────────────────────────────────

def version( name: str, entry: dict, base ) -> str:
    """`name#version`'s version: the producer computes the same, when it writes a store ( ADR 0027 §2 )"""
    h = hashlib.sha256( f"errand-service/1 {name} protocol {entry.get( 'protocol', 1 )}\n".encode() )
    for rel in entry.get( "version_of" ) or [ ]:
        data = ( Path( base ) / rel ).read_bytes()
        h.update( f"{rel} {len( data )}\n".encode() )
        h.update( data )
    return h.hexdigest()[ :8 ]


def split( key: str ) -> tuple:
    """`blender#3fa29c1e` -> ( "blender", "3fa29c1e" ); a bare name -> ( name, None )"""
    name, _, v = str( key ).partition( "#" )
    return name, ( v or None )


# ── the envs of this machine ─────────────────────────────────────────────────

def _roots( ) -> list:
    home = Path.home()
    out = [ ]
    for var in ( "MAMBA_ROOT_PREFIX", "CONDA_ROOT", "CONDA_PREFIX" ):
        if os.environ.get( var ):
            out.append( Path( os.environ[ var ] ) )
    for name in ( ".mamba", "micromamba", ".micromamba", "miniforge3", "miniforge", "mambaforge", "miniconda3",
                  "anaconda3", ".conda" ):
        out.append( home / name )
    return out


def envs( extra = ( ) ) -> list:
    """the prefixes of the Python environments of this machine: every `envs/*` of the conda / micromamba roots, the roots
    themselves, errand's service envs ( `errand serve fetch pip:` ), this interpreter's, and `extra`"""
    from . import bootstrap
    found, seen = [ ], set()

    def add( p ):
        try:
            p = Path( p ).resolve()
        except OSError:
            return
        if p in seen or not p.is_dir():
            return
        if _site( p ):
            seen.add( p )
            found.append( p )

    for root in _roots():
        add( root )
        for e in sorted( glob.glob( str( root / "envs" / "*" ) ) ):
            add( e )
    for e in sorted( glob.glob( str( bootstrap.local_cache() / "svc-envs" / "*" ) ) ):
        add( e )
    add( sys.prefix )
    for e in extra:
        add( e )
    return found


def _site( prefix: Path ) -> list:
    """the site-packages of an env"""
    got = glob.glob( str( prefix / "lib" / "python3*" / "site-packages" ) ) + glob.glob( str( prefix / "Lib" / "site-packages" ) )
    return [ Path( g ) for g in sorted( got ) if Path( g ).is_dir() ]


def python_of( prefix: Path ) -> str | None:
    for c in ( prefix / "bin" / "python3", prefix / "bin" / "python", prefix / "python.exe", prefix / "Scripts" / "python.exe" ):
        if c.is_file():
            return str( c )
    return None


# ── the packages that describe services ──────────────────────────────────────

@dataclass
class Provider:
    env: str                    # the env's prefix
    python: str | None          # its interpreter
    package: str                # the distribution's name ( `sdot` )
    dist_version: str           # its version ( `2026.11.3` )
    module: str                 # the entry point's module ( `sdot.viz.services` )
    dir: str                    # where that module is on this machine
    editable: str | None        # the checkout, for an editable install
    data: dict = field( default_factory = dict )      # its `errand-services.json`

    @property
    def file( self ) -> str:
        return str( Path( self.dir ) / FILE )

    def services( self ) -> dict:
        return ( self.data.get( "services" ) or { } ) if isinstance( self.data, dict ) else { }

    def provided( self ) -> dict:
        """{ name: version } for every service it describes ( a missing file: left out )"""
        out = { }
        for name, entry in self.services().items():
            try:
                out[ name ] = version( name, entry, self.dir )
            except OSError:
                continue
        return out

    def brief( self ) -> dict:
        return { "env": self.env, "python": self.python, "package": self.package, "version": self.dist_version,
                 "dir": self.dir, "editable": self.editable, "provides": self.provided() }


def _entry_points( text: str ) -> dict:
    out, group = { }, None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith( ( "#", ";" ) ):
            continue
        if line.startswith( "[" ) and line.endswith( "]" ):
            group = line[ 1:-1 ].strip()
            continue
        if group == GROUP and "=" in line:
            k, _, v = line.partition( "=" )
            out[ k.strip() ] = v.split( ":" )[ 0 ].strip()
    return out


def _meta( dist: Path ) -> tuple:
    name, ver = dist.name.rsplit( "-", 1 )[ 0 ], ""
    try:
        for line in ( dist / "METADATA" ).read_text( errors = "replace" ).splitlines():
            if line.startswith( "Name:" ):
                name = line[ 5: ].strip()
            elif line.startswith( "Version:" ):
                ver = line[ 8: ].strip()
            elif not line.strip():
                break
    except OSError:
        pass
    return name, ver


def _editable( dist: Path ) -> str | None:
    try:
        d = json.loads( ( dist / "direct_url.json" ).read_text() )
    except ( OSError, ValueError ):
        return None
    if not ( d.get( "dir_info" ) or { } ).get( "editable" ):
        return None
    url = str( d.get( "url" ) or "" )
    if not url.startswith( "file://" ):
        return None
    from urllib.parse import unquote, urlparse
    return unquote( urlparse( url ).path )


def _mapped( site: Path, top: str ) -> list:
    """where an editable install puts the top-level package `top`: the setuptools / scikit-build finders' MAPPING, and
    the plain paths of `.pth` files"""
    out = [ ]
    for f in glob.glob( str( site / "__editable__*finder.py" ) ) + glob.glob( str( site / "_*editable*.py" ) ):
        try:
            text = Path( f ).read_text( errors = "replace" )
        except OSError:
            continue
        m = re.search( r"MAPPING\s*(?::[^=]*)?=\s*(\{[^}]*\})", text )
        if m:
            for k, v in re.findall( r"""['"]([^'"]+)['"]\s*:\s*['"]([^'"]+)['"]""", m.group( 1 ) ):
                if k == top:
                    out.append( Path( v ) )
    for f in glob.glob( str( site / "*.pth" ) ):
        try:
            lines = Path( f ).read_text( errors = "replace" ).splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if line and not line.startswith( ( "#", "import " ) ) and os.path.isabs( line ):
                out.append( Path( line ) / top )
    return out


def _module_dir( site: Path, module: str, editable: str | None ) -> Path | None:
    parts = module.split( "." )
    cands = [ site.joinpath( *parts ) ]
    for top in _mapped( site, parts[ 0 ] ):
        cands.append( top.joinpath( *parts[ 1: ] ) )
    if editable:
        cands += [ Path( editable ) / "src" / Path( *parts ), Path( editable ) / Path( *parts ) ]
    for c in cands:
        if ( c / FILE ).is_file():
            return c
    return None


def in_env( prefix ) -> list:
    """the providers of one env"""
    prefix = Path( prefix )
    out = [ ]
    for site in _site( prefix ):
        for dist in sorted( site.glob( "*.dist-info" ) ):
            try:
                eps = _entry_points( ( dist / "entry_points.txt" ).read_text( errors = "replace" ) )
            except OSError:
                continue
            if not eps:
                continue
            name, ver = _meta( dist )
            editable = _editable( dist )
            for module in eps.values():
                d = _module_dir( site, module, editable )
                if d is None:
                    continue
                try:
                    data = json.loads( ( d / FILE ).read_text() )
                except ( OSError, ValueError ):
                    continue
                out.append( Provider( str( prefix ), python_of( prefix ), name, ver, module, str( d ), editable, data ) )
    return out


def installs_of( package: str, extra = ( ) ) -> list:
    """( env, version, editable ) of every install of the distribution `package` here, services described or not ( one
    installed before its entry point was added describes none: said by the diagnosis )"""
    want = re.sub( r"[-_.]+", "-", package ).lower()
    out = [ ]
    for e in envs( extra ):
        for site in _site( e ):
            for dist in site.glob( "*.dist-info" ):
                name, ver = _meta( dist )
                if re.sub( r"[-_.]+", "-", name ).lower() == want:
                    out.append( ( str( e ), ver, _editable( dist ) ) )
    return out


def providers( extra = ( ) ) -> list:
    """every package of this machine's envs that describes services"""
    out = [ ]
    for e in envs( extra ):
        out += in_env( e )
    return out


def providing( key: str, extra = ( ) ) -> list:
    """the providers of exactly `name#version`"""
    name, v = split( key )
    return [ p for p in providers( extra ) if name in p.services() and ( v is None or p.provided().get( name ) == v ) ]


def by_file( path: str ) -> Provider | None:
    """the provider whose `errand-services.json` is `path` ( a declaration's `provider` ), read again"""
    p = Path( path )
    for prov in providers():
        if Path( prov.file ) == p:
            return prov
    try:                                              # ( an env errand no longer lists: the file alone )
        return Provider( "", None, "", "", "", str( p.parent ), None, json.loads( p.read_text() ) )
    except ( OSError, ValueError ):
        return None


# ── composing a command ──────────────────────────────────────────────────────

class Unresolved( LookupError ):
    pass


def compose( provider: Provider, name: str, tools: dict | None = None ) -> list:
    """the words of service `name` on this machine: `{python}` the env's, `{file:REL}` the package's file there,
    `{tool:NAME}` `tools[ NAME ]`; `{port}` and `{port:NAME}` stay for the keeper"""
    entry = provider.services().get( name )
    if entry is None:
        raise Unresolved( f"{provider.package or provider.dir} describes no service {name!r}" )
    run = entry.get( "run" )
    if not isinstance( run, list ) or not run or not all( isinstance( w, str ) for w in run ):
        raise Unresolved( f"{name}: `run` is a list of words" )
    tools = tools or { }
    out = [ ]
    for w in run:
        def one( m ):
            what = m.group( 1 )
            if what == "python":
                if not provider.python:
                    raise Unresolved( f"{name}: no Python in {provider.env}" )
                return provider.python
            if what.startswith( "file:" ):
                rel = what[ 5: ]
                f = ( Path( provider.dir ) / rel ).resolve()
                if not f.exists():
                    raise Unresolved( f"{name}: {rel} is not in {provider.dir}" )
                return str( f )
            if what.startswith( "tool:" ):
                t = what[ 5: ]
                if not tools.get( t ):
                    raise Unresolved( f"{name}: no {t} found" )
                return str( tools[ t ] )
            return m.group( 0 )                          # ( a port: the keeper's )
        out.append( WORDS.sub( one, w ) )
    return out


def needs_of( entry: dict ) -> dict:
    """what a description asks of a declaration: gpus, gpu_ram, ram, idle"""
    n = dict( entry.get( "needs" ) or { } )
    out = { k: n[ k ] for k in ( "gpus", "gpu_ram", "ram", "cpus" ) if n.get( k ) is not None }
    if entry.get( "idle" ):
        out[ "idle" ] = entry[ "idle" ]
    return out
