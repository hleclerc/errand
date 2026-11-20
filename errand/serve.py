"""`errand serve`: a service the agent keeps, under the queue, until nobody uses it ( ADR 0018 ).

A service is a long-lived process ( an LLM server, a viewer ), started on demand, never twice, stopped when
nobody uses it, optionally holding a share of the machine that it gives back when a computation needs it while
it rests. One per ( user, machine, name ).

    errand.services[ "ollama" ] = errand.Service( [ "ollama", "serve" ], env = { "OLLAMA_HOST": "127.0.0.1:{port}" },
                                                  gpus = 1, gpu_ram = "10G", busy = errand.http_json( "/api/ps",
                                                  lambda r: bool( r[ "models" ] ) ), idle = "10m", ports = 11435 )

Declared in `~/.config/errand/services.py` ( `$XDG_CONFIG_HOME` ), or in any project file errand reads; or ad hoc,
`errand serve --gpus 1 -- ollama serve`.

Its **keeper** ( `python -m errand.serve keep NAME` ) is a process of this machine's host agent that outlives the
command that asked for it ( `keep`: the agent owns it, lists it, stops it ). It holds everything of one service:

    claim       the queue's ( `queue.claim` ), firm while the service is used, kept warm ( giving way ) otherwise
    ports       named; each has two sides. The announced one, declared or chosen once and kept for the name: the
                keeper listens there, from the start, server up or not, and relays each connection. The server's,
                declared or chosen free at each start, given to the command ( `{port:NAME}`, `$PORT_NAME`; `{port}`,
                `$PORT` when there is one ). Only this account's connections are relayed ( Linux ), unless `others`
    use         open connections ( every one passes the keeper ), or the probe saying busy; never throughput
    stops       evicted while warm, `idle` without connection nor busy, `errand serve stop`, the server ending

Its state is a directory, `~/.cache/errand/serve/<name>/`: `spec.json` ( what to start ), `keeper.pid`, `state.json`
( what it does, for `errand serve list` and `errand status` ), `ports.json` ( the announced ports, kept ), `keeper.log`,
`wanted` ( touched by an `errand serve` that waits for it ), `stop` ( asked to go ).
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

PROBE_EVERY   = 2.0       # seconds between two questions to the probe
PROBE_TIMEOUT = 5.0       # a probe that does not answer within this counts as busy
WANTED_FRESH  = 5.0       # an `errand serve` waiting touches `wanted` more often than this
START_WAIT    = 60.0      # seconds for a keeper to say it exists

# The services declared by the files errand reads: `errand.services[ name ] = errand.Service( ... )`.
services: dict = { }


# ── declaring ────────────────────────────────────────────────────────────────

def seconds( value, default: float = 0.0 ) -> float:
    """`"10m"`, `"30s"`, `"2h"`, `90` ( seconds ) -> seconds."""
    if value is None:
        return default
    if isinstance( value, ( int, float ) ):
        return float( value )
    m = re.fullmatch( r"\s*([0-9.]+)\s*(ms|s|m|min|h|d)?\s*", str( value ) )
    if not m:
        raise ValueError( f"a duration: 30s, 10m, 2h ( got {value!r} )" )
    return float( m.group( 1 ) ) * { None: 1, "ms": 1e-3, "s": 1, "m": 60, "min": 60, "h": 3600, "d": 86400 }[ m.group( 2 ) ]


class Service:
    """A server errand starts on demand and stops when nobody uses it.

    `command`: the server's command, a list ( or a string, split as a shell would ). `ports`: { name: spec }, the
    ports it listens on; a spec is `"ANNOUNCED:SERVER"`, either side empty for errand to choose, or an int ( the
    announced side ), or None ( both chosen ); a bare spec instead of a dict is one port named `port` ( the default:
    one port, both sides chosen ). `{port:NAME}` in the command and in the values of `env` is the server's side of
    port NAME, also in `$PORT_NAME`; `{port}` and `$PORT` when there is one port. `others`: let other accounts of
    the machine connect ( by default, on Linux, a connection from another uid is closed at once ). `gpus`, `gpu_ram`, `ram`, `cpus`, `exclusive`: its claim,
    as for `errand run`; the cards granted are given as a run gets them ( `CUDA_VISIBLE_DEVICES` ... ). `busy`: a
    function of the server's ports ( { name: port } ) -> whether the server is in the middle of something ( its
    claim is then firm ), or a shell command, exit 0 = busy, with the same `{port...}`; a probe that fails counts as
    busy. `ready`: a function of the server's ports -> whether it answers, for a server that accepts before it is
    ready ( default: every port accepts ). `idle`: how long without connection nor busy before it stops.
    `grace`: between asking it to stop and killing it. `cwd`: where it starts ( default: the home directory )."""

    def __init__( self, command, *, env = None, gpus = None, gpu_ram = None, ram = None, cpus = None, exclusive = False,
                  label = None, busy = None, ready = None, idle = "10m", ports = None, others = False, grace = "10s",
                  cwd = None ):
        self.command   = shlex.split( command ) if isinstance( command, str ) else [ str( c ) for c in command ]
        if not self.command:
            raise ValueError( "a service needs a command" )
        self.env       = { str( k ): str( v ) for k, v in ( env or { } ).items() }
        self.gpus, self.gpu_ram, self.ram, self.cpus = gpus, gpu_ram, ram, cpus
        self.exclusive = bool( exclusive )
        self.label     = label
        self.busy      = busy
        self.ready     = ready
        self.idle      = seconds( idle, 600.0 )
        self.ports     = parse_ports( ports )
        self.others    = bool( others )
        self.grace     = seconds( grace, 10.0 )
        self.cwd       = str( cwd ) if cwd else None
        dummy = { n: 1 for n in self.ports }
        for text in [ *self.command, *self.env.values(), *( [ busy ] if isinstance( busy, str ) else [ ] ) ]:
            fill( text, dummy )             # a `{port:NAME}` that names no port: said now, not at start

    def needs( self ) -> dict:
        return { k: v for k, v in ( ( "gpus", self.gpus ), ( "gpu_ram", self.gpu_ram ), ( "ram", self.ram ),
                                    ( "cpus", self.cpus ) ) if v is not None }

    def claims( self ) -> bool:
        return bool( self.needs() ) or self.exclusive

    def wire( self ) -> dict | None:
        """What a keeper is started with, when everything is plain data ( an ad hoc service ); None when a function
        is part of it: the keeper reads the declaration again."""
        if callable( self.busy ) or callable( self.ready ):
            return None
        return { "command": self.command, "env": self.env, "gpus": self.gpus, "gpu_ram": self.gpu_ram, "ram": self.ram,
                 "cpus": self.cpus, "exclusive": self.exclusive, "label": self.label, "busy": self.busy,
                 "idle": self.idle, "ports": { n: list( ab ) for n, ab in self.ports.items() }, "others": self.others,
                 "grace": self.grace, "cwd": self.cwd }

    def __repr__( self ):
        return f"errand.Service( {self.command!r} )"


PORT_NAME = r"[a-z][a-z0-9_]*"


def _one_port( name: str, spec ) -> tuple:
    """A port's spec -> ( announced, server ), None where errand chooses."""
    if spec is None:
        a = i = None
    elif isinstance( spec, int ) and not isinstance( spec, bool ):
        a, i = spec, None
    elif isinstance( spec, ( tuple, list ) ) and len( spec ) == 2:
        a, i = spec
    else:
        m = re.fullmatch( r"\s*(\d*)\s*(?::\s*(\d*)\s*)?", str( spec ) )
        if not m:
            raise ValueError( f"port {name}: ANNOUNCED:SERVER, either side may be empty ( got {spec!r} )" )
        a, i = m.group( 1 ) or None, m.group( 2 ) or None
    a, i = ( int( a ) if a not in ( None, "" ) else None ), ( int( i ) if i not in ( None, "" ) else None )
    for p in ( a, i ):
        if p is not None and not 0 < p < 65536:
            raise ValueError( f"port {name}: {p} is not a port" )
    if a is not None and a == i:
        raise ValueError( f"port {name}: the announced side and the server's differ ( errand listens on {a} and "
                          "relays to the server's ); leave one empty" )
    return a, i


