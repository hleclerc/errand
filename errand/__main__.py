import sys

from .cli import main

try:
    sys.exit( main() )
except KeyboardInterrupt:
    # Ctrl-C stops the run; what it was in the middle of is not worth a traceback.
    print( "\n  interrupted", file = sys.stderr )
    sys.exit( 130 )
