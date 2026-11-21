"""`errand web`: the same view as `errand tui`, as a page in a browser.

    errand web          -> http://127.0.0.1:2xxxx/?t=…     ( opened in the browser, and printed )

The page is served by this machine's host agent ( `agents/host-…` ), the one that holds
`~/.cache/errand/web.lock`: one per user and machine, nested agents ( environments, allocations )
serve none. It shows what `errand tui` shows -- this machine and every machine of its ledger, what
runs there, what waits, VMs and guests, the history, the files and output of a run -- asked through
the agents as the TUI asks them ( `tui.machines`, `tui.rows` ), and only while a page asks: the
machines are let go of 30 s after the last request.

    address     127.0.0.1 only; port 20000 + uid % 10000, any free one when taken. From elsewhere:
                `ssh -L PORT:localhost:PORT host`, then `errand web` there gives the URL
    access      the port is open to every user of the machine: a page is served only to who holds
                the token, drawn when the agent starts ( 384 bits ), kept in `web.json` ( mode 0600 ).
                `errand web` opens the page with a code used once ( `web-once/`, two minutes ): a URL
                seen in `ps` or a history is already spent. Otherwise the page asks for the token
                ( `errand web token` prints it ). Then a cookie; `Host` checked; an action from another
                page refused ( `Origin` ); a run's files served in a sandbox, apart from the page
    life        a page that asks keeps its agent: a request counts as use

Stdlib only ( `http.server` ): errand still installs with nothing.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .. import bootstrap

LOCK  = "web.lock"
SAID  = "web.json"
ONCE  = "web-once"            # codes used once, that `errand web` puts in the URL it opens
ONCE_FOR = 120.0
WAIT  = 20.0                # seconds `errand web` waits for the agent to say where its page is


def port_of_user( ) -> int:
    """The same port for the same user, every time: a tunnel written once keeps working."""
    if hasattr( os, "getuid" ):
        uid = os.getuid()
    else:
        import zlib
        uid = zlib.crc32( os.environ.get( "USERNAME", "" ).encode() )
    return 20000 + uid % 10000


def host_agent_dir( ) -> Path:
    """This machine's host agent, where ssh would start it ( `upstream.argv_of` )."""
    from ..agents import upstream as U
    return bootstrap.local_cache() / U.AGENTS / U.name_of( { "kind": "ssh" }, U.this_machine() )


def serves( root: Path ) -> bool:
    """Whether the agent in `root` is a host agent: the one kind that serves the page."""
    root = Path( root )
    return root.name.startswith( "host-" ) and root.parent.resolve() == ( bootstrap.local_cache() / "agents" ).resolve()


def start( root: Path ):
    """Started by the agent in `root`: the page served from a thread, if this agent is the one that
    serves it -> the `Web`, or None. Never fatal to the agent: what fails is written to its log."""
    if not serves( root ):
        return None
    try:
        from .server import Web
        # The user's ports ( the same every time: a tunnel written once ) are the user's own cache's: an agent of another
        # cache ( a test's, `ERRAND_CACHE_DIR` ) takes any free one, never the page of its user.
        own = bootstrap.local_cache().resolve() == ( Path.home() / bootstrap.BASE ).expanduser().resolve()
        web = Web.start( bootstrap.local_cache(), port = None if own else 0, agent = str( Path( root ).resolve() ) )
        if web is not None:
            try:
                from . import static
                web.static = static.start( at = None if own else 0 )   # the views opened as they are, beside the page
            except Exception:
                import traceback
                traceback.print_exc()
        return web
    except Exception:
        import traceback
        traceback.print_exc()
        return None


def said( ) -> dict | None:
    """Where the page of this machine is, if an agent serves it: { port, token, pid, url }."""
    from ..agents.endpoint import hold
    cache = bootstrap.local_cache()
    try:
        rec = json.loads( ( cache / SAID ).read_text() )
    except ( OSError, ValueError ):
        return None
    free = hold( cache / LOCK )
    if free is not None:              # nobody holds the lock: what the file says is a leftover
        free.close()
        return None
    return { **rec, "url": f"http://127.0.0.1:{rec[ 'port' ]}/" }


def once( ) -> str:
    """A code that opens the page once, within `ONCE_FOR` seconds ( `server._Handler` spends it )."""
    import secrets
    d = bootstrap.local_cache() / ONCE
    d.mkdir( mode = 0o700, parents = True, exist_ok = True )
    os.chmod( d, 0o700 )
    code = secrets.token_urlsafe( 32 )
    fd = os.open( str( d / code ), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 )
    os.close( fd )
    return code


def spend( code: str ) -> bool:
    """Whether `code` opens the page: it exists, is fresh, and is used now, so never again."""
    if not code or "/" in code or "\\" in code or code.startswith( "." ):
        return False
    path = bootstrap.local_cache() / ONCE / code
    try:
        fresh = time.time() - path.stat().st_mtime < ONCE_FOR
        path.unlink()
    except OSError:
        return False
    for old in ( bootstrap.local_cache() / ONCE ).glob( "*" ):          # what was never used
        try:
            if time.time() - old.stat().st_mtime > ONCE_FOR:
                old.unlink()
        except OSError:
            pass
    return fresh


def _older( got: dict | None ) -> bool:
    """whether the page is served by a host agent of other sources than these ( an errand changed since it started )"""
    return got is not None and got.get( "sources" ) != bootstrap.sources_key()


