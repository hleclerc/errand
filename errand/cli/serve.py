"""`errand serve` and `errand hold` ( ADR 0018 ).

    errand serve                                   the services of this machine, and what each does
    errand serve NAME                              a declared service, started if need be: its address
    errand serve NAME --url [PORT]                 only its URL, for a script: OLLAMA_HOST=$( errand serve ollama --url )
    errand serve --port http=8080:8081 --port grpc=:50051 -- CMD {port:http} {port:grpc}
                                                   named ports, ANNOUNCED:SERVER, either side empty for errand to choose
    errand serve [--gpus N ...] -- CMD ARGS...     the same, ad hoc: its name, --name, -n, else the command's first word
    errand serve stop NAME                         stopped: its server, then its claim
    errand serve connect NAME [PORT]               stdin and stdout relayed to it ( `command=` in authorized_keys )
    errand serve look [--on M] [--path T=P] DIR    what M has for the services a store asks for, and the lines to type
    errand serve fetch [--on M] URL#sha256=H       a file into errand's cache on M, checked, unpacked; nothing run
    errand serve fetch [--on M] pip:PKG==V [--index URL] [--into ENV]   a package into a new env of errand's ( or ENV )
    errand serve install [--on M] [--gpus N] [--idle T] NAME#VERSION -- WORDS   declared on M as typed ( ADR 0027 )
    errand serve install [--on M] NAME#VERSION     composed from the package on M that provides it, shown, asked
    errand serve probe [--on M] -- PROG --version  run once, to read a version no file says
    errand hold [--gpus N ...] [-n LABEL]          a claim held for whoever holds this stream: `granted <cards>`,
                                                   reads warm / busy, says `evict`, released when stdin closes
"""
from __future__ import annotations

import argparse
import sys
import time

from .style import bad, dim, good as ok


def _parser( prog: str, service: bool ) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser( prog = prog, allow_abbrev = False )
    p.add_argument( "--gpus", default = None, help = "cards it needs" )
    p.add_argument( "--gpu-ram", dest = "gpu_ram", default = None, help = "memory it takes on each card: 10G, 75%%" )
    p.add_argument( "--ram", default = None, help = "memory it needs, e.g. 8G" )
    p.add_argument( "--cpus", default = None, help = "cores it needs" )
    p.add_argument( "-x", "--exclusive", action = "store_true", help = "the machine to itself" )
    p.add_argument( "-n", "--label", default = None, help = "its name in errand queue" )
    if service:
        p.add_argument( "--name", default = None, help = "the service's name ( default: the label, else the command's first word )" )
        p.add_argument( "--idle", default = "10m", help = "how long without connection nor busy before it stops ( 10m )" )
        p.add_argument( "--busy-if", dest = "busy_if", default = None,
                        help = "a shell command, exit 0 when the server is busy; {port} is its port" )
        p.add_argument( "--port", action = "append", default = [ ], metavar = "[NAME=]ANNOUNCED[:SERVER]",
                        help = "a port, repeated for several: http=8080:8081, grpc=:50051 ( empty: errand chooses; "
                               "the announced side is kept from one start to the next ). Without a name: `port`" )
        p.add_argument( "--others", action = "store_true",
                        help = "let other accounts of this machine connect ( closed by default, on Linux )" )
        p.add_argument( "--grace", default = "10s", help = "between asking it to stop and killing it ( 10s )" )
        p.add_argument( "--ensure", action = "store_true", help = "nothing said when it already runs" )
        p.add_argument( "--url", nargs = "?", const = "", default = None, metavar = "PORT",
                        help = "only its URL on stdout, for a script: http://127.0.0.1:PORT ( of port PORT, else the first )" )
        p.add_argument( "-f", "--foreground", action = "store_true", help = "stay until it stops; Ctrl-C stops it" )
        p.add_argument( "--yes", action = "store_true", help = "install: no question ( you have read the command )" )
        p.add_argument( "--on", default = None, metavar = "M",
                        help = "look, fetch, install, probe: the machine ( here by default; a machine of errand status, an env, an ssh host )" )
        p.add_argument( "--source", action = "append", default = [ ], metavar = "URL",
                        help = "fetch: a source outside errand.sources, repeated by you" )
        p.add_argument( "--index", default = None, help = "fetch pip:: the package index ( PyPI by default )" )
        p.add_argument( "--into", default = None, metavar = "ENV", help = "fetch pip:: an existing env instead of a new one" )
        p.add_argument( "--path", action = "append", default = [ ], metavar = "TOOL=PATH[@VERSION]",
                        help = "look: where a tool is, when it is somewhere errand does not look" )
        p.add_argument( "--host", default = None, help = "forward: the machine the service runs on ( an ssh destination )" )
        p.add_argument( "--env", default = None, help = "forward: the environment whose machine the service runs on" )
        p.add_argument( "words", nargs = "*", help = "NAME, list, stop NAME, connect NAME, install DIR NAME, forward NAME" )
    return p


