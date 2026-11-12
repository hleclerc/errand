"""errand, started from a copy of its sources that travelled to another machine.

`bootstrap.ship` puts the package under `~/.cache/errand/src/<key>/errand/` over
there, and the command that reaches it is `python <that>/_boot.py run ...`
rather than `python -m errand run ...`: nothing has to be installed on the other
side, and the errand that answers is exactly the one that asked.

What errand starts in turn -- a `-j` child, the ranks of an MPI run, the run
after a preparation -- is `sys.executable -m errand`, so the copy goes on
PYTHONPATH too, in front of whatever was there.

Run as a file, never imported: `__name__` guards it, and it imports nothing
but the standard library before the package itself.
"""
if __name__ == "__main__":
    import os
    import sys

    here = os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) )
    # The script's own directory is sys.path[ 0 ]: inside the package, where
    # `errand/queue.py` would shadow the standard `queue`.
    sys.path[ 0 ] = here
    os.environ[ "PYTHONPATH" ] = os.pathsep.join( p for p in ( here, os.environ.get( "PYTHONPATH" ) ) if p )
    if sys.argv[ 1 : 2 ] == [ "-m" ]:
        # `_boot.py -m errand.agents connect …`: a module of the copy, as `python -m` would run it
        import runpy
        module = sys.argv[ 2 ]
        sys.argv = [ module, *sys.argv[ 3 : ] ]
        runpy.run_module( module, run_name = "__main__", alter_sys = True )
        sys.exit( 0 )
    from errand.cli import main
    try:
        sys.exit( main() )
    except KeyboardInterrupt:
        print( "\n  interrupted", file = sys.stderr )
        sys.exit( 130 )
