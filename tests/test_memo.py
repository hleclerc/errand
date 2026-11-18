"""`@errand.memo` ( ADR 0015 ): a result kept by its inputs, in the project's cache zone."""
import dataclasses
import enum
import importlib.util
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from errand import skip, test
from errand import memos as M


def project( ) -> Path:
    root = Path( tempfile.mkdtemp() ).resolve()
    ( root / "errand-project.py" ).write_text( "" )
    return root


def counted( root, **kw ):
    calls = [ ]

    @M.memo( root = root, **kw )
    def slow( a, b = 2, verbose = False ):
        calls.append( ( a, b ) )
        return { "sum": a + b, "a": a }
    return slow, calls


if test( "computed once, then read back; another argument, a default made explicit, another version" ):
    root = project()
    slow, calls = counted( root, ignore = [ "verbose" ] )
    assert slow( 1 ) == { "sum": 3, "a": 1 } and slow( 1 ) == { "sum": 3, "a": 1 } and len( calls ) == 1
    assert slow( 1, 2 ) == slow( a = 1 ) and len( calls ) == 1, "a default is part of the key, given or not"
    slow( 1, verbose = True )
    assert len( calls ) == 1, "an ignored argument"
    slow( 2 )
    assert len( calls ) == 2
    d = slow.memo_dir( 1 )
    assert d.parent.parent == root / "errand-cache/memo" and ( d / "value.pkl" ).is_file()
    meta = json.loads( ( d / "meta.json" ).read_text() )
    assert meta[ "version" ] == 0 and meta[ "args" ][ "a" ] == "1" and meta[ "host" ], meta
    slow2, calls2 = counted( root, version = 2, ignore = [ "verbose" ] )
    slow2( 1 )
    assert len( calls2 ) == 1 and slow2.memo_dir( 1 ) != d, "another version, another key"
    assert not list( ( root / "errand-cache/memo" / M.WORK / "parts" ).iterdir() ), "no part left"


if test( "the key holds what arguments hold: containers, dataclasses, enums, files; never repr" ):
    @dataclasses.dataclass
    class P:
        n: int
        tol: float = 1e-6

    class E( enum.Enum ):
        A = 1

    def f( x ):
        pass

    k = lambda x: M.key_of( f, 0, ( x, ), { } )
    assert k( { "a": 1, "b": [ 1, 2 ] } ) == k( { "b": [ 1, 2 ], "a": 1 } ), "a dict's order is no part of it"
    assert k( ( 1, 2 ) ) != k( [ 1, 2 ] ) and k( 1 ) != k( 1.0 ) and k( 1 ) != k( "1" ) and k( True ) != k( 1 )
    assert k( P( 3 ) ) == k( P( 3 ) ) and k( P( 3 ) ) != k( P( 4 ) ) and k( E.A ) == k( E.A )
    assert k( { 1, 2, 3 } ) == k( { 3, 2, 1 } )
    d = Path( tempfile.mkdtemp() )
    ( d / "a.bin" ).write_bytes( b"x" )
    ( d / "b" ).mkdir()
    ( d / "b/a.bin" ).write_bytes( b"x" )
    assert k( d / "a.bin" ) == k( d / "b/a.bin" ), "a file by its contents, not where it is"
    ( d / "b/a.bin" ).write_bytes( b"y" )
    assert k( d / "a.bin" ) != k( d / "b/a.bin" )

    class Opaque:
        pass
    for bad in ( Opaque(), d, lambda: 0 ):
        try:
            k( bad )
            assert False, bad
        except M.MemoError as err:
            assert "argument 'x'" in str( err ), err

    class Keyed:
        def __init__( self, v ):
            self.v = v

        def __errand_key__( self ):
            return self.v
    assert k( Keyed( 1 ) ) == k( Keyed( 1 ) ) != k( Keyed( 2 ) )
    assert M.key_of( f, 0, ( Opaque(), ), { }, key = lambda x: "fixed" ) == M.key_of( f, 0, ( 1, ), { }, key = lambda x: "fixed" )


if test( "arrays: by dtype, shape and bytes, kept as a .npz" ):
    if importlib.util.find_spec( "numpy" ) is None:
        skip( "no numpy here" )
    import numpy as np
    root = project()
    calls = [ ]

    @M.memo( root = root )
    def grid( x ):
        calls.append( 1 )
        return x * 2, x + 1

    a = np.arange( 6, dtype = np.float32 ).reshape( 2, 3 )
    got = grid( a )
    again = grid( a.copy() )
    assert len( calls ) == 1 and isinstance( again, tuple ) and ( again[ 0 ] == got[ 0 ] ).all()
    assert ( grid.memo_dir( a ) / "value.npz" ).is_file()
    grid( a.reshape( 3, 2 ) )
    grid( a.astype( np.float64 ) )
    assert len( calls ) == 3, "another shape, another dtype: other keys"


