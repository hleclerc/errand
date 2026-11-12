"""`python -m errand.agents connect|serve <dir> <keep_alive>`: what a layer's stream reaches.

    connect   the bridge: start the agent of <dir> if none answers, then relay stdio to it
    serve     the agent itself, in the foreground ( tests, debugging )
    rsh       rsync's remote shell, through the agent ( `rsh.py` )
"""
from __future__ import annotations

import sys
from pathlib import Path


def main( argv = None ) -> int:
    argv = list( sys.argv[ 1 : ] if argv is None else argv )
    if argv[ : 1 ] == [ "rsh" ] and len( argv ) >= 3:
        from .rsh import main as rsh
        return rsh( argv[ 1 ], argv[ 2 : ] )
    if len( argv ) != 3 or argv[ 0 ] not in ( "connect", "serve" ):
        print( "usage: python -m errand.agents connect|serve DIR KEEP_ALIVE", file = sys.stderr )
        return 2
    verb, root, keep = argv[ 0 ], Path( argv[ 1 ] ).expanduser(), float( argv[ 2 ] )
    if verb == "serve":
        from .agent import Agent
        return Agent( root, keep ).run()
    from .daemon import connect
    return connect( root, keep )


if __name__ == "__main__":
    sys.exit( main() )
