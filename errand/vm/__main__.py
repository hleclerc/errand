"""`python -m errand.vm keep <dir>`: the keeper, a process of its own, here ( the machine's side
of it is `keeping.Keeping` ). `python -m errand.vm stop` stops every warm machine.
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
        return Machine( host, Facts.of( host ), config[ "name" ] ).keep( config )
    if argv[ : 1 ] == [ "stop" ]:
        return stop_all()
    print( "usage: python -m errand.vm keep LIVE_DIR | stop", file = sys.stderr )
    return 2


if __name__ == "__main__":
    sys.exit( main() )