def hold( argv ) -> int:
    from .. import queue
    known = _parser( "errand hold", False ).parse_args( argv )
    needs = { k: getattr( known, k ) for k in ( "gpus", "gpu_ram", "ram", "cpus" ) if getattr( known, k ) is not None }
    return queue.hold( { "needs": needs, "exclusive": known.exclusive, "label": known.label or "errand hold" } )


def _line( st: dict ) -> str:
    now = st.get( "state", "?" )
    colour = ok if now in ( "busy", "in use", "warm", "idle" ) else dim if now in ( "stopped", "gave up" ) else \
        bad if now == "failed" else ( lambda s: s )
    ports = st.get( "ports" ) or { }
    where = " ".join( f"{n}={p[ 'address' ]}" for n, p in ports.items() ) if len( ports ) > 1 else st.get( "address" ) or ""
    detail = st.get( "detail" ) or ""
    waiting = f"  {st[ 'waiting' ]} connection{'s' * ( st[ 'waiting' ] != 1 )} waiting" if st.get( "waiting" ) else ""
    source = f"( {st[ 'source' ]} ) " if st.get( "source" ) and now in ( "ready", "unverified", "wrong version" ) else ""
    colour = bad if now == "wrong version" else colour
    return f"  {st[ 'name' ]:<20} {colour( now ):<10} {where:<18} {dim( source + detail )}{waiting}"


def lines( include_ended = False ) -> list:
    """The services of this machine, one line each, for `errand serve` and `errand status`."""
    from .. import serve as S
    return [ _line( st ) for st in ( S.listed() if include_ended else S.running() ) ]


def target_of( host = None, env = None ) -> dict:
    """the agent a service is reached through: `host` ( an ssh destination ), the machine of environment `env` ( its first
    Ssh layer ), else this machine's host agent"""
    from .. import agents
    if host:
        return agents.upstream.of_host( host )
    if env:
        from .. import config
        from ..layers.gateways import Ssh
        from .project import find_root
        config.load( find_root() )
        found = [ e for e, _ in config.select( names = [ env ] ) ]
        if not found:
            raise LookupError( f"no environment {env!r}" )
        lead = next( ( l for l in found[ 0 ].stack if isinstance( l, Ssh ) ), None )
        if lead is None:
            raise LookupError( f"{env}: not on another machine ( no Ssh layer ): run the service here" )
        return agents.upstream.ssh_target( lead )
    from .. import bootstrap
    return { "kind": "local", "dir": str( bootstrap.local_cache() / "agents" / "forward" ), "keep_alive": 900 }


def _forward( words, known, say ) -> int:
    """`errand serve forward NAME [--host H | --env E] [--port N]`: a port here, every connection to it the service over there"""
    from .. import serve as S
    if len( words ) != 1:
        print( bad( "errand serve forward NAME [--host H | --env E] [--port N]" ) )
        return 2
    try:
        target = target_of( known.host, known.env )
        lst = S.forward( target, words[ 0 ], int( ( known.port or [ "0" ] )[ 0 ] ), echo = say )
    except ( LookupError, OSError, ValueError ) as err:
        print( bad( f"errand serve forward: {err}" ) )
        return 2
    where = known.host or known.env or "this machine"
    print( f"http://127.0.0.1:{lst.getsockname()[ 1 ]}" + dim( f"   -> {words[ 0 ]} on {where} ( Ctrl-C stops the forward )" ), flush = True )
    try:
        while True:
            time.sleep( 3600 )
    except KeyboardInterrupt:
        lst.close()
        return 0


def _on( known, req: dict, timeout = 3600 ) -> dict:
    from .. import reach
    m = known.on or "here"
    got = reach.ask( m, req, timeout = timeout )
    return got