def parse_ports( ports ) -> dict:
    """`ports =` of a Service -> { name: ( announced, server ) }, in the order given."""
    if not isinstance( ports, dict ):
        ports = { "port": ports }
    if not ports:
        raise ValueError( "a service listens on one port at least" )
    got = { }
    for name, spec in ports.items():
        if not re.fullmatch( PORT_NAME, str( name ) ):
            raise ValueError( f"a port's name: lower case letters, digits, _ ( got {name!r} )" )
        got[ str( name ) ] = _one_port( name, spec )
    fixed = [ p for ab in got.values() for p in ab if p is not None ]
    if len( fixed ) != len( set( fixed ) ):
        raise ValueError( f"ports {ports}: one number given twice" )
    return got


def fill( text, server: dict ) -> str:
    """`{port:NAME}` -> the server's side of port NAME; `{port}` when there is one."""
    def one( m ):
        name = m.group( 1 )
        if name is None:
            if len( server ) != 1:
                raise ValueError( f"{{port}} with several ports ( {', '.join( server )} ): {{port:NAME}}" )
            return str( next( iter( server.values() ) ) )
        if name not in server:
            raise ValueError( f"{{port:{name}}}: no port {name!r} ( declared: {', '.join( server )} )" )
        return str( server[ name ] )
    return re.sub( r"\{port(?::(" + PORT_NAME + r"))?\}", one, str( text ) )


