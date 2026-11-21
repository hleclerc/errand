"""The agent's `services` operation ( ADR 0027 ): what a machine has for a page's services, and what a person typed for it.

    { "op": "services", "do": "look", ... }      read only: `diagnose.look` ( the page's diagnosis, `errand serve look` )
    { "op": "services", "do": "probe", "argv" }  `errand serve probe -- PROG --version`: run once, the version kept
    { "op": "services", "do": "fetch", "source", "index", "into", "source_ok" }      `errand serve fetch`
    { "op": "services", "do": "install", "key", "words", "needs" }                    `errand serve install -- WORDS`
    { "op": "services", "do": "copy_into", "vid" } -> { "root" }  where a view's copy goes here ( `.errand/copy` )

Only `look` and `copy_into` are reached from a page ( through the errand that serves it ): they run nothing. The others
are reached from a person's command line only ( `cli/serve.py` ), through their own agent.
"""
from __future__ import annotations

import re
import subprocess

PROBE_TIMEOUT = 5.0
READ_ONLY = ( "look", "copy_into", "compose" )


def answer( req: dict ) -> dict:
    do = req.get( "do" )
    try:
        if do == "look":
            from ..diagnose import look
            return { "ok": True, **look( req ) }
        if do == "copy_into":
            from .. import bootstrap
            vid = re.sub( r"[^A-Za-z0-9_-]", "", str( req.get( "vid" ) or "" ) )
            if not vid:
                return { "error": "no view" }
            root = bootstrap.local_cache() / "views" / vid
            root.mkdir( parents = True, exist_ok = True )
            return { "ok": True, "root": str( root ), "rel": f"views/{vid}" }
        if do == "compose":
            from .. import install as I
            words, needs, text = I.composed( str( req[ "key" ] ) )
            return { "ok": True, "words": words, "needs": needs, "text": text }
        if do == "probe":
            return probe( [ str( a ) for a in req.get( "argv" ) or [ ] ] )
        if do == "fetch":
            return fetch( req )
        if do == "install":
            from .. import install as I
            words = req.get( "words" )
            decl = I.install( str( req[ "key" ] ), [ str( w ) for w in words ] if words else None,
                              needs = req.get( "needs" ) or None, ask = ( lambda text: True ) if req.get( "yes" ) else None )
            return { "ok": True, "declaration": decl, "file": str( I.installed_file() ) }
    except Exception as err:
        return { "error": f"{type( err ).__name__}: {err}" }
    return { "error": f"unknown services request {do!r}" }


def probe( argv: list ) -> dict:
    """the program run once with the arguments the person typed; the first version-looking word of its output kept"""
    from ..diagnose import remember_probe
    if not argv:
        return { "error": "nothing to run" }
    try:
        got = subprocess.run( argv, capture_output = True, text = True, timeout = PROBE_TIMEOUT, stdin = subprocess.DEVNULL )
    except ( OSError, subprocess.TimeoutExpired ) as err:
        return { "error": f"{argv[ 0 ]}: {err}" }
    out = ( got.stdout or "" ) + "\n" + ( got.stderr or "" )
    m = re.search( r"\b(\d+\.\d+(?:\.\d+)?)\b", out )
    if not m:
        return { "error": f"{argv[ 0 ]}: no version in its output", "output": out.strip()[ :400 ] }
    remember_probe( argv[ 0 ], m.group( 1 ), f"probed ( {' '.join( argv )} )" )
    return { "ok": True, "version": m.group( 1 ), "output": out.strip().splitlines()[ 0 ][ :200 ] if out.strip() else "" }


def fetch( req: dict ) -> dict:
    from .. import install as I
    source = str( req.get( "source" ) or "" )
    ok = [ str( s ) for s in req.get( "source_ok" ) or [ ] ]
    if source.startswith( "pip:" ):
        env = I.fetch_pip( source[ 4: ], index = req.get( "index" ), into = req.get( "into" ), source_ok = ok )
        return { "ok": True, "env": env }
    m = I.URL_SHA.match( source )
    if not m:
        return { "error": f"{source!r}: URL#sha256=<64 hex digits>, or pip:PACKAGE==VERSION" }
    where = I.fetch_url( m.group( "url" ), m.group( "sha" ), source_ok = ok )
    return { "ok": True, "path": where }
