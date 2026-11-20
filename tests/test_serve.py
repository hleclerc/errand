"""`errand serve`: a service kept while used, under the queue ( ADR 0018 )."""
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from errand import test
from errand import queue as Q

ECHO = r'''
import os, socket, threading
port = int( os.environ[ "PORT" ] )
s = socket.socket(); s.setsockopt( socket.SOL_SOCKET, socket.SO_REUSEADDR, 1 ); s.bind( ( "127.0.0.1", port ) ); s.listen()
print( "cards", os.environ.get( "CUDA_VISIBLE_DEVICES" ), "claim", os.environ.get( "ERRAND_CLAIM" ), flush = True )
def one( c ):
    with c:
        for chunk in iter( lambda: c.recv( 4096 ), b"" ):
            c.sendall( chunk.upper() )
while True:
    c, _ = s.accept(); threading.Thread( target = one, args = ( c, ), daemon = True ).start()
'''


@contextlib.contextmanager
def place( ):
    """A cache and a queue of our own; keepers started on their own ( no agent: they inherit this environment )."""
    keys = ( "ERRAND_CACHE_DIR", "XDG_RUNTIME_DIR", "ERRAND_SERVE_NO_AGENT", Q.CLAIM, "PYTHONPATH" )
    before = { k: os.environ.get( k ) for k in keys }
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path( tmp )
        ( tmp / "run" ).mkdir()
        os.environ.update( ERRAND_CACHE_DIR = str( tmp / "cache" ), XDG_RUNTIME_DIR = str( tmp / "run" ),
                           ERRAND_SERVE_NO_AGENT = "1",
                           PYTHONPATH = os.pathsep.join( p for p in sys.path if p ) )
        os.environ.pop( Q.CLAIM, None )
        ( tmp / "echo.py" ).write_text( ECHO )
        from errand import serve as S
        try:
            yield tmp, S
        finally:
            for st in S.running():
                S.stop( st[ "name" ], wait = 15 )
            for k, v in before.items():
                if v is None:
                    os.environ.pop( k, None )
                else:
                    os.environ[ k ] = v


def until( cond, within = 20.0, what = "" ):
    end = time.time() + within
    while not cond():
        assert time.time() < end, f"not within {within} s: {what}"
        time.sleep( 0.1 )


def echo( port, text = b"hello", timeout = 10 ) -> bytes:
    with socket.create_connection( ( "127.0.0.1", port ), timeout = timeout ) as c:
        c.sendall( text )
        return c.recv( 100 )


if test( "a service starts on demand, relays, and stops once idle" ):
    with place() as ( tmp, S ):
        svc = S.Service( [ sys.executable, str( tmp / "echo.py" ) ], idle = "2s" )
        st = S.ensure( "echo", svc )
        assert st[ "state" ] == "idle", st
        assert echo( st[ "port" ] ) == b"HELLO"
        until( lambda: S.state( "echo" )[ "state" ] == "stopped", what = "an idle service stops" )
        assert "idle for" in S.state( "echo" )[ "detail" ]
        # started again, at the same address: the port is kept for the name
        again = S.ensure( "echo", svc )
        assert again[ "port" ] == st[ "port" ]
        assert echo( again[ "port" ] ) == b"HELLO"


if test( "two asking at once start one keeper" ):
    with place() as ( tmp, S ):
        svc = S.Service( [ sys.executable, str( tmp / "echo.py" ) ], idle = "30s" )
        got = [ ]
        ts = [ threading.Thread( target = lambda: got.append( S.ensure( "echo", svc ) ) ) for _ in range( 3 ) ]
        for t in ts:
            t.start()
        for t in ts:
            t.join( 30 )
        assert len( { g[ "pid" ] for g in got } ) == 1, got
        assert len( { g[ "server_pid" ] for g in got } ) == 1, got