if test( "save and load replace the format; a value that does not load is computed again" ):
    root = project()
    calls = [ ]

    @M.memo( root = root, save = lambda v, d: ( d / "v.txt" ).write_text( v ), load = lambda d: ( d / "v.txt" ).read_text() )
    def text( n ):
        calls.append( n )
        return "x" * n

    assert text( 3 ) == "xxx" and text( 3 ) == "xxx" and len( calls ) == 1
    slow, calls = counted( root )
    slow( 5 )
    ( slow.memo_dir( 5 ) / "value.pkl" ).write_bytes( b"not a pickle" )
    assert slow( 5 ) == { "sum": 7, "a": 5 } and len( calls ) == 2
    assert slow( 5 ) == { "sum": 7, "a": 5 } and len( calls ) == 2, "written again, read since"


if test( "modes: off computes and keeps nothing, refresh computes and replaces" ):
    import errand
    root = project()
    slow, calls = counted( root )
    try:
        errand.memo.mode = "off"
        slow( 1 )
        slow( 1 )
        assert len( calls ) == 2 and not ( root / "errand-cache/memo" ).exists()
        errand.memo.mode = None
        slow( 1 )
        slow( 1 )
        assert len( calls ) == 3
        errand.memo.mode = "refresh"
        slow( 1 )
        assert len( calls ) == 4
        os.environ[ M.ENV ] = "off"
        errand.memo.mode = None
        slow( 1 )
        assert len( calls ) == 5
    finally:
        errand.memo.mode = None
        os.environ.pop( M.ENV, None )


if test( "two runs that want one result: computed once, the other waits and reads it" ):
    root = project()
    calls = [ ]

    @M.memo( root = root )
    def once( n ):
        calls.append( n )
        time.sleep( 0.3 )
        return n * n

    got = [ ]
    ts = [ threading.Thread( target = lambda: got.append( once( 7 ) ) ) for _ in range( 4 ) ]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert got == [ 49 ] * 4 and calls == [ 7 ], ( got, calls )


if test( "outside a project: computed, nothing kept, said once" ):
    d = Path( tempfile.mkdtemp() )
    old = os.getcwd()
    calls = [ ]
    try:
        os.chdir( d )

        @M.memo
        def free( n ):
            calls.append( n )
            return n

        assert free( 1 ) == 1 and free( 1 ) == 1 and len( calls ) == 2 and not ( d / "errand-cache" ).exists()
    finally:
        os.chdir( old )


if test( "errand.memo, as a project's code writes it" ):
    import errand
    root = project()
    old = os.getcwd()
    try:
        os.chdir( root )
        calls = [ ]

        @errand.memo( version = 1 )
        def f( n ):
            calls.append( n )
            return n + 1

        assert f( 1 ) == 2 and f( 1 ) == 2 and calls == [ 1 ]
        assert f.memo_dir( 1 ).is_relative_to( root / "errand-cache/memo" )
    finally:
        os.chdir( old )


if test( "a function is named by its file in the project: the same key run by errand or by hand" ):
    import subprocess
    import sys
    root = project()
    ( root / "exp" ).mkdir()
    ( root / "exp/recon.py" ).write_text( "import errand\n"
                                          "@errand.memo\n"
                                          "def solve( n ):\n"
                                          "    print( 'computing' )\n"
                                          "    return n\n"
                                          "if __name__ == '__main__':\n"
                                          "    print( solve( 3 ), solve.memo_dir( 3 ) )\n" )
    env = { **os.environ, "PYTHONPATH": str( Path( M.__file__ ).parents[ 1 ] ) }
    by_hand = subprocess.run( [ sys.executable, "exp/recon.py" ], cwd = root, env = env, capture_output = True, text = True )
    assert "computing" in by_hand.stdout and "exp.recon.solve" in by_hand.stdout, by_hand
    imported = subprocess.run( [ sys.executable, "-c", "import importlib.util as u, sys; s = u.spec_from_file_location( "
                                 "'_errand_scan.exp.recon', 'exp/recon.py' ); m = u.module_from_spec( s ); s.loader.exec_module( m ); "
                                 "print( m.solve( 3 ) )" ], cwd = root, env = env, capture_output = True, text = True )
    assert imported.stdout.strip() == "3" and "computing" not in imported.stdout, "found, not computed again"