def _retire( got: dict ) -> bool:
    """The host agent of older sources that serves the page asked to go ( `stop`, never forced: one that runs work stays,
    and its page with it ); -> whether the page was given up. Its directory from `web.json`, else the host agents here of
    other sources ( a `web.json` written before it said it )."""
    from ..agents import upstream as U
    agents = bootstrap.local_cache() / U.AGENTS
    dirs = [ Path( got[ "agent" ] ) ] if got.get( "agent" ) else [
        d for d in sorted( agents.glob( "host-*" ) ) if d.resolve() != host_agent_dir().resolve() ]
    for d in dirs:
        try:
            conn = U.direct( { "kind": "local", "dir": str( d ), "keep_alive": U.KEEP_ALIVE } )
            try:
                call = conn.open( { "op": "stop" } )
                call.reply( 10 )
                call.close()
            finally:
                conn.close()
        except Exception:
            continue
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if said() is None:
            return True
        time.sleep( 0.2 )
    return False


def ensure( ) -> dict | None:
    """Where the page of this machine is ( `said` ), the host agent started if need be: None when it serves none. A
    page served by a host agent of older sources is handed over to the one of these, when the old one runs nothing."""
    got = said()
    if _older( got ) and _retire( got ):
        got = None
    if got is None:
        from ..agents import upstream as U
        conn = U.direct( { "kind": "local", "dir": str( host_agent_dir() ), "keep_alive": U.KEEP_ALIVE } )
        try:
            call = conn.open( { "op": "ping" } )
            call.reply( 60 )
            call.close()
        finally:
            conn.close()
        deadline = time.monotonic() + WAIT
        while got is None and time.monotonic() < deadline:
            time.sleep( 0.2 )
            got = said()
    return got


def run_link( leaf, start = False ) -> str | None:
    """The address of a run's page ( `/r/<id>`, ADR 0017 §5 ), the run named by its directory over there: on this
    machine's page, which reads the other machines through the agents. No secret in it: the page's cookie lasts.
    None when no agent serves the page here ( `start`: started if need be )."""
    from ..agents.seen import ident
    try:
        got = ensure() if start else said()
    except Exception:
        got = None
    if _older( got ) and not start:
        _wake()                                   # a page of older sources: handed over aside ( `ensure` )
    if got is None and not start:
        # Nobody serves the page now: it is said all the same, at the port of its user ( the one the page takes ), and
        # the host agent is woken aside, so that the page is there when the link is followed. Never a wait for the run.
        _wake()
        return f"http://127.0.0.1:{port_of_user()}/r/{ident( leaf )}"
    return f"{got[ 'url' ]}r/{ident( leaf )}" if got else None


_woken = [ False ]


def _wake( ):
    """the host agent asked once, from a thread: it starts the page if it is not served"""
    if _woken[ 0 ]:
        return
    _woken[ 0 ] = True
    import threading

    def go():
        try:
            ensure()
        except Exception:
            pass
    threading.Thread( target = go, daemon = True ).start()


def main( words = ( ), echo = print, browse = True ) -> int:
    """`errand web`: the host agent here started if need be, then its page opened, with a code used once.
    `errand web token`: the token, to paste in a page that asks for it ( through a tunnel, another browser )."""
    if list( words ) == [ "dev" ]:
        return dev( echo = echo, browse = browse )
    if list( words ) not in ( [ ], [ "token" ] ):
        echo( "errand web: `errand web` opens the page, `errand web token` prints its token, "
              "`errand web dev` serves it from these sources" )
        return 2
    got = ensure()
    if got is None:
        echo( f"errand web: the agent in {host_agent_dir()} serves no page ( started by an older errand? "
              "`errand agents restart`; its log says more )" )
        return 1
    if list( words ) == [ "token" ]:
        echo( got[ "token" ] )
        return 0
    url = f"{got[ 'url' ]}?o={once()}"
    echo( f"{url}   ( once, within {ONCE_FOR / 60:.0f} min; then `errand web token` for the page that asks )" )
    if browse:
        import webbrowser
        try:
            webbrowser.open( url )
        except Exception:
            pass
    return 0


def dev( echo = print, browse = True, port = None ) -> int:
    """`errand web dev`: the page served by this process, from the sources as they are now, beside the
    agent's ( which goes on, and what it follows with it ): to work on the page without stopping what runs.
    The page is read again at each load ( `page.py`: reload the tab ); the server's code, at each start
    ( Ctrl-C, again ). Its own lock and token, the same codes used once."""
    from .server import Web
    web = Web.start( bootstrap.local_cache() / "web-dev", port = port_of_user() + 1 if port is None else port,
                     reload_page = True )
    if web is None:
        echo( "errand web dev: another one serves already ( its lock: "
              f"{bootstrap.local_cache() / 'web-dev' / LOCK} )" )
        return 1
    url = f"http://127.0.0.1:{web.port}/?o={once()}"
    echo( f"{url}   ( this process, these sources: page.py read at each load; Ctrl-C ends it )" )
    if browse:
        import webbrowser
        try:
            webbrowser.open( url )
        except Exception:
            pass
    try:
        while True:
            time.sleep( 3600 )
    except KeyboardInterrupt:
        pass
    finally:
        web.stop()
    return 0