if test( "an open connection keeps it, silent or not" ):
    with place() as ( tmp, S ):
        svc = S.Service( [ sys.executable, str( tmp / "echo.py" ) ], idle = "1s" )
        st = S.ensure( "echo", svc )
        c = socket.create_connection( ( "127.0.0.1", st[ "port" ] ) )
        until( lambda: S.state( "echo" ).get( "connections" ) == 1 )
        time.sleep( 3 )
        assert S.state( "echo" )[ "state" ] == "in use", S.state( "echo" )
        c.close()
        until( lambda: S.state( "echo" )[ "state" ] == "stopped", what = "stops once the connection is gone" )


if test( "a busy probe keeps it without connection; a probe that fails counts as busy" ):
    with place() as ( tmp, S ):
        svc = S.Service( [ sys.executable, str( tmp / "echo.py" ) ], idle = "1s", busy = "exit 3" )
        S.ensure( "idle-probe", svc )
        until( lambda: S.state( "idle-probe" )[ "state" ] == "stopped", what = "a probe saying not busy" )
        svc = S.Service( [ sys.executable, str( tmp / "echo.py" ) ], idle = "1s", busy = lambda port: 1 / 0 )
        k = S.Keeper( "failing", svc )
        k.internal = { "port": 1 }
        assert k.probe() is True


if test( "warm, it gives way to a computation; busy, it does not" ):
    with place() as ( tmp, S ):
        flag = tmp / "busy"
        flag.touch()
        svc = S.Service( [ sys.executable, str( tmp / "echo.py" ) ], exclusive = True, idle = "60s",
                         busy = f"test -e {flag}" )
        st = S.ensure( "echo", svc )
        until( lambda: S.state( "echo" )[ "state" ] == "busy" )
        assert "echo ( service )" in "\n".join( Q.describe() ), Q.describe()
        got = [ ]

        def compute():
            with Q.claim( { }, label = "computation" ):
                got.append( time.time() )
        t = threading.Thread( target = compute )
        t.start()
        time.sleep( 3 )
        assert not got, "a busy service is not asked to give way"
        flag.unlink()
        t.join( 30 )
        assert got, "warm, it gave way"
        until( lambda: S.state( "echo" )[ "state" ] == "stopped" )
        assert "evicted" in S.state( "echo" )[ "detail" ], S.state( "echo" )


if test( "waiting for its share, connections wait too, and nobody left waiting gives up" ):
    with place() as ( tmp, S ):
        svc = S.Service( [ sys.executable, str( tmp / "echo.py" ) ], exclusive = True, idle = "2s" )
        with Q.claim( { }, label = "running" ):
            st = S.ensure( "echo", svc, wait = False )
            until( lambda: S.state( "echo" )[ "state" ] == "waiting" )
            port = S.state( "echo" )[ "port" ]
            answer = [ ]

            def ask():
                try:
                    answer.append( echo( port, timeout = 60 ) )   # it waits for the claim
                except Exception as err:
                    answer.append( err )
            t = threading.Thread( target = ask )
            t.start()
            until( lambda: S.state( "echo" ).get( "waiting" ) == 1, what = "the connection waits" )
            time.sleep( 3 )
            assert S.state( "echo" )[ "state" ] == "waiting", "a connection waiting keeps the wait"
        t.join( 60 )
        assert answer == [ b"HELLO" ], ( answer, S.state( "echo" ), ( S.home() / "echo" / "keeper.log" ).read_text() )
        until( lambda: S.state( "echo" )[ "state" ] == "stopped" )

        with Q.claim( { }, label = "running" ):
            S.ensure( "echo", svc, wait = False )
            until( lambda: S.state( "echo" )[ "state" ] == "gave up", what = "nobody waits for it" )