def http_json( path: str, predicate = bool, port: str = None ):
    """A probe: GET `http://127.0.0.1:<port><path>`, its JSON given to `predicate` -> busy. `port`: which port's
    server side ( default: the first ). Raises when the server does not answer, which counts as busy."""
    import urllib.request

    def probe( ports: dict ) -> bool:
        p = ports[ port ] if port else next( iter( ports.values() ) )
        with urllib.request.urlopen( f"http://127.0.0.1:{p}{path}", timeout = PROBE_TIMEOUT ) as r:
            return bool( predicate( json.loads( r.read() or b"null" ) ) )
    probe.__name__ = f"http_json({path})"
    return probe


def user_file( ) -> Path:
    base = os.environ.get( "XDG_CONFIG_HOME" ) or str( Path.home() / ".config" )
    return Path( base ) / "errand" / "services.py"


def declared( cwd = None, warn = None ) -> dict:
    """The services declared: the user's file, then the project's files around `cwd`, if any. -> { name: Service }"""
    services.clear()
    f = user_file()
    if f.is_file():
        import runpy
        runpy.run_path( str( f ), run_name = "errand_services" )
    try:
        from .config import load
        from .cli.project import find_root
        root = find_root( Path( cwd or os.getcwd() ) )
        if root is not None and any( Path( root ).glob( "errand-*.py" ) ):
            load( Path( root ), warn = warn )
    except Exception as err:            # a project that does not load must not hide the user's services
        if warn:
            warn( f"the project's files: {err}" )
    return dict( services )


def name_of( svc: Service ) -> str:
    word = svc.label or Path( svc.command[ 0 ] ).name
    return re.sub( r"[^A-Za-z0-9_.-]+", "-", word ).strip( "-." ) or "service"


# ── where a service's state is ───────────────────────────────────────────────

def home( ) -> Path:
    from . import bootstrap
    d = bootstrap.local_cache() / "serve"
    d.mkdir( parents = True, exist_ok = True )
    return d


def spot( name: str ) -> Path:
    if not re.fullmatch( r"[A-Za-z0-9_.-]+", name ) or name.startswith( "." ):
        raise ValueError( f"a service's name: letters, digits, _ . - ( got {name!r} )" )
    d = home() / name
    d.mkdir( parents = True, exist_ok = True )
    return d


def _read_json( path: Path ) -> dict:
    try:
        return json.loads( path.read_text() )
    except ( OSError, ValueError ):
        return { }


def _write_json( path: Path, what: dict ):
    tmp = path.with_name( f".{path.name}.{os.getpid()}-{threading.get_ident()}.tmp" )
    tmp.write_text( json.dumps( what ) )
    tmp.replace( path )


def _alive( pid ) -> bool:
    try:
        pid = int( pid )
    except ( TypeError, ValueError ):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess( 0x1000, False, pid )
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess( h, ctypes.byref( code ) )
        ctypes.windll.kernel32.CloseHandle( h )
        return code.value == 259
    try:
        os.kill( pid, 0 )
    except PermissionError:
        return True
    except OSError:
        return False
    return True


ENDED = ( "stopped", "failed", "gave up" )


def state( name: str ) -> dict:
    """What the service `name` does: `state.json`, its keeper checked alive ( a dead keeper: `stopped` )."""
    d = home() / name
    st = _read_json( d / "state.json" )
    if not st:
        try:
            pid = int( ( d / "keeper.pid" ).read_text() )
        except ( OSError, ValueError ):
            pid = None
        return { "name": name, "state": "starting" if _alive( pid ) else "stopped" }
    if st.get( "state" ) not in ENDED and not _alive( st.get( "pid" ) ):
        st = { **st, "state": "stopped", "detail": "its keeper is gone" }
    return { "name": name, **st }


def listed( ) -> list:
    """Every service this machine knows of, running or not, by name."""
    return [ state( d.name ) for d in sorted( home().iterdir() ) if d.is_dir() and ( d / "spec.json" ).exists() ]


def running( ) -> list:
    return [ s for s in listed() if s.get( "state" ) not in ENDED ]


def free_port( ) -> int:
    with socket.socket() as s:
        s.bind( ( "127.0.0.1", 0 ) )
        return s.getsockname()[ 1 ]


