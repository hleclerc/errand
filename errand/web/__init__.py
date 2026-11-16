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
    access      a token drawn when the agent starts, in the URL, then a cookie; `Host` checked.
                It is in `web.json` ( mode 0600 ) beside the lock, for `errand web` to read
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
        return Web.start( bootstrap.local_cache() )
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
    return { **rec, "url": f"http://127.0.0.1:{rec[ 'port' ]}/?t={rec[ 'token' ]}" }


def main( echo = print, browse = True ) -> int:
    """`errand web`: the host agent here started if need be, then its page opened."""
    got = said()
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
    if got is None:
        echo( f"errand web: the agent in {host_agent_dir()} serves no page ( started by an older errand? "
              "`errand agents stop`, then again; its log says more )" )
        return 1
    echo( got[ "url" ] )
    if browse:
        import webbrowser
        try:
            webbrowser.open( got[ "url" ] )
        except Exception:
            pass
    return 0