if test( "errand serve stop stops it, and the command line lists it" ):
    with place() as ( tmp, S ):
        env = { **os.environ }
        r = subprocess.run( [ sys.executable, "-m", "errand", "serve", "--name", "echo", "--", sys.executable,
                              str( tmp / "echo.py" ) ], capture_output = True, text = True, env = env, timeout = 60 )
        assert r.returncode == 0 and "echo  http://127.0.0.1:" in r.stdout, r.stdout + r.stderr
        r = subprocess.run( [ sys.executable, "-m", "errand", "serve" ], capture_output = True, text = True, env = env )
        assert "echo" in r.stdout and "idle" in r.stdout, r.stdout
        r = subprocess.run( [ sys.executable, "-m", "errand", "serve", "stop", "echo" ], capture_output = True,
                            text = True, env = env, timeout = 60 )
        assert "stopped" in r.stdout, r.stdout + r.stderr
        assert S.state( "echo" )[ "state" ] == "stopped"
        assert not ( S.home() / "echo" / "keeper.pid" ).exists()


if test( "a declared service is found in the user's file" ):
    with place() as ( tmp, S ):
        conf = tmp / "conf" / "errand"
        conf.mkdir( parents = True )
        ( conf / "services.py" ).write_text(
            "import errand, sys\n"
            f"errand.services[ 'shout' ] = errand.Service( [ sys.executable, {str( tmp / 'echo.py' )!r} ], idle = '2s',\n"
            "    busy = errand.http_json( '/nothing', bool ) )\n" )
        old = os.environ.get( "XDG_CONFIG_HOME" )
        os.environ[ "XDG_CONFIG_HOME" ] = str( tmp / "conf" )
        try:
            assert "shout" in S.declared( cwd = tmp )
            st = S.ensure( "shout", cwd = tmp )
            assert echo( st[ "port" ] ) == b"HELLO"
        finally:
            if old is None:
                os.environ.pop( "XDG_CONFIG_HOME", None )
            else:
                os.environ[ "XDG_CONFIG_HOME" ] = old


TWO = r'''
import os, socket, threading, sys
def serve( port, how ):
    s = socket.socket(); s.setsockopt( socket.SOL_SOCKET, socket.SO_REUSEADDR, 1 ); s.bind( ( "127.0.0.1", port ) ); s.listen()
    def one( c ):
        with c:
            for chunk in iter( lambda: c.recv( 4096 ), b"" ):
                c.sendall( how( chunk ) )
    while True:
        c, _ = s.accept(); threading.Thread( target = one, args = ( c, ), daemon = True ).start()
assert os.environ[ "PORT_UP" ] == sys.argv[ 1 ] and "PORT" not in os.environ
threading.Thread( target = serve, args = ( int( sys.argv[ 1 ] ), bytes.upper ), daemon = True ).start()
serve( int( os.environ[ "PORT_REV" ] ), lambda b: b[ ::-1 ] )
'''


if test( "named ports: each relayed to its server's side, fixed or chosen on either side" ):
    with place() as ( tmp, S ):
        ( tmp / "two.py" ).write_text( TWO )
        fixed_server, fixed_announced = S.free_port(), S.free_port()
        svc = S.Service( [ sys.executable, str( tmp / "two.py" ), "{port:up}" ], idle = "30s",
                         ports = { "up": f":{fixed_server}", "rev": fixed_announced } )
        st = S.ensure( "two", svc )
        assert set( st[ "ports" ] ) == { "up", "rev" }, st
        assert st[ "ports" ][ "up" ][ "server" ] == fixed_server
        assert st[ "ports" ][ "rev" ][ "port" ] == fixed_announced
        assert echo( st[ "ports" ][ "up" ][ "port" ] ) == b"HELLO"
        assert echo( st[ "ports" ][ "rev" ][ "port" ] ) == b"olleh"
        assert S.address( st, "rev" ) == f"127.0.0.1:{fixed_announced}"
        chosen = st[ "ports" ][ "up" ][ "port" ]
        S.stop( "two" )
        assert S.ensure( "two", svc )[ "ports" ][ "up" ][ "port" ] == chosen, "a chosen announced port is kept"