def announced_ports( name: str, svc: Service ) -> dict:
    """{ port name: announced port }: the declared ones, else the ones chosen for this name the first time, kept:
    an address stays the same from one start to the next."""
    f = spot( name ) / "ports.json"
    kept = _read_json( f )
    got = { }
    for n, ( a, _ ) in svc.ports.items():
        got[ n ] = a or kept.get( n )
    taken = { p for ab in svc.ports.values() for p in ab if p } | { p for p in got.values() if p }
    for n in got:
        while not got[ n ]:
            p = free_port()
            if p not in taken:
                got[ n ] = p
                taken.add( p )
    if any( kept.get( n ) != p for n, p in got.items() if not svc.ports[ n ][ 0 ] ):
        _write_json( f, { **kept, **{ n: p for n, p in got.items() if not svc.ports[ n ][ 0 ] } } )
    return got


def server_ports( svc: Service, avoid: set ) -> dict:
    """{ port name: the server's port } for one start: the declared ones, checked free, else free ones."""
    got, taken = { }, set( avoid ) | { i for _, i in svc.ports.values() if i }
    for n, ( _, i ) in svc.ports.items():
        if i:
            with socket.socket() as s:
                try:
                    s.bind( ( "127.0.0.1", i ) )
                except OSError:
                    raise Failed( f"port {n}: the server's side, {i}, is taken ( by an earlier server? )" ) from None
            got[ n ] = i
            continue
        while True:
            p = free_port()
            if p not in taken:
                got[ n ] = p
                taken.add( p )
                break
    return got


def _tcp_ends( field: str ) -> tuple:
    """`0100007F:1F90` of /proc/net/tcp -> ( "127.0.0.1", 8080 )"""
    host, port = field.split( ":" )
    raw = int( host, 16 ).to_bytes( 4, sys.byteorder )
    return socket.inet_ntoa( raw ), int( port, 16 )


def tcp_owner( local: tuple, remote: tuple, table: str = None ) -> int | None:
    """The uid of the socket whose own end is `local` and other end `remote` ( Linux, /proc/net/tcp ): who opened a
    connection that reached us from `local`. None: not found, or not Linux."""
    if table is None:
        try:
            table = Path( "/proc/net/tcp" ).read_text()
        except OSError:
            return None
    for line in table.splitlines()[ 1 : ]:
        f = line.split()
        if len( f ) < 8:
            continue
        try:
            if _tcp_ends( f[ 1 ] ) == tuple( local ) and _tcp_ends( f[ 2 ] ) == tuple( remote ):
                return int( f[ 7 ] )
        except ValueError:
            continue
    return None


def can_check_owners( ) -> bool:
    return Path( "/proc/net/tcp" ).is_file()


# ── the keeper ───────────────────────────────────────────────────────────────

