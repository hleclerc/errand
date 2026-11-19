"""The runs as a tree ( ADR 0023 ): directories, file, entry, parameter sets as a table, runs; sorted, folded; and
removed by hand, for good, only run directories a machine noted, never what runs."""
import contextlib
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

from errand import test


class M:
    def __init__( self, name, here = False ):
        self.name, self.here, self.table, self.history = name, here, { "procs": [ ] }, { "runs": [ ] }

    def now( self ):
        return time.time()

    def ask( self, q, timeout = 60.0 ):
        from errand.agents import look
        return look.answer( q )


def rec( leaf, started, status = "PASS", params = None, what = None, env = "jax", **more ):
    r = { "leaf": leaf, "started": started, "status": status, "env": env, "duration": 1.5,
          "what": what or ( "exp.py::foam" + "".join( f" {k}={v}" for k, v in ( params or { } ).items() ) ), **more }
    if params is not None:
        r[ "params" ] = params
    return r


@contextlib.contextmanager
def scratch( ):
    d = Path( tempfile.mkdtemp( dir = "/tmp" ) ).resolve()
    was = os.environ.get( "ERRAND_CACHE_DIR" )
    os.environ[ "ERRAND_CACHE_DIR" ] = str( d / "cache" )
    try:
        yield d
    finally:
        os.environ.pop( "ERRAND_CACHE_DIR", None ) if was is None else os.environ.__setitem__( "ERRAND_CACHE_DIR", was )
        shutil.rmtree( d, ignore_errors = True )


if test( "the tree: directories merged, the file, the entry, its parameter sets as an aligned table that sorts" ):
    from errand.tui import runtree as T
    m = M( "lmo" )
    base = "/p/errand-outputs/runs/otrec/experiments/exp.py/foam"
    runs = [ ( m, rec( f"{base}/r1", 100, params = { "n": 10000, "row": 500 } ), False ),
             ( m, rec( f"{base}/r2", 200, params = { "n": 2000, "row": 500 }, results = { "loss": 0.25 } ), False ),
             ( m, rec( f"{base}/r3", 300, status = None, what = "exp.py::foam n=10000 row=500" ), True ),     # an older agent: from `what`
             ( m, rec( "/p/errand-outputs/runs/sdot-ffi/tests/test_a.py/case_a/r4", 50, what = "test_a.py::case a, with a comma" ), False ) ]
    root = T.build( runs )
    top = T.rows( root )
    assert [ ( r.label, r.open ) for r in top ][ : 2 ] == [ ( "otrec/experiments/exp.py", True ), ( "foam", True ) ], [ ( r.label, r.open ) for r in top ]
    assert all( "," not in r.data[ 1 ][ "tree" ] for r in top if r.kind in ( "tnode", "tset", "thead" ) ), "ids a list can carry"
    head = next( r for r in top if r.kind == "thead" )
    sets = [ r for r in top if r.kind == "tset" or r.tabled ]
    assert head.label.split()[ : 3 ] == [ "n", "row", "→loss" ] and len( sets ) == 2, ( head.label, [ s.label for s in sets ] )
    assert sets[ 1 ].kind == "run" and sets[ 1 ].open is None and sets[ 1 ].data[ 1 ][ "leaf" ].endswith( "/r2" ), \
        "a set of one run: its line is the run, nothing to unfold"
    assert all( s.label.index( "500" ) == head.label.index( "row" ) for s in sets ), "aligned under its column"
    assert sets[ 0 ].label.split()[ 0 ] == "10000" and "running" in sets[ 0 ].label and sets[ 0 ].open, "the busy set first, open"
    assert "2" in sets[ 0 ].label.split(), "two runs in the set n=10000"
    folded = T.rows( root, folded = { f"t:{top[ 0 ].data[ 1 ][ 'tree' ]}" } )
    assert folded[ 0 ].open is False and len( [ r for r in folded if r.depth == 0 ] ) == len( folded ), "folded by hand"
    entry = top[ 1 ].data[ 1 ][ "tree" ]
    srt = T.rows( root, opened = { f"s:{entry}=n" } )
    assert [ r.label.split()[ 0 ] for r in srt if r.kind == "tset" or r.tabled ] == [ "2000", "10000" ] and "n ▲" in next( r for r in srt if r.kind == "thead" ).label
    srt = T.rows( root, opened = { f"s:{entry}=-n" } )
    assert [ r.label.split()[ 0 ] for r in srt if r.kind == "tset" or r.tabled ] == [ "10000", "2000" ]
    sd = next( r for r in top if r.label.startswith( "sdot-ffi" ) )
    assert sd.label == "sdot-ffi/tests/test_a.py" and sd.open is False, "not busy: folded"
    opened = T.rows( root, opened = { f"t:{sd.data[ 1 ][ 'tree' ]}" } )
    assert any( r.label == "case a, with a comma" for r in opened ), [ r.label for r in opened ]

