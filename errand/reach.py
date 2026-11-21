"""The machines a page's services may run on, and how to ask one of them ( ADR 0027 §3 ).

    known( )             this machine, then every machine of the ledger ( ADR 0008: where work was sent ), each once
    target( M )          the agent M is reached through ( None: this machine ): a name of the ledger, an environment whose
                         first layer is Ssh, else an ssh destination
    ask( M, req )        the agent's `services` operation on M ( called directly for this machine )
"""
from __future__ import annotations

HERE_WORDS = ( "here", "localhost", "127.0.0.1" )


def here_name( ) -> str:
    from .agents import ledger
    return ledger.here_name()


def is_here( m: str | None ) -> bool:
    import socket
    m = str( m or "here" )
    return m in HERE_WORDS or m == here_name() or m == socket.gethostname() or m == socket.gethostname().split( "." )[ 0 ]


def known( ) -> list:
    """[ { name, here, target, host } ]: this machine first"""
    from .agents import ledger
    out = [ { "name": here_name(), "here": True } ]
    try:
        groups = ledger.groups()
    except Exception:
        groups = [ ]
    for g in groups:
        if any( is_here( n ) for n in [ g[ "name" ], *g.get( "names", [ ] ) ] ):
            continue
        out.append( { "name": g[ "name" ], "here": False, "target": g.get( "target" ), "host": g.get( "host" ),
                      "names": g.get( "names", [ ] ) } )
    return out


def target( m: str ) -> dict | None:
    if is_here( m ):
        return None
    for k in known():
        if m == k[ "name" ] or m in k.get( "names", [ ] ):
            return k[ "target" ]
    from .cli.serve import target_of
    try:
        return target_of( env = m )
    except LookupError:
        pass
    return target_of( host = m )


def ask( m: str, req: dict, timeout: float = 60.0 ) -> dict:
    """the `services` operation on M -> its answer ( { error } when M cannot be reached )"""
    from .agents import servicesop
    t = target( m )
    if t is None:
        return servicesop.answer( req )
    from . import agents
    try:
        from .agents.servicesop import READ_ONLY
        call = agents.open( t, noted = req.get( "do" ) not in READ_ONLY ).open( { "op": "services", **req } )
        try:
            return call.reply( timeout = timeout )
        finally:
            try:
                call.close()
            except Exception:
                pass
    except Exception as err:
        return { "error": f"{m}: {type( err ).__name__}: {err}" }
