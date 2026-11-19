"""The bottom of `errand run` ( ADR 0016 ): what is under way, never part of the history.

    ┃ a out 41                                   the case in front ( Focus ), live, when one is
    1 ▸ case a · iteration 41 · ▕████▏ 41 %     one line per case running, several under `-j`
    2 ▸ case b · 12 s
    lmo: ssh:lmo -> vars · ↓ sync pull ← lmo    what errand does to get there ( `put`, `working` )

Errand's line is made of named parts ( `env`, `work`, `step` for a case run in this process ), drawn
together; a part goes when it is done. A case running is said by whoever follows it ( `case_start`,
`case_step`, `case_end` ): with one case, its line and errand's are one. At most a third of the terminal
for the cases, then `+k more`. Off a terminal nothing is drawn.

Focus ( `keys`, under `-j` ): `1` … `9` or Tab puts a case in front, its output scrolling above the
lines; Esc goes back. The case's block is still drawn whole in the history when it ends.

    with working( "↑ sync push → lmo" ) as w:      # drawn with the time it takes, while it takes it
        report = push( ... )
        w.numbers = { "files": 126, "bytes": 1.1e6 }
    w.record                                        # { "transfer": "push", "s": 0.8, "files": 126, ... }
"""
from __future__ import annotations

import contextlib
import os
import re
import shutil
import sys
import threading
import time

_parts: dict = { }
_cases: dict = { }                  # key -> { label, step, since, recent }, in the order they started
_focus = None                       # the key of the case in front, or None
_footer = None
_ticker = None
_lock = threading.RLock()


# ── drawing ──────────────────────────────────────────────────────────────────

def _usable( ) -> bool:
    from .footer import Footer
    return Footer.usable( sys.stdout )


def _elapsed( since: float ) -> str:
    s = int( time.time() - since )
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60:02d} s"


def _said( k: dict ) -> str:
    """A case's line after its name: its step, or how long it has run; and whether it seems to wait."""
    text = k[ "step" ] or _elapsed( k[ "since" ] )
    try:
        if k.get( "waiting" ) and k[ "waiting" ]():
            text += " · ⌨ waits for input?"
    except Exception:
        pass
    return text