if test( "keep only the latest: per parameter set and env, the latest and the last PASS stay; never what runs" ):
    from errand.tui import runtree as T
    m = M( "lmo" )
    b = "/p/errand-outputs/runs/exp.py/foam"
    runs = [ ( m, rec( f"{b}/a", 1, params = { "n": 1 } ), False ), ( m, rec( f"{b}/b", 2, params = { "n": 1 } ), False ),
             ( m, rec( f"{b}/c", 3, status = "FAIL", params = { "n": 1 } ), False ),
             ( m, rec( f"{b}/d", 4, params = { "n": 1 }, env = "torch" ), False ),
             ( m, rec( f"{b}/e", 0, params = { "n": 2 } ), False ), ( m, rec( f"{b}/f", 5, status = None, params = { "n": 2 } ), True ) ]
    gone = sorted( Path( r[ "leaf" ] ).name for _, r, _ in T.keep_latest( runs ) )
    assert gone == [ "a" ], gone                  # ( c the latest, b the last PASS, d another env; n=2: f runs, e its last PASS )

if test( "the agent removes only run directories it noted, never one that runs; dry: their sizes; `latest` goes with it" ):
    from errand.agents import look, seen
    with scratch() as d:
        entry = d / "proj" / "errand-outputs" / "runs" / "exp.py" / "foam"
        leaves = [ entry / n for n in ( "r1", "r2" ) ]
        for l in leaves:
            l.mkdir( parents = True )
            ( l / "result.yaml" ).write_text( "status: PASS\n" )
            ( l / "big.bin" ).write_bytes( b"x" * 1000 )
            seen.note( l, d / "proj", "exp.py::foam", "jax" )
        ( entry / "latest" ).symlink_to( leaves[ 1 ] )
        stranger = d / "proj" / "data"
        stranger.mkdir()
        got = look.answer( { "op": "runs_remove", "leaves": [ str( l ) for l in leaves ] + [ str( stranger ) ], "dry": True } )
        assert set( got[ "sizes" ] ) == { str( l ) for l in leaves } and all( v >= 1000 for v in got[ "sizes" ].values() ), got
        got = look.answer( { "op": "runs_remove", "leaves": [ str( leaves[ 1 ] ), str( stranger ) ] } )
        assert got[ "removed" ] == [ str( leaves[ 1 ] ) ] and got[ "kept" ] == [ [ str( stranger ), "not a run of this machine" ] ], got
        assert not leaves[ 1 ].exists() and leaves[ 0 ].exists() and stranger.exists() and not ( entry / "latest" ).is_symlink()
        assert [ r[ "leaf" ] for r in seen.runs( 10 )[ "runs" ] ] == [ str( leaves[ 0 ] ) ], "its link gone with it"