class Keeper:
    """Holds one service: its claim, its ports, its server, its relays, the rules to stop."""

    def __init__( self, name: str, svc: Service ):
        self.name, self.svc, self.dir = name, svc, spot( name )
        self.lock      = threading.Lock()
        self.said      = threading.Lock()   # one writer of state.json at a time, the last state last
        self.conns     = 0
        self.waiting   = 0                  # connections accepted, waiting for the server
        self.ready     = threading.Event()
        self.stopping  = threading.Event()
        self.internal  = { }                # { port name: the server's port }, for this start
        self.announced = { }                # { port name: the announced port }
        self.refused   = 0                  # connections from another account, closed
        self.proc      = None
        self.busy      = False
        self.detail    = ""
        self.now       = "starting"
        self.since     = time.time()

    # what it says
    def say( self, now: str = None, detail: str = None ):
        if now is not None:
            self.now = now
        if detail is not None:
            self.detail = detail
        with self.said:
            self._say()

    def _say( self ):
        with self.lock:
            conns, waiting = self.conns, self.waiting
        first = next( iter( self.announced.values() ), None )
        _write_json( self.dir / "state.json", {
            "state": self.now, "detail": self.detail, "pid": os.getpid(), "since": self.since, "label": self.svc.label or self.name,
            "address": f"127.0.0.1:{first}" if first else None, "port": first,
            "ports": { n: { "address": f"127.0.0.1:{a}", "port": a, "server": self.internal.get( n ) }
                       for n, a in self.announced.items() },
            "refused": self.refused, "connections": conns, "waiting": waiting, "command": self.svc.command,
            "server_pid": self.proc.pid if self.proc else None, "updated": time.time() } )

    def log( self, text: str ):
        print( time.strftime( "%H:%M:%S " ) + text, flush = True )

    # connections
    def listen( self ) -> dict:
        """Every announced port listened on, from now on, server up or not. -> { port name: socket }"""
        self.announced = announced_ports( self.name, self.svc )
        got = { }
        try:
            for n, port in self.announced.items():
                s = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
                got[ n ] = s
                if os.name != "nt":
                    s.setsockopt( socket.SOL_SOCKET, socket.SO_REUSEADDR, 1 )
                try:
                    s.bind( ( "127.0.0.1", port ) )
                except OSError as err:
                    raise OSError( f"port {n}, 127.0.0.1:{port}: {err.strerror or err}" ) from None
                s.listen( 64 )
                s.settimeout( 0.5 )
        except OSError:
            for s in got.values():
                s.close()
            raise
        return got

    def mine( self, client: socket.socket, port: int ) -> bool:
        """Whether this connection comes from this account ( Linux ); `others`, or no way to know: yes."""
        if self.svc.others or not can_check_owners():
            return True
        try:
            peer = client.getpeername()
        except OSError:
            return False
        uid = tcp_owner( peer[ : 2 ], ( "127.0.0.1", port ) )
        if uid is None:     # the table is read once more: a connection may show there a moment late
            time.sleep( 0.01 )
            uid = tcp_owner( peer[ : 2 ], ( "127.0.0.1", port ) )
        if uid == os.getuid():
            return True
        self.log( f"a connection from uid {uid} closed: only this account's are relayed ( others = True opens it )" )
        return False

    def accept( self, server: socket.socket, name: str ):
        port = self.announced[ name ]
        while not self.stopping.is_set():
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if not self.mine( client, port ):
                with contextlib.suppress( OSError ):
                    client.close()
                with self.lock:
                    self.refused += 1
                self.say()
                continue
            with self.lock:
                self.conns += 1
            threading.Thread( target = self.relay, args = ( client, name ), daemon = True ).start()
            self.say()

    def relay( self, client: socket.socket, name: str ):
        """One connection: it waits for the server if it is not ready yet, then both ways until either side closes."""
        upstream = None
        try:
            client.settimeout( None )
            if not self.ready.is_set():
                with self.lock:
                    self.waiting += 1
                self.say()
                try:
                    while not self.ready.wait( 0.5 ):
                        if self.stopping.is_set():
                            return
                finally:
                    with self.lock:
                        self.waiting -= 1
            if self.stopping.is_set():
                return
            upstream = socket.create_connection( ( "127.0.0.1", self.internal[ name ] ), timeout = 10 )
            upstream.settimeout( None )
            done = threading.Event()

            def pump( a, b ):
                try:
                    while True:
                        chunk = a.recv( 65536 )
                        if not chunk:
                            break
                        b.sendall( chunk )
                except OSError:
                    pass
                finally:
                    with contextlib.suppress( OSError ):
                        b.shutdown( socket.SHUT_WR )
                    done.set()

            t1 = threading.Thread( target = pump, args = ( client, upstream ), daemon = True )
            t2 = threading.Thread( target = pump, args = ( upstream, client ), daemon = True )
            t1.start(); t2.start()
            t1.join(); t2.join()
        except OSError as err:
            self.log( f"a connection: {err}" )
        finally:
            for s in ( client, upstream ):
                if s is not None:
                    with contextlib.suppress( OSError ):
                        s.close()
            with self.lock:
                self.conns -= 1
            self.say()

    # what it asks of the server
    def answers( self ) -> bool:
        if self.svc.ready is not None:
            try:
                return bool( self.svc.ready( self.internal ) )
            except Exception:
                return False
        for port in self.internal.values():
            try:
                with socket.create_connection( ( "127.0.0.1", port ), timeout = 1 ):
                    pass
            except OSError:
                return False
        return True

    def probe( self ) -> bool:
        """Busy? A probe that fails or does not answer counts as busy: a saturated server is in the middle of
        something. No probe: never busy, only its connections say it is used."""
        busy = self.svc.busy
        if busy is None:
            return False
        got = [ True ]

        def ask():
            try:
                if callable( busy ):
                    got[ 0 ] = bool( busy( self.internal ) )
                else:
                    cmd = fill( busy, self.internal )
                    got[ 0 ] = subprocess.run( cmd, shell = True, timeout = PROBE_TIMEOUT,
                                               stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL ).returncode == 0
            except Exception:
                got[ 0 ] = True
        t = threading.Thread( target = ask, daemon = True )
        t.start()
        t.join( PROBE_TIMEOUT )
        return got[ 0 ]

    def wanted( self ) -> bool:
        """an `errand serve` waits for it"""
        try:
            return time.time() - ( self.dir / "wanted" ).stat().st_mtime < WANTED_FRESH
        except OSError:
            return False

    def asked_to_stop( self ) -> bool:
        return ( self.dir / "stop" ).exists() or self.stopping.is_set()

    # the server
    def start_server( self, granted ):
        self.internal = server_ports( self.svc, set( self.announced.values() ) )
        ports = { f"PORT_{n.upper()}": str( p ) for n, p in self.internal.items() }
        if len( self.internal ) == 1:
            ports[ "PORT" ] = str( next( iter( self.internal.values() ) ) )
        env = { **os.environ, **( granted.env() if granted else { } ),
                **( granted.handed_down() if granted and granted.path else { } ),
                **ports, **{ k: fill( v, self.internal ) for k, v in self.svc.env.items() } }
        argv = [ fill( a, self.internal ) for a in self.svc.command ]
        self.log( "starting " + " ".join( shlex.quote( a ) for a in argv ) + "  ( "
                  + ", ".join( f"{n} {self.announced[ n ]} -> {p}" for n, p in self.internal.items() ) + " )" )
        kw = { "start_new_session": True } if os.name != "nt" else \
             { "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP }
        self.proc = subprocess.Popen( argv, env = env, cwd = self.svc.cwd or str( Path.home() ), stdin = subprocess.DEVNULL,
                                      stdout = sys.stdout, stderr = subprocess.STDOUT, **kw )

    def stop_server( self ):
        """INT, TERM after 2 s, KILL after `grace`, on its group: what the agents do ( ADR 0008 )."""
        p = self.proc
        if p is None or p.poll() is not None:
            return

        def send( sig ):
            with contextlib.suppress( OSError ):
                if os.name == "nt":
                    p.send_signal( signal.CTRL_BREAK_EVENT if sig == signal.SIGINT else sig )
                else:
                    os.killpg( p.pid, sig )

        send( signal.SIGINT )
        steps = [ ( 2.0, signal.SIGTERM ), ( max( self.svc.grace - 2.0, 1.0 ), getattr( signal, "SIGKILL", signal.SIGTERM ) ) ]
        for wait, sig in steps:
            try:
                p.wait( wait )
                return
            except subprocess.TimeoutExpired:
                send( sig )
        with contextlib.suppress( subprocess.TimeoutExpired ):
            p.wait( 5 )

    # the whole of it
    def run( self ) -> int:
        ( self.dir / "keeper.pid" ).write_text( str( os.getpid() ) )
        ( self.dir / "stop" ).unlink( missing_ok = True )
        if os.name != "nt":
            signal.signal( signal.SIGTERM, lambda *_: sys.exit( 0 ) )
        why, code = "stopped", 0
        listening = { }
        try:
            try:
                listening = self.listen()
            except OSError as err:
                self.say( "failed", str( err ) )
                self.log( f"cannot listen: {err}" )
                return 1
            for n, sock in listening.items():
                threading.Thread( target = self.accept, args = ( sock, n ), daemon = True ).start()
            if not self.svc.others and not can_check_owners():
                self.log( "connections from other accounts cannot be told apart on this system: all are relayed" )
            from . import queue as Q
            needs = self.svc.needs()
            label = self.svc.label or self.name
            idle_since = [ time.time() ]

            def give_up() -> bool:
                if self.asked_to_stop():
                    return True
                with self.lock:
                    used = self.conns > 0
                if used or self.wanted():
                    idle_since[ 0 ] = time.time()
                    return False
                return time.time() - idle_since[ 0 ] > self.svc.idle

            self.say( "waiting" if self.svc.claims() else "starting" )
            holding = Q.claim( needs, exclusive = self.svc.exclusive, label = f"{label} ( service )",
                               echo = lambda m: ( self.log( m.strip() ), self.say( "waiting", m.strip() ) ),
                               give_up = give_up ) if self.svc.claims() else contextlib.nullcontext( None )
            try:
                with holding as granted:
                    why = self.serve( granted )
            except Q.GaveUp as err:
                self.say( "gave up", str( err ) )
                self.log( f"nobody waits for it any more: {err}" )
                return 0
            except Failed as err:
                self.say( "failed", str( err ) )
                self.log( str( err ) )
                return 1
        except SystemExit:
            why = "stopped ( asked )"
        except Exception as err:
            import traceback
            traceback.print_exc()
            why, code = f"failed: {err}", 1
        finally:
            self.stopping.set()
            self.stop_server()
            for sock in listening.values():
                with contextlib.suppress( OSError ):
                    sock.close()
            if self.now not in ENDED:
                self.say( "failed" if code else "stopped", why )
            self.log( f"done: {why}" )
            ( self.dir / "keeper.pid" ).unlink( missing_ok = True )
            ( self.dir / "stop" ).unlink( missing_ok = True )
        return code

    def serve( self, granted ) -> str:
        """The server started, then watched until a rule stops it. -> why it stopped."""
        self.start_server( granted )
        self.say( "starting", "" )
        while not self.answers():
            if self.proc.poll() is not None:
                self.say( "failed", f"the server ended before it answered ( exit {self.proc.returncode} )" )
                return f"the server ended before it answered ( exit {self.proc.returncode} )"
            if self.asked_to_stop():
                return "asked to stop"
            time.sleep( 0.2 )
        self.ready.set()
        self.log( "ready: " + ", ".join( f"{n} 127.0.0.1:{self.announced[ n ]} -> {p}" for n, p in self.internal.items() ) )
        idle_since, warm = None, None
        next_probe = 0.0
        while True:
            if self.proc.poll() is not None:
                return f"the server ended by itself ( exit {self.proc.returncode} )"
            if self.asked_to_stop():
                return "asked to stop"
            now = time.time()
            if now >= next_probe:
                self.busy = self.probe()
                next_probe = now + PROBE_EVERY
            with self.lock:
                conns = self.conns
            used = conns > 0 or self.busy
            if granted is not None and granted.path is not None and warm != ( not used ):
                warm = not used
                granted.preemptible( warm )
            if used:
                idle_since = None
                self.say( "busy" if self.busy else "in use", f"{conns} connection{'s' * ( conns != 1 )}" )
            else:
                idle_since = idle_since or now
                if granted is not None and granted.path is not None and granted.evicted():
                    return "gave its share to a computation ( evicted while warm )"
                left = self.svc.idle - ( now - idle_since )
                if left <= 0:
                    return f"idle for {_human( self.svc.idle )}"
                self.say( "warm" if granted is not None and granted.path is not None else "idle",
                          f"idle for {_human( now - idle_since )}, stops in {_human( left )}" )
            time.sleep( 0.5 )


def _human( s: float ) -> str:
    s = int( s )
    return f"{s} s" if s < 90 else f"{s // 60} min" if s < 5400 else f"{s // 3600} h {s % 3600 // 60:02d}"


def keep( name: str ) -> int:
    """`python -m errand.serve keep NAME`: the keeper, as the agent starts it. Its output, and its server's, in
    `keeper.log`: whoever started it may be gone."""
    d = spot( name )
    fd = os.open( str( d / "keeper.log" ), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644 )
    for to in ( 1, 2 ):
        os.dup2( fd, to )
    os.close( fd )
    sys.stdout = os.fdopen( 1, "w", buffering = 1 )
    sys.stderr = os.fdopen( 2, "w", buffering = 1 )
    ( d / "keeper.pid" ).write_text( str( os.getpid() ) )
    spec = _read_json( d / "spec.json" )
    if spec.get( "wire" ) is not None:
        svc = Service( **{ k: v for k, v in spec[ "wire" ].items() } )
    else:
        svc = declared( spec.get( "cwd" ) ).get( name )
        if svc is None:
            _write_json( d / "state.json", { "state": "failed", "detail": f"no service {name!r} is declared any more",
                                             "pid": os.getpid() } )
            return 1
    return Keeper( name, svc ).run()


# ── asking for it ────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _start_lock( d: Path ):
    try:
        import fcntl
    except ImportError:
        yield
        return
    fd = os.open( str( d / "start.lock" ), os.O_CREAT | os.O_RDWR, 0o600 )
    try:
        fcntl.flock( fd, fcntl.LOCK_EX )
        yield
    finally:
        os.close( fd )


def _errand_path( ) -> str:
    """Where this errand is imported from: the keeper imports the same one."""
    return str( Path( __file__ ).resolve().parent.parent )


def start_keeper( name: str ):
    """Through this machine's host agent, as one of its processes that outlives this command ( `keep` ): the agent
    owns it, lists it, stops it. No agent to be had: a session of its own, still on this machine."""
    d = spot( name )
    argv = [ sys.executable, "-m", "errand.serve", "keep", name ]
    env = { "PYTHONPATH": os.pathsep.join( p for p in ( _errand_path(), os.environ.get( "PYTHONPATH", "" ) ) if p ) }
    ( d / "keeper.pid" ).unlink( missing_ok = True )
    started = False
    if os.environ.get( "ERRAND_SERVE_NO_AGENT" ) != "1":
        try:
            from .agents import upstream as U
            from .web import host_agent_dir
            conn = U.direct( { "kind": "local", "dir": str( host_agent_dir() ), "keep_alive": U.KEEP_ALIVE } )
            try:
                call = conn.open( { "op": "spawn", "argv": argv, "cwd": str( Path.home() ), "keep": True, "env": env } )
                call.reply( 30 )
                from .agents import frames as F
                call.send( F.EOF )
                call.close()
            finally:
                conn.close()
            started = True
        except Exception as err:
            print( f"errand serve: the host agent could not start the keeper ( {err} ): started on its own",
                   file = sys.stderr )
    if not started:
        kw = { "start_new_session": True } if os.name != "nt" else { "creationflags": 0x00000200 }
        subprocess.Popen( argv, env = { **os.environ, **env }, stdin = subprocess.DEVNULL, stdout = subprocess.DEVNULL,
                          stderr = subprocess.DEVNULL, cwd = str( Path.home() ), **kw )
    deadline = time.monotonic() + START_WAIT
    while not ( d / "keeper.pid" ).exists() and not ( d / "state.json" ).exists() and time.monotonic() < deadline:
        time.sleep( 0.1 )


class Failed( RuntimeError ):
    pass


def ensure( name: str, svc: Service | None = None, *, cwd = None, echo = None, wait = True ) -> dict:
    """The service `name` running, its keeper started if need be, and, with `wait`, answering. -> its state ( with
    `address` ). `svc`: an ad hoc service ( its spec written for the keeper ); None: a declared one, read again by
    the keeper from the files around `cwd`. Two at once start one."""
    d = spot( name )
    with _start_lock( d ):
        st = state( name )
        if st.get( "state" ) in ENDED:
            if svc is not None:
                wire = svc.wire()
                if wire is None:
                    raise ValueError( "an ad hoc service is plain data: its probe is a command ( --busy-if )" )
                spec = { "name": name, "wire": wire, "cwd": str( cwd or os.getcwd() ) }
            else:
                spec = { "name": name, "wire": None, "cwd": str( cwd or os.getcwd() ) }
            _write_json( d / "spec.json", spec )
            ( d / "state.json" ).unlink( missing_ok = True )
            ( d / "stop" ).unlink( missing_ok = True )
            ( d / "wanted" ).touch()
            start_keeper( name )
    said = None
    while True:
        ( d / "wanted" ).touch()
        st = state( name )
        now = st.get( "state", "starting" )
        if now in ENDED and ( d / "state.json" ).exists():
            raise Failed( st.get( "detail" ) or now )
        if now == "stopped" and not ( d / "keeper.pid" ).exists():
            raise Failed( "its keeper did not start: " + _tail( d / "keeper.log" ) )
        if now not in ( "starting", "waiting" ):
            return st
        line = now + ( f": {st[ 'detail' ]}" if st.get( "detail" ) else "" )
        if echo and line != said:
            echo( line )
            said = line
        if not wait and now != "starting":
            return st
        time.sleep( 0.2 )


def _tail( path: Path, n: int = 12 ) -> str:
    try:
        return "\n".join( path.read_text( errors = "replace" ).splitlines()[ -n : ] )
    except OSError:
        return "( no log )"


def stop( name: str, wait: float = 30.0 ) -> bool:
    """Ask the keeper of `name` to go ( it stops the server, then releases its claim ). -> whether it went."""
    d = home() / name
    if not d.is_dir() or state( name ).get( "state" ) in ENDED:
        return False
    ( d / "stop" ).touch()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if state( name ).get( "state" ) in ENDED:
            return True
        time.sleep( 0.2 )
    pid = _read_json( d / "state.json" ).get( "pid" )
    if pid and _alive( pid ) and os.name != "nt":
        with contextlib.suppress( OSError ):
            os.kill( int( pid ), signal.SIGTERM )
    return True


def address( st: dict, port: str = None ) -> str:
    """The announced address of port `port` ( default: the first ) in a state."""
    if not port:
        return st[ "address" ]
    ports = st.get( "ports" ) or { }
    if port not in ports:
        raise Failed( f"no port {port!r} ( ports: {', '.join( ports ) or 'none'} )" )
    return ports[ port ][ "address" ]


def connect( name: str, svc: Service | None = None, cwd = None, port: str = None ) -> int:
    """`errand serve connect NAME [PORT]`: the service ensured, then this process's stdin and stdout relayed to its
    port PORT ( the first by default ) -- what `command=` in `authorized_keys` runs for a tunnel. Its connection
    counts like any other."""
    st = ensure( name, svc, cwd = cwd, echo = lambda m: print( f"errand serve: {m}", file = sys.stderr, flush = True ) )
    host, p = address( st, port ).rsplit( ":", 1 )
    s = socket.create_connection( ( host, int( p ) ) )

    def up():
        try:
            for chunk in iter( lambda: os.read( 0, 65536 ), b"" ):
                s.sendall( chunk )
        except OSError:
            pass
        with contextlib.suppress( OSError ):
            s.shutdown( socket.SHUT_WR )

    threading.Thread( target = up, daemon = True ).start()
    try:
        while True:
            chunk = s.recv( 65536 )
            if not chunk:
                break
            view = memoryview( chunk )
            while view:
                view = view[ os.write( 1, view ) : ]
    except OSError:
        pass
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    if len( sys.argv ) == 3 and sys.argv[ 1 ] == "keep":
        # As `errand.serve`, not `__main__`: the files it reads fill `errand.services`, which is that module's.
        from errand.serve import keep as _keep
        sys.exit( _keep( sys.argv[ 2 ] ) )
    print( "usage: python -m errand.serve keep NAME", file = sys.stderr )
    sys.exit( 2 )