def lines( rows: int | None = None ) -> list:
    """What the bottom shows now, top to bottom."""
    from .render import BOLD, CYAN, DIM, RESET, YELLOW, colors_on
    rows = rows or shutil.get_terminal_size().lines
    color = colors_on( sys.stdout )
    c = lambda code, t: f"{code}{t}{RESET}" if color else t
    errand = " · ".join( t for t in _parts.values() if t )
    cases = list( _cases.items() )
    if len( cases ) <= 1 and _focus is None and not _keys_on:
        # one case, or none: the case says how long it runs under its own lines ( `render.Renderer.status` );
        # here, only what errand does outside a place line
        return [ errand ] if errand else [ ]
    room = max( 1, rows // 3 )
    out = [ ]
    for key, k in cases[ : room ]:
        mark = "▶" if key == _focus else "▸"
        out.append( f"{c( DIM, str( k.get( 'n', '·' ) ) )} {c( BOLD + CYAN, mark + ' ' + k[ 'label' ] )} · {_said( k )}" )
    if len( cases ) > room:
        out.append( c( DIM, f"+{len( cases ) - room} more" ) )
    if errand:
        out.append( errand )
    if _focus is not None and _focus in _cases and _cases[ _focus ].get( "recent" ):
        live = max( 3, rows - len( out ) - rows // 3 )
        try:
            shown = _cases[ _focus ][ "recent" ]( live )
        except Exception:
            shown = [ ]
        out = [ *shown[ -live : ], *out ]
    front = _cases.get( _focus ) if _focus is not None else None
    if front is not None and front.get( "write" ):
        out.append( c( YELLOW, f"› {_typed.decode( errors = 'replace' )}" ) + "▏" )
    if cases and _keys_on:
        out.append( c( DIM, "1-9 / tab: a case in front · esc: back"
                            + ( " · enter: send the line to it · ctrl-d: end its input" if front and front.get( "write" ) else "" ) ) )
    return out


def _draw( ):
    global _footer
    from .footer import Footer
    from .render import _lock as screen
    if _footer is None:
        if not _usable():
            return
        _footer = Footer( sys.stdout )
    with _lock:
        shown = lines()
    with screen:
        _footer.show_lines( shown )


def redraw( ):
    try:
        _draw()
    except Exception:
        pass                                # the bottom is a courtesy: never a failure


def _tick( ):
    """Times and steps move by themselves: drawn again twice a second while a case runs."""
    global _ticker
    with _lock:
        if _ticker is not None:
            return

        def loop():
            global _ticker
            while True:
                time.sleep( 0.5 )
                with _lock:
                    if not _cases:
                        _ticker = None
                        return
                    for k in _cases.values():
                        if k.get( "poll" ):
                            try:
                                k[ "step" ] = k[ "poll" ]() or k[ "step" ]
                            except Exception:
                                pass
                redraw()

        _ticker = threading.Thread( target = loop, daemon = True )
        _ticker.start()


# ── what is under way ────────────────────────────────────────────────────────

def put( key: str, text: str | None ):
    """The part `key` of errand's line, or none ( `text` None )."""
    with _lock:
        if text:
            _parts[ key ] = text
        else:
            _parts.pop( key, None )
    redraw()


def case_start( key, label: str, recent = None, poll = None, write = None, close = None, waiting = None ):
    """A case started: its line, until `case_end`. `recent( n )`: its last `n` lines, for Focus; `poll()`:
    its step now, asked twice a second, for a case nobody says it of. `write( bytes )` / `close()`: its
    input, for what is typed while it is in front; `waiting()`: whether it seems to wait for some."""
    with _lock:
        taken = { k[ "n" ] for k in _cases.values() }
        n = next( i for i in range( 1, len( _cases ) + 2 ) if i not in taken )     # kept while it runs: its key
        _cases[ key ] = { "label": label, "step": None, "since": time.time(), "recent": recent, "poll": poll,
                          "write": write, "close": close, "waiting": waiting, "n": n }
    _tick()
    redraw()


def case_step( key, text: str | None ):
    with _lock:
        if key in _cases:
            _cases[ key ][ "step" ] = text
    redraw()


def case_end( key ):
    global _focus
    with _lock:
        _cases.pop( key, None )
        if _focus == key:
            _focus = None
    redraw()


def focus( which ):
    """`which`: a case's number ( 1, 2, …, the one its line shows ), `"next"`, or None for none in front."""
    global _focus, _typed
    with _lock:
        _typed = b""
        keys = list( _cases )
        if which is None or not keys:
            _focus = None
        elif which == "next":
            _focus = keys[ ( keys.index( _focus ) + 1 ) % len( keys ) ] if _focus in keys else keys[ 0 ]
        elif isinstance( which, int ):
            _focus = next( ( k for k in keys if _cases[ k ].get( "n" ) == which ), _focus )
    redraw()


# ── the keys ─────────────────────────────────────────────────────────────────

_keys_on = False
_typed = b""                        # the line being typed for the case in front


def key( k: bytes ):
    """One key, as `keys` reads it. None in front: a digit or Tab chooses, Esc does nothing. A case in
    front that takes input: what is typed is its line, Enter sends it, Backspace takes back, Ctrl-D ends
    its input; Esc, and Tab, are still Focus's."""
    global _typed
    with _lock:
        front = _cases.get( _focus ) if _focus is not None else None
    if k == b"\x1b":
        return focus( None )
    if k == b"\t":
        return focus( "next" )
    if front is not None and front.get( "write" ):
        if k in ( b"\r", b"\n" ):
            line, _typed = _typed + b"\n", b""
            front[ "write" ]( line )
        elif k in ( b"\x7f", b"\x08" ):
            _typed = _typed[ : -1 ]
        elif k == b"\x04":
            _typed = b""
            if front.get( "close" ):
                front[ "close" ]()
        elif k >= b" ":
            _typed += k
        return redraw()
    if k.isdigit() and k != b"0":
        focus( int( k ) )


@contextlib.contextmanager
def keys( ):
    """While the block runs, the keys of Focus are read: only when both the keyboard and the screen are
    a terminal's. Ctrl-C stays what it is ( cbreak keeps signals )."""
    global _keys_on
    fd = None
    try:
        if os.name == "posix" and sys.stdin.isatty() and _usable():
            fd = sys.stdin.fileno()
    except ( AttributeError, ValueError, OSError ):
        fd = None
    if fd is None:
        yield
        return
    import select
    import termios
    import tty
    kept = termios.tcgetattr( fd )
    stop = threading.Event()

    def read():
        while not stop.is_set():
            ready, _, _ = select.select( [ fd ], [ ], [ ], 0.2 )
            if not ready:
                continue
            k = os.read( fd, 1 )
            if k == b"\x1b":                            # Esc alone; an arrow's sequence is let go
                more, _, _ = select.select( [ fd ], [ ], [ ], 0.05 )
                if more:
                    os.read( fd, 8 )
                    continue
            key( k )

    try:
        tty.setcbreak( fd )
        _keys_on = True
        t = threading.Thread( target = read, daemon = True )
        t.start()
        yield
    finally:
        stop.set()
        _keys_on = False
        termios.tcsetattr( fd, termios.TCSADRAIN, kept )


@contextlib.contextmanager
def feeding( write, close ):
    """The one case running reads what is typed here ( ADR 0016 ): the terminal as it is ( its echo, its
    line editing ), each line sent as it is entered, Ctrl-D the end of its input. Only when the keyboard
    is a terminal's."""
    fd = None
    try:
        if os.name == "posix" and sys.stdin.isatty() and _usable():
            fd = sys.stdin.fileno()
    except ( AttributeError, ValueError, OSError ):
        fd = None
    if fd is None:
        yield
        return
    import select
    stop = threading.Event()

    def read():
        while not stop.is_set():
            ready, _, _ = select.select( [ fd ], [ ], [ ], 0.2 )
            if not ready or stop.is_set():
                continue
            data = os.read( fd, 65536 )
            if not data:
                close()                     # Ctrl-D on an empty line
                return
            write( data )

    t = threading.Thread( target = read, daemon = True )
    t.start()
    try:
        yield
    finally:
        stop.set()


# ── errand's own work ────────────────────────────────────────────────────────

class Work:
    """What `working` hands back: set `numbers` to say what it came to."""

    def __init__( self, kind: str | None, text: str ):
        self.kind, self.text = kind, text
        self.numbers: dict = { }
        self.started = time.time()
        self.seconds = None

    @property
    def record( self ) -> dict:
        """Its event for a run's journal ( `steps.jsonl` )."""
        return { "t": self.started, **( { "transfer": self.kind } if self.kind else { } ),
                 "s": round( self.seconds or 0.0, 3 ), **self.numbers }


@contextlib.contextmanager
def working( text: str, kind: str | None = None, key: str = "work" ):
    """`text` at the bottom, with the time it takes, while the block runs; gone after. On the place line
    instead, while one is open ( `place.Place` ): where it goes is said there already."""
    from . import place
    w = Work( kind, text )
    line = place.current
    if line is not None:
        line.doing_now( re.split( r" [→←] ", text )[ 0 ] + "…" )
        try:
            yield w
        finally:
            w.seconds = time.time() - w.started
            line.doing_now( None )
            if w.kind:
                line.crossed( w.record )
        return
    done = threading.Event()

    def tick():
        while not done.wait( 0.5 ):
            put( key, f"{text} · {time.time() - w.started:.0f} s" )

    put( key, text )
    t = threading.Thread( target = tick, daemon = True )
    t.start()
    try:
        yield w
    finally:
        w.seconds = time.time() - w.started
        done.set()
        t.join()
        put( key, None )