def made( root: Path, rel: str, host = None, **said ) -> Path:
    """a run of this machine's record ( ADR 0025 ): its directory under the root's `runs/`, its `result.yaml`"""
    import socket
    from errand import yamlish
    leaf = root / "errand-outputs" / "runs" / rel
    leaf.mkdir( parents = True )
    ( leaf / "out.bin" ).write_bytes( b"x" * 1500 )
    parts = rel.split( "/" )
    name = parts[ -1 ]
    rec = { "name": parts[ -2 ], "file": parts[ -3 ] if len( parts ) > 2 else parts[ 0 ], "env": "jax", "host": host or socket.gethostname(),
            "status": "PASS", "duration_s": 1.5, "stamp": name[ : 19 ], **said }
    ( leaf / "result.yaml" ).write_text( yamlish.dump( rec ) if hasattr( yamlish, "dump" ) else "" )
    return leaf


def record( d: Path, *more ):
    """the record of `d / "here"` ( and `more` roots ): only theirs -- the other machine's runs, noted in this process's
    `seen` too, are not this machine's"""
    from errand.agents import registry as G
    G.roots = lambda: [ str( d / "here" ), *( str( m ) for m in more ) ]
    G._shared.clear()
    return G.shared()


if test( "the record: every run started here, with exact counts, the projects as sub-lists; a run there too" ):
    from errand.tui import rows as R
    with scratch() as d:
        for i in range( 3 ):
            made( d / "here", f"exp.py/foam/2026-11-19_10h0{i}m00-jax", params = { "n": i } )
        made( d / "here" / "sub", "b.sh/2026-11-19_11h00m00-jax", name = "sh", file = "b.sh" )
        made( d / "here", "exp.py/foam/2026-11-19_12h00m00-jax@far", host = "farhost", params = { "n": 0 } )
        reg = record( d, d / "here" / "sub" )
        assert len( reg.runs ) == 5, list( reg.runs )
        far, mac = M( "far" ), M( "mac", here = True )
        far._host = "farhost"
        rows = R.build( [ mac, far ], tab = "runs", unfold = True )
        top = [ ( r.label, r.detail.split( "  " )[ 0 ] ) for r in rows if r.kind == "tnode" and r.depth == 0 ]
        assert sorted( top ) == [ ( "exp.py", "4 runs" ), ( "sub/b.sh", "1 run" ) ], top    # no common directory, no `./`
        on_far = [ r for r in rows if r.kind == "run" and r.data[ 0 ] == "far" ]
        assert len( on_far ) == 1 and on_far[ 0 ].data[ 1 ][ "rel" ].endswith( "@far" ), [ ( r.kind, r.label, r.data[ 0 ] ) for r in rows ]

if test( "remove: here, and there by its path under runs/ through that machine's agent; nothing asked elsewhere" ):
    from errand.agents import seen
    from errand.tui import removal as RM
    from errand.tui import rows as R
    with scratch() as d:
        rel = "exp.py/foam/2026-11-19_10h00m00-jax@far"
        here = made( d / "here", rel, host = "farhost" )
        there = d / "there" / "errand-outputs" / "runs" / rel                # ( "far"'s agent: this process, its `seen` )
        there.mkdir( parents = True )
        ( there / "big.bin" ).write_bytes( b"x" * 2000 )
        seen.note( there, d / "there", "exp.py::foam", "jax" )
        mine = made( d / "here", "exp.py/foam/2026-11-19_11h00m00-jax" )
        record( d )
        far, mac = M( "far" ), M( "mac", here = True )
        far._host = "farhost"
        rows = R.build( [ mac, far ], tab = "runs", unfold = True )
        node = next( r for r in rows if r.kind == "tnode" and r.label.startswith( "exp.py" ) )
        p = RM.plan( node, [ mac, far ], "all" )
        assert p.title == "remove 2 runs of exp.py?" and p.lines[ : 2 ] == [ "here: 2 runs, …", "far: 1 run there too, …" ], ( p.title, p.lines )
        RM.measure( p )
        assert p.lines[ 0 ].startswith( "here: 2 runs, " ) and p.lines[ 1 ].startswith( "far: 1 run there too, " ), p.lines
        said = RM.send( p )
        assert said.startswith( "2 runs removed here, 1 on other machines" ), said
        assert not here.exists() and not there.exists() and not mine.exists()
        assert not [ r for r in R.build( [ mac, far ], tab = "runs", unfold = True ) if r.kind == "run" ], "gone from the list at once"

