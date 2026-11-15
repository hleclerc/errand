"""On the machine that runs QEMU ( ADR 0008 ):

    python -m errand.vm use '<request>'     a command's hold on a machine ( `using` )
    python -m errand.vm keep <live dir>     its keeper, a process of the agent there ( `keeping` )
    python -m errand.vm stop                every machine kept on this one, stopped
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import layers as L
from .facts import Facts
from .machine import Machine, stop_all


def main( argv = None ) -> int:
    argv = list( sys.argv[ 1 : ] if argv is None else argv )
    if argv[ : 1 ] == [ "keep" ] and len( argv ) == 2:
        live = Path( argv[ 1 ] )
        config = json.loads( ( live / "config.json" ).read_text() )
        host = L.host_of( config[ "host" ] )
        m = Machine( host, Facts.of( host ), config[ "name" ] )
        m.at( config[ "image" ] )
        return m.keep( config )
    if argv[ : 1 ] == [ "use" ] and len( argv ) == 2:
        from .using import use
        return use( json.loads( argv[ 1 ] ) )
    if argv[ : 1 ] == [ "stop" ]:
        return stop_all()
    print( "usage: python -m errand.vm use REQUEST | keep LIVE_DIR | stop", file = sys.stderr )
    return 2


if __name__ == "__main__":
    sys.exit( main() )