def _look( words, known ) -> int:
    """`errand serve look [--on M] [--path T=P] DIR|VIEW`: M's diagnosis for a store, the lines"""
    from pathlib import Path
    from .. import reach
    from ..web import page_services as PS, static
    if len( words ) != 1:
        print( bad( "errand serve look [--on M] DIR ( a store, or a view's id )" ) )
        return 2
    where = words[ 0 ]
    vid = None
    if not Path( where ).is_dir():
        vid, where = where, static.registered().get( where, where )
    if not Path( where ).is_dir():
        print( bad( f"errand serve look: {words[ 0 ]}: no such directory or view" ) )
        return 2
    m = known.on or reach.here_name()
    req = PS._request( where, vid, m )
    for spec in known.path:
        t, _, p = spec.partition( "=" )
        req[ "paths" ].setdefault( t, [ ] ).append( p )
    a = reach.ask( m, req, timeout = 60 )
    if a.get( "error" ):
        print( bad( f"errand serve look: {a[ 'error' ]}" ) )
        return 1
    st = a.get( "store" ) or { }
    print( f"{m}  {a.get( 'platform' )}  " + dim( ", ".join( c.get( "name" ) or "?" for c in a.get( "cards" ) or [ ] ) or "no card" )
           + dim( f"   the store: {st.get( 'seen' )}" + ( f" {st[ 'path' ]}" if st.get( "path" ) else "" ) ) )
    for name, e in ( a.get( "services" ) or { } ).items():
        print( f"  {e.get( 'key', name ):<24} {e.get( 'state' )}" + dim( f"  {e.get( 'why' ) or ''}" ) )
        for f in e.get( "found" ) or [ ]:
            print( dim( f"      · {f}" ) )
        for line in e.get( "lines" ) or [ ]:
            print( dim( f"      # {line[ 'comment' ]}" ) + ( bad( "  ( unknown source, named by the store )" ) if line.get( "unknown_source" ) else "" ) )
            print( f"      {line[ 'command' ]}" )
    return 0


def _fetch( words, known ) -> int:
    if len( words ) != 1:
        print( bad( "errand serve fetch [--on M] URL#sha256=HASH | pip:PACKAGE==VERSION" ) )
        return 2
    got = _on( known, { "do": "fetch", "source": words[ 0 ], "index": known.index, "into": known.into,
                        "source_ok": known.source } )
    if got.get( "error" ):
        print( bad( f"errand serve fetch: {got[ 'error' ]}" ) )
        return 1
    print( f"{known.on or 'here'}: {got.get( 'path' ) or got.get( 'env' )}" )
    return 0


def _probe( command, known ) -> int:
    if not command:
        print( bad( "errand serve probe [--on M] -- PROGRAM --version" ) )
        return 2
    got = _on( known, { "do": "probe", "argv": command }, timeout = 60 )
    if got.get( "error" ):
        print( bad( f"errand serve probe: {got[ 'error' ]}" ) )
        return 1
    print( f"{command[ 0 ]}: {got[ 'version' ]}" + dim( f"   {got.get( 'output', '' )}" ) )
    return 0


def _install_on( words, command, known, argv ) -> int:
    """`errand serve install [--on M] [needs] NAME#VERSION [-- WORDS]`"""
    if len( words ) != 1 or "#" not in words[ 0 ]:
        print( bad( "errand serve install [--on M] [--gpus N] [--idle T] NAME#VERSION [-- WORDS]" ) )
        return 2
    needs = { k: getattr( known, k ) for k in ( "gpus", "gpu_ram", "ram", "cpus" ) if getattr( known, k ) is not None }
    if "--idle" in argv:
        needs[ "idle" ] = known.idle
    yes = known.yes
    req = { "do": "install", "key": words[ 0 ], "words": command or None, "needs": needs or None, "yes": True }
    if not command:
        prev = _on( known, { **req, "do": "compose" } )
        if prev.get( "error" ):
            print( bad( f"errand serve install: {prev[ 'error' ]}" ) )
            return 1
        print( prev[ "text" ] )
        if not yes:
            try:
                if input( "install it? [y/N] " ).strip().lower() not in ( "y", "yes", "o", "oui" ):
                    print( dim( "not installed" ) )
                    return 1
            except EOFError:
                return 1
    got = _on( known, req )
    if got.get( "error" ):
        print( bad( f"errand serve install: {got[ 'error' ]}" ) )
        return 1
    d = got[ "declaration" ]
    said = "" if d.get( "provider" ) else bad( "   unverified: no package there provides this version" )
    print( f"{words[ 0 ]}: declared on {known.on or 'here'} in {got[ 'file' ]}" + dim( f"   {' '.join( d[ 'command' ] )}" ) + said )
    return 0