if test( "remove in two times: the window asks nobody, the room after; the rows chosen together; greyed until gone" ):
    from errand.tui import removal as RM
    from errand.tui import rows as R
    from errand.tui import runtree as T
    with scratch() as d:
        leaves = [ made( d / "here", f"exp.py/foam/2026-11-19_10h0{i}m00-jax", params = { "n": i } ) for i in range( 3 ) ]
        record( d )
        asked = [ ]

        class Far( M ):
            def ask( self, q, timeout = 60.0 ):
                asked.append( q )
                return super().ask( q )
        mac = Far( "mac", here = True )
        rows = R.build( [ mac ], tab = "runs", unfold = True )
        sets = [ r for r in rows if r.tabled ]
        assert len( sets ) == 3, [ ( r.kind, r.label ) for r in rows ]
        p = RM.plan( sets[ : 2 ], [ mac ], "all" )
        assert not asked, "the window: nobody asked"
        assert p.title == "remove 2 runs of 2 rows?" and p.lines[ 0 ] == "here: 2 runs, …", ( p.title, p.lines )
        shown = p.lines
        RM.measure( p )
        assert shown is p.lines and p.lines[ 0 ].startswith( "here: 2 runs, " ) and p.lines[ 0 ].endswith( "kB" ), p.lines
        RM.mark( p )
        try:
            greyed = [ r for r in R.build( [ mac ], tab = "runs", unfold = True ) if r.mark == "going" ]
            assert len( greyed ) == 2 and all( r.tabled for r in greyed ), [ ( r.kind, r.mark, r.label ) for r in greyed ]
        finally:
            T.GOING.clear()
        said = RM.send( p )
        assert said.startswith( "2 runs removed here" ) and not T.GOING and sum( l.exists() for l in leaves ) == 1, said

if test( "errand web: the window of a removal at once, its sizes asked after, the yes answered before it is done" ):
    from errand.tui import runtree as T
    from errand.web.server import Web, _key
    from errand.tui import rows as R
    with scratch() as d:
        leaf = made( d / "here", "exp.py/foam/2026-11-19_10h00m00-jax" )
        record( d )
        mac = M( "mac", here = True )
        mac.wake = threading.Event()
        w = Web.start( d / "cache", port = 0, machines_of = lambda: [ mac ] )
        try:
            row = next( r for r in R.build( [ mac ], tab = "runs", unfold = True ) if r.kind == "run" )
            got = w.act( { "op": "runs_remove", "how": "all", "keys": [ _key( row ) ] } )[ "confirm" ]
            assert got[ "plan" ] and got[ "measure" ] == "runs_measure" and "remove 1 run" in got[ "title" ], got
            lines = w.act( { "op": "runs_measure", "plan": got[ "plan" ] } )[ "lines" ]
            assert lines[ 0 ].startswith( "here: 1 run, " ) and "…" not in lines[ 0 ], lines
            n0 = w._said_n
            said = w.act( { "op": "runs_remove", "how": "all", "keys": [ _key( row ) ], "plan": got[ "plan" ], "sure": True } )
            assert said[ "said" ].startswith( "removing 1 run" ), said
            deadline = time.time() + 10
            while w._told[ 0 ] <= n0 and time.time() < deadline:
                time.sleep( 0.05 )
            assert "1 run removed here" in w._told[ 1 ] and not leaf.exists() and not T.GOING, ( w._told, leaf.exists() )
        finally:
            w.stop()

