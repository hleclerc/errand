"""`errand serve` and `errand hold` ( ADR 0018 ).

    errand serve                                   the services of this machine, and what each does
    errand serve NAME                              a declared service, started if need be: its address
    errand serve NAME --url [PORT]                 only its URL, for a script: OLLAMA_HOST=$( errand serve ollama --url )
    errand serve --port http=8080:8081 --port grpc=:50051 -- CMD {port:http} {port:grpc}
                                                   named ports, ANNOUNCED:SERVER, either side empty for errand to choose
    errand serve [--gpus N ...] -- CMD ARGS...     the same, ad hoc: its name, --name, -n, else the command's first word
    errand serve stop NAME                         stopped: its server, then its claim
    errand serve connect NAME [PORT]               stdin and stdout relayed to it ( `command=` in authorized_keys )
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
        p.add_argument( "words", nargs = "*", help = "NAME, list, stop NAME, connect NAME" )
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
    return f"  {st[ 'name' ]:<16} {colour( now ):<10} {where:<18} {dim( detail )}{waiting}"


def lines( include_ended = False ) -> list:
    """The services of this machine, one line each, for `errand serve` and `errand status`."""
    from .. import serve as S
    return [ _line( st ) for st in ( S.listed() if include_ended else S.running() ) ]


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
