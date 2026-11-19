"""A run's outputs as one list ( ADR 0017 §5 ): what is made to be looked at first, in the order it appeared -- views,
pages, images, bundles ( a directory with an extension: one row, its state from its manifest ) --, then the console,
then the other files."""
import json
import tempfile
from pathlib import Path

from errand import test


class Here:
    """a machine whose agent reads this file system ( `ls` / `tail` as the agent answers them )"""
    name = "box"

    def now( self ):
        import time
        return time.time()

    def ask( self, q ):
        from errand.agents import look
        if q[ "op" ] == "tail":
            return look.tail( Path( q[ "path" ] ), q.get( "offset" ), q.get( "size" ) )
        raise AssertionError( q )


if test( "views and outputs in one list: the rich ones first, by when they appeared; a store on one line with its state" ):
    import os
    import time
    from errand.agents import look
    from errand.tui.screen import outputs
    leaf = Path( tempfile.mkdtemp() )
    t0 = time.time() - 100

    def put( name, data, age ):
        p = leaf / name
        p.parent.mkdir( parents = True, exist_ok = True )
        p.write_bytes( data if isinstance( data, bytes ) else data.encode() )
        os.utime( p, ( t0 + age, t0 + age ) )

    put( "log.txt", "x", 1 )
    put( "plot.png", b"png", 5 )
    m = { "format": 1, "title": "foam", "complete": False, "curves": [ ], "frames": [ { "v": [ i ], "file": f"frames/{i:06d}.bin" } for i in range( 12 ) ] }
    put( "foam.sviz/manifest.json", json.dumps( m, separators = ( ",", ":" ) ), 3 )
    put( "foam.sviz/index.html", "<html>", 2 )
    put( "foam.sviz/frames/000000.bin", b"f", 2 )
    put( "end.html", "<html>", 9 )
    put( "output.txt", "out", 9 )
    files = [ { **f, "path": f"{leaf}/{f[ 'name' ]}" } for f in look.ls( leaf ) ]
    step = { "views": [ { "t": t0 + 4, "view": "curve.svg", "title": "convergence" },
                        { "t": t0 + 9, "view": f"/through/a/link/{leaf.name}/end.html" } ] }     # ( the leaf by another path )
    rich, plain = outputs( Here(), { "leaf": str( leaf ) }, step, files )
    names = [ r.label for r in rich ]
    assert names == [ "foam.sviz", "convergence", "plot.png", "end.html" ], names
    store = rich[ 0 ]
    assert store.data == ( "box", f"{leaf}/foam.sviz" ) and store.detail.startswith( "12 frames  running" ), store.detail
    assert [ r.label for r in plain ] == [ "log.txt" ], "neither the console ( its own row ) nor what is inside the store"
    m[ "complete" ] = True
    put( "foam.sviz/manifest.json", json.dumps( m, separators = ( ",", ":" ) ), 3 )
    rich, _ = outputs( Here(), { "leaf": str( leaf ) }, step, [ { **f, "path": f"{leaf}/{f[ 'name' ]}" } for f in look.ls( leaf ) ] )
    assert rich[ 0 ].detail.startswith( "12 frames  " ) and "running" not in rich[ 0 ].detail, rich[ 0 ].detail

if test( "the console draws a run's rows as `errand run` does: aligned, the head coloured, no escape shown" ):
    import os
    from errand import rows as RW
    from errand.tui.screen import ROW_HEAD, drawn
    was = os.environ.get( "ERRAND_STEPS" )
    os.environ[ "ERRAND_STEPS" ] = "/x"                       # ( under errand: rows marked )
    try:
        a = RW.text( "adjust", [ "\x1b[2mctr=\x1b[0m1", "pts=1250" ], [ "loss 35.2" ] )
        b = RW.text( "adjust", [ "\x1b[2mctr=\x1b[0m1", "pts=10000" ], [ "loss 0.1" ] )
        c = RW.text( "split", [ "div=4" ] )
    finally:
        os.environ.pop( "ERRAND_STEPS", None ) if was is None else os.environ.__setitem__( "ERRAND_STEPS", was )
    out = drawn( [ a, "plain \x1b]8;;http://x\x07line", b, c ] )
    assert all( "errand-row" not in l and "\x07" not in l for l in out ), out
    assert out[ 1 ] == "plain line"
    seen = [ RW._SGR.sub( "", l ) for l in out ]
    assert seen[ 0 ].index( "loss" ) == seen[ 2 ].index( "loss" ), seen            # ( aligned on the rows after it too )
    assert out[ 0 ].startswith( ROW_HEAD + "adjust" ), out[ 0 ]