def main( argv ) -> int:
    from .. import serve as S
    command = [ ]
    if "--" in argv:
        i = argv.index( "--" )
        argv, command = argv[ : i ], argv[ i + 1 : ]
    known = _parser( "errand serve", True ).parse_args( argv )
    words = known.words
    say = lambda m: print( dim( f"errand serve: {m}" ), file = sys.stderr, flush = True )

    if not command and words[ : 1 ] in ( [ ], [ "list" ] ):
        got = lines( include_ended = True )
        print( "\n".join( got ) if got else dim( "  no service on this machine ( errand serve -- CMD, or errand.services )" ) )
        return 0
    if not command and words[ : 1 ] == [ "forward" ]:
        return _forward( words[ 1 : ], known, say )
    if words[ : 1 ] == [ "install" ]:
        if len( words ) == 3 and not command:                       # ( ADR 0026's form: DIR NAME, a recipe )
            print( bad( "errand serve install DIR NAME is gone ( ADR 0027 ): errand serve look DIR shows the lines" ) )
            return 2
        return _install_on( words[ 1 : ], command, known, argv )
    if words[ : 1 ] == [ "fetch" ] and not command:
        return _fetch( words[ 1 : ], known )
    if words[ : 1 ] == [ "probe" ]:
        return _probe( command, known )
    if words[ : 1 ] == [ "look" ] and not command:
        return _look( words[ 1 : ], known )
    if not command and words[ : 1 ] == [ "stop" ] and len( words ) == 2:
        if S.stop( words[ 1 ] ):
            print( f"{words[ 1 ]}: stopped" )
            return 0
        print( dim( f"{words[ 1 ]}: not running" ) )
        return 0

    svc, name = None, None
    connect = words[ : 1 ] == [ "connect" ]
    port_name = None
    if connect:
        words = words[ 1 : ]
        if len( words ) == 2:
            words, port_name = words[ : 1 ], words[ 1 ]
    if command:
        if words:
            print( bad( f"errand serve: {' '.join( words )}: a name goes in --name, the command after --" ) )
            return 2
        needs = { k: getattr( known, k ) for k in ( "gpus", "gpu_ram", "ram", "cpus" ) if getattr( known, k ) is not None }
        ports = { }
        for spec in known.port:
            n, _, rest = spec.rpartition( "=" )
            if ( n or "port" ) in ports:
                print( bad( f"errand serve: port {n or 'port'} given twice ( --port NAME=... for several )" ) )
                return 2
            ports[ n or "port" ] = rest
        try:
            svc = S.Service( command, label = known.label, busy = known.busy_if, idle = known.idle,
                             ports = ports or None, others = known.others, grace = known.grace,
                             exclusive = known.exclusive, **needs )
        except ValueError as err:
            print( bad( f"errand serve: {err}" ) )
            return 2
        name = known.name or S.name_of( svc )
    else:
        if len( words ) != 1:
            print( bad( "errand serve: NAME, or a command after --" ) )
            return 2
        name = words[ 0 ]
        found = S.declared( warn = say )
        if name not in found:
            names = ", ".join( sorted( found ) ) or f"none ( {S.user_file()} )"
            print( bad( f"errand serve: no service {name!r} is declared" ) + dim( f"   declared: {names}" ) )
            return 2

    if connect:
        return S.connect( name, svc, port = port_name )

    before = S.state( name ).get( "state" )
    try:
        st = S.ensure( name, svc, echo = say )
    except S.Failed as err:
        print( bad( f"errand serve: {name}: {err}" ) )
        return 1
    except KeyboardInterrupt:
        S.stop( name )
        return 130
    if known.url is not None:
        try:
            print( f"http://{S.address( st, known.url )}" )
        except S.Failed as err:
            print( bad( f"errand serve: {name}: {err}" ) )
            return 2
    elif not ( known.ensure and before not in S.ENDED ):
        ports = st.get( "ports" ) or { }
        if len( ports ) > 1:
            print( f"{name}  " + "  ".join( f"{n} http://{p[ 'address' ]}" for n, p in ports.items() )
                   + "  " + dim( f"( {st.get( 'state' )} )" ) )
        else:
            print( f"{name}  http://{st[ 'address' ]}  " + dim( f"( {st.get( 'state' )} )" ) )
    if not known.foreground:
        return 0
    try:
        while S.state( name ).get( "state" ) not in S.ENDED:
            time.sleep( 0.5 )
    except KeyboardInterrupt:
        S.stop( name )
        print( dim( f"{name}: stopped" ) )
        return 130
    st = S.state( name )
    print( dim( f"{name}: {st.get( 'state' )}" + ( f", {st[ 'detail' ]}" if st.get( "detail" ) else "" ) ) )
    return 0