if test( "a file run as a whole ( sh x.sh ) is the file, in its directories; an entry is under its file" ):
    from errand.tui import runtree as T
    o = "/p/errand-outputs/runs/"
    assert T.rel_file( { "leaf": o + "proj/scripts/h.sh/2026-11-19_x", "what": "h.sh::sh", "file": "scripts/h.sh" } ) == "proj/scripts/h.sh"
    assert T.rel_file( { "leaf": o + "proj/scripts/h.sh/2026-11-19_x", "what": "h.sh::sh" } ) == "proj/scripts/h.sh"
    assert T.rel_file( { "leaf": o + "h.sh/2026-11-19_x", "what": "h.sh::sh" } ) == "h.sh"
    assert T.rel_file( { "leaf": o + "otrec/experiments/exp_2d_real.py/foam/2026_x", "what": "exp_2d_real.py::foam n=1" } ) == "otrec/experiments/exp_2d_real.py"
    assert T.rel_file( { "leaf": o + "a/b.py/c/2026_x", "what": "" } ) == "a/b.py"

if test( "the check: a run another machine holds that is not here is listed, marked; brought back or removed there" ):
    from errand.agents import seen
    from errand.tui import removal as RM
    from errand.tui import rows as R
    with scratch() as d:
        made( d / "here", "exp.py/foam/2026-11-19_09h00m00-jax" )               # ( its file's directory is here )
        rel = "exp.py/foam/2026-11-19_10h00m00-jax@far"
        there = d / "there" / "errand-outputs" / "runs" / rel
        there.mkdir( parents = True )
        ( there / "result.yaml" ).write_text( "status: PASS\nname: foam\n" )
        seen.note( there, d / "there", "exp.py::foam", "jax" )
        record( d )
        far, mac = M( "far" ), M( "mac", here = True )
        far._host = "farhost"
        said = R.check( [ mac, far ] )
        assert said == "checked: far: 1 there only", said
        rows = R.build( [ mac, far ], tab = "runs", unfold = True )
        only = [ r for r in rows if r.mark == "there" ]
        assert len( only ) == 1 and "on far only" in only[ 0 ].label and only[ 0 ].data[ 1 ][ "project" ] == str( d / "here" ), \
            [ ( r.kind, r.mark, r.label ) for r in rows ]
        p = RM.plan( only[ 0 ], [ mac, far ], "all" )
        assert p.here == [ ] and p.there == { "far": ( far, [ rel ] ) }, ( p.here, p.there )
        assert RM.send( p ).startswith( "0 runs removed here, 1 on other machines" ) and not there.exists()
        assert not [ r for r in R.build( [ mac, far ], tab = "runs", unfold = True ) if r.mark == "there" ]

if test( "the history, remembered: a new link and a result written later are seen, a leaf gone drops its link" ):
    from errand.agents import seen
    with scratch() as d:
        leaves = [ d / "runs" / f"r{i}" for i in range( 3 ) ]
        for i, l in enumerate( leaves[ : 2 ] ):
            l.mkdir( parents = True )
            seen.note( l, d, f"a.py::c{i}", "jax" )
        got = seen.runs( 10 )[ "runs" ]
        assert len( got ) == 2 and all( r[ "status" ] is None for r in got ), got
        ( leaves[ 0 ] / "result.yaml" ).write_text( "status: PASS\nparams: { n: 3 }\n" )
        leaves[ 2 ].mkdir( parents = True )
        time.sleep( 0.01 )
        seen.note( leaves[ 2 ], d, "a.py::c2", "jax" )
        got = { Path( r[ "leaf" ] ).name: r for r in seen.runs( 10 )[ "runs" ] }
        assert set( got ) == { "r0", "r1", "r2" } and got[ "r0" ][ "status" ] == "PASS" and got[ "r0" ][ "params" ] == { "n": 3 }, got
        shutil.rmtree( leaves[ 1 ] )
        assert { Path( r[ "leaf" ] ).name for r in seen.runs( 10 )[ "runs" ] } == { "r0", "r2" }
        assert len( list( ( d / "cache" / "seen" ).glob( "*.json" ) ) ) == 2, "its link gone"