if test( "ports are declared clearly, or refused at once" ):
    from errand import serve as S
    assert S.parse_ports( None ) == { "port": ( None, None ) }
    assert S.parse_ports( 11435 ) == { "port": ( 11435, None ) }
    assert S.parse_ports( { "http": "8080:8081", "grpc": ":50051", "x": "9000:" } ) == \
        { "http": ( 8080, 8081 ), "grpc": ( None, 50051 ), "x": ( 9000, None ) }
    for bad in ( { "http": "8080:8080" }, { "Http": 1 }, { "a": 8080, "b": 8080 }, { "a": "x" }, { "a": 70000 }, { } ):
        try:
            S.parse_ports( bad )
        except ValueError:
            continue
        raise AssertionError( f"accepted: {bad}" )
    for cmd in ( [ "x", "{port:nope}" ], ):
        try:
            S.Service( cmd, ports = { "a": None } )
        except ValueError:
            continue
        raise AssertionError( cmd )
    try:
        S.Service( [ "x", "{port}" ], ports = { "a": None, "b": None } )
        raise AssertionError( "{port} with two ports" )
    except ValueError:
        pass
    assert S.fill( "h:{port:b} {port:a}", { "a": 1, "b": 2 } ) == "h:2 1"


if test( "a server port already taken fails clearly" ):
    with place() as ( tmp, S ):
        with socket.socket() as taken:
            taken.bind( ( "127.0.0.1", 0 ) )
            taken.listen()
            p = taken.getsockname()[ 1 ]
            svc = S.Service( [ sys.executable, str( tmp / "echo.py" ) ], ports = f":{p}" )
            try:
                S.ensure( "echo", svc )
                raise AssertionError( "started on a taken port" )
            except S.Failed as err:
                assert "taken" in str( err ), err


if test( "the owner of a connection, from /proc/net/tcp" ):
    from errand import serve as S
    import struct
    def hexa( ip, port ):
        v = int.from_bytes( socket.inet_aton( ip ), sys.byteorder )
        return f"{v:08X}:{port:04X}"
    table = ( "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
              f"   0: {hexa( '127.0.0.1', 11435 )} 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 1\n"
              f"   1: {hexa( '127.0.0.1', 51000 )} {hexa( '127.0.0.1', 11435 )} 01 00000000:00000000 00:00000000 00000000  1001        0 2\n"
              f"   2: {hexa( '127.0.0.1', 11435 )} {hexa( '127.0.0.1', 51000 )} 01 00000000:00000000 00:00000000 00000000  1000        0 3\n" )
    assert S.tcp_owner( ( "127.0.0.1", 51000 ), ( "127.0.0.1", 11435 ), table ) == 1001
    assert S.tcp_owner( ( "127.0.0.1", 51001 ), ( "127.0.0.1", 11435 ), table ) is None
    if S.can_check_owners():        # Linux: a connection of ours is ours
        with socket.socket() as srv:
            srv.bind( ( "127.0.0.1", 0 ) ); srv.listen()
            c = socket.create_connection( srv.getsockname() )
            a, _ = srv.accept()
            assert S.tcp_owner( a.getpeername(), srv.getsockname() ) == os.getuid()
            c.close(); a.close()


if test( "a connection from another account is closed, unless others" ):
    from errand import serve as S
    real = S.can_check_owners, S.tcp_owner
    try:
        S.can_check_owners = lambda: True
        S.tcp_owner = lambda local, remote, table = None: os.getuid() + 1
        with socket.socket() as srv:
            srv.bind( ( "127.0.0.1", 0 ) ); srv.listen()
            c = socket.create_connection( srv.getsockname() )
            a, _ = srv.accept()
            k = S.Keeper( "x", S.Service( [ "x" ] ) )
            assert not k.mine( a, srv.getsockname()[ 1 ] )
            k = S.Keeper( "x", S.Service( [ "x" ], others = True ) )
            assert k.mine( a, srv.getsockname()[ 1 ] )
            S.tcp_owner = lambda local, remote, table = None: os.getuid()
            assert S.Keeper( "x", S.Service( [ "x" ] ) ).mine( a, srv.getsockname()[ 1 ] )
            c.close(); a.close()
    finally:
        S.can_check_owners, S.tcp_owner = real
