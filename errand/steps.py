"""Steps ( ADR 0010 ): a run says where it is, and errand shows it live.

    errand.step( f"iteration {i}", done = i / n, residual = r )     # text, fraction, curves
    errand.view( "convergence.html", content = html )                # a file of the run that evolves

Every call is a dated event, one JSON line of the run's journal, `$ERRAND_STEPS`
( `<leaf>/steps.jsonl`, set by `run_case` ):

    {"t": 1763220000.12, "text": "iteration 41", "done": 0.41, "residual": 3e-07}
    {"t": 1763220001.40, "view": "convergence.html"}
    {"t": 1763220002.10, "transfer": "pull", "s": 0.01, "files": 12, "bytes": 4145, ...}   errand's ( ADR 0016 )

A view is also said where it opens, `OUTPUT: file://...`: by the run itself when nobody drives it,
else by the side that drives it, once the file is brought back there ( `cli.views` ).

At most `RATE` writes per second: calls in between are merged and written at the next write, or at
exit. Without `$ERRAND_STEPS` ( a process errand did not start ) nothing is written and nothing raised.

A shell script gets the same calls with `eval "$ERRAND_STEPS_SH"`:

    step "iteration 41" done=0.41 residual=3e-7
    view convergence.html

Imported by `errand` itself: standard library only, and cheap.
"""
from __future__ import annotations

import atexit
import json
import os
import threading
import time
from pathlib import Path

ENV    = "ERRAND_STEPS"
RELAY  = "ERRAND_RELAY"     # set on a run whose session is followed ( `downloads.RELAY` ): it says its views
SH_ENV = "ERRAND_STEPS_SH"
FILE   = "steps.jsonl"
RATE   = 0.1               # seconds between two writes, at least
EDGE   = 1 << 16           # bytes read at each end of a journal for a summary
POINTS = 60                # points of a curve kept in a summary
KEYS   = ( "t", "text", "done", "view", "title", "want" )   # what is not a curve ( `want`: `downloads` )
# An event with `transfer` is errand's ( ADR 0016 ): a push or a pull, its numbers; never a curve.

# The same calls in POSIX sh. The first argument is the text unless it reads `name=value`.
SHELL_STEPS = r'''
step() {
    [ -n "$ERRAND_STEPS" ] || return 0
    errand_line="{\"t\": $( date +%s )"
    if [ $# -gt 0 ] && { [ "${1%%=*}" = "$1" ] || [ -n "$( printf '%s' "${1%%=*}" | tr -d 'A-Za-z0-9_' )" ]; }; then
        errand_line="$errand_line, \"text\": \"$( printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' )\""
        shift
    fi
    for errand_kv in "$@"; do
        errand_line="$errand_line, \"${errand_kv%%=*}\": ${errand_kv#*=}"
    done
    printf '%s}\n' "$errand_line" >> "$ERRAND_STEPS" 2>/dev/null
    return 0
}
view() {
    [ -n "$ERRAND_STEPS" ] || return 0
    printf '{"t": %s, "view": "%s"}\n' "$( date +%s )" "$1" >> "$ERRAND_STEPS" 2>/dev/null
    if [ -z "$ERRAND_RELAY" ]; then
        case "$1" in /*) errand_v="$1" ;; *) errand_v="$( dirname "$ERRAND_STEPS" )/$1" ;; esac
        case "|$errand_views|" in *"|$errand_v|"*) ;; *)       # once per file
            errand_views="$errand_views|$errand_v"; printf 'OUTPUT: file://%s\n' "$errand_v" ;; esac
    fi
    return 0
}
download() {
    PYTHONPATH="$ERRAND_SRC${PYTHONPATH:+:$PYTHONPATH}" "$ERRAND_PYTHON" -m errand download "$@"
}
require() {
    [ -n "$ERRAND_CLAIM_FILE" ] || return 0
    errand_set=$( PYTHONPATH="$ERRAND_SRC${PYTHONPATH:+:$PYTHONPATH}" "$ERRAND_PYTHON" -m errand require "$@" )
    errand_rc=$?
    [ "$errand_rc" -eq 75 ] && exit 75
    [ "$errand_rc" -eq 0 ] || return "$errand_rc"
    for errand_kv in $errand_set; do export "$errand_kv"; done
    return 0
}
'''


# ── writing ──────────────────────────────────────────────────────────────────

class _Journal:
    """The journal of the current run: calls merged between two writes."""

    def __init__( self, path: str ):
        self.path    = path
        self.pending = { }
        self.written = 0.0
        self.lock    = threading.Lock()

    def add( self, event: dict, now = False ):
        with self.lock:
            self.pending.update( event )
            self.pending[ "t" ] = time.time()
            if now or self.pending[ "t" ] - self.written >= RATE:
                self._write()

    def flush( self ):
        with self.lock:
            self._write()

    def _write( self ):
        if not self.pending:
            return
        line = json.dumps( self.pending ) + "\n"
        self.pending = { }
        self.written = time.time()
        try:
            with open( self.path, "a" ) as f:          # one line, one write: several writers can share it
                f.write( line )
        except OSError:
            pass                                        # a run must not fail over its steps
        nudge()


_rung = [ 0.0 ]
NUDGE = 1.0                   # seconds between two rings of the agents' bell by a run, at most


def nudge( ):
    """The agents of this machine told something of a run changed ( a step, a view, the run noted: ADR 0024 ), at most
    every `NUDGE` seconds: their watchers look now. A courtesy: never the run's failure."""
    now = time.time()
    if now - _rung[ 0 ] < NUDGE:
        return
    _rung[ 0 ] = now
    try:
        from .agents import look
        look.ring()
    except Exception:
        pass


_journal: _Journal | None = None


def _current() -> _Journal | None:
    """The journal `$ERRAND_STEPS` names now: it changes from one case to the next."""
    global _journal
    path = os.environ.get( ENV )
    if not path:
        return None
    if _journal is None or _journal.path != path:
        if _journal is not None:
            _journal.flush()
        _journal = _Journal( path )
    return _journal


@atexit.register
def flush():
    """Write what is merged and not written yet. At exit, and at the end of each case."""
    if _journal is not None:
        _journal.flush()


def step( text: str | None = None, *, done: float | None = None, **values ):
    """Where the run is: `text` as a person reads it, `done` a fraction from 0 to 1, and named
    numbers, one curve each. Everything is optional; the text stays until another one is given."""
    event = { k: float( v ) for k, v in values.items() }     # a curve is made of numbers
    if text is not None:
        event[ "text" ] = str( text )
    if done is not None:
        event[ "done" ] = float( done )
    journal = _current()
    if journal is not None and event:
        journal.add( event )


_announced: set = set()          # the views this process said itself, once each


class Static:
    """What opens a view that is a directory carrying its own page ( ADR 0017 §5 ): `errand.view( "foam.sviz", open =
    errand.Static( "index.html" ) )`. Its files are served as they are, from the copy brought back here, on a server
    of errand's beside its page ( `web.static` ): nothing runs here, and the page is the one written with the data."""

    def __init__( self, index: str = "index.html" ):
        self.index = str( index )

    def wire( self ) -> dict:
        return { "static": self.index }

    def __repr__( self ):
        return f"errand.Static( {self.index!r} )"


def view( path, title: str | None = None, content: str | bytes | None = None, last = None, open = None ) -> bool:
    """`path` ( relative to the run's directory ) is a file of the run worth looking at as it
    evolves. With `content`, errand writes it, atomically: a reader never sees half of it.

    `path` may be a DIRECTORY ( a scene store, ADR 0017 ): named again, what changed in it comes back to the side
    that drives the run. `last`: a file of it ( or several ) that comes after the rest, read over there BEFORE the
    rest is listed -- an index that names the other files ( `manifest.json` ) never names one not here yet.
    `open`: what opens it ( `Static`, or a list, the first by default ): said by the producer, nothing to declare.

    -> whether errand says where to open it ( `OUTPUT: file://...`, once per file ): the side that
    drives a run elsewhere brings the file back at once and says its path there ( `cli.views` ); a run
    nobody drives says its own. False outside errand: the caller says it, if it wants to."""
    journal = _current()
    target = Path( path )
    if not target.is_absolute() and journal is not None:
        target = Path( journal.path ).parent / target
    if content is not None:
        tmp = target.with_name( f".{target.name}.tmp" )
        tmp.parent.mkdir( parents = True, exist_ok = True )
        if isinstance( content, bytes ):
            tmp.write_bytes( content )
        else:
            tmp.write_text( content )
        tmp.replace( target )
    if journal is None:
        return False
    last = [ last ] if isinstance( last, str ) else list( last or ( ) )
    opens = [ o.wire() if hasattr( o, "wire" ) else o for o in ( open if isinstance( open, ( list, tuple ) ) else [ open ] if open else [ ] ) ]
    journal.add( { "view": str( path ), **( { "title": title } if title else { } ), **( { "last": last } if last else { } ),
                   **( { "open": opens } if opens else { } ) }, now = True )
    if not os.environ.get( RELAY ) and str( target ) not in _announced:
        _announced.add( str( target ) )
        print( f"OUTPUT: { target.absolute().as_uri() }", flush = True )
    return True


# ── reading ──────────────────────────────────────────────────────────────────

def read( path, edge = EDGE ) -> list:
    """The events of a journal: all of it when small, its first and last `edge` bytes otherwise
    ( the views are said early, the state late ). Lines that are not JSON are skipped."""
    try:
        with open( path, "rb" ) as f:
            size = f.seek( 0, 2 )
            f.seek( 0 )
            if size <= 2 * edge:
                chunks = [ f.read() ]
            else:
                head = f.read( edge ).rsplit( b"\n", 1 )[ 0 ]
                f.seek( size - edge )
                chunks = [ head, f.read().split( b"\n", 1 )[ -1 ] ]
    except OSError:
        return [ ]
    return parse( b"\n".join( chunks ) )


def parse( data ) -> list:
    """The events in a piece of journal ( bytes or text ); lines that are not JSON are skipped."""
    events = [ ]
    for line in data.splitlines():
        try:
            e = json.loads( line )
        except ValueError:
            continue
        if isinstance( e, dict ):
            events.append( e )
    return events


def summary( path ) -> dict | None:
    """What a watcher shows of a journal, small enough to send every 2 s:
    { t, first, text, done, eta, curves: { name: [ last POINTS values ] }, views: [ { view, title } ] }."""
    return summarize( read( path ) )


def summarize( events: list ) -> dict | None:
    # What crossed to get the run there and back ( `transfer`, ADR 0016 ) is errand's, not the run's steps.
    events = [ e for e in events if "transfer" not in e ]
    if not events:
        return None
    out = { "t": events[ -1 ].get( "t" ), "first": events[ 0 ].get( "t" ), "text": None, "done": None,
            "eta": None, "curves": { }, "views": [ ] }
    dones = [ ]
    for e in events:
        if e.get( "text" ) is not None:
            out[ "text" ] = e[ "text" ]
        if e.get( "done" ) is not None:
            out[ "done" ] = e[ "done" ]
            dones.append( ( e.get( "t" ) or 0, e[ "done" ] ) )
        if e.get( "view" ) and not any( v[ "view" ] == e[ "view" ] for v in out[ "views" ] ):
            out[ "views" ].append( { "view": e[ "view" ], "title": e.get( "title" ), **( { "open": e[ "open" ] } if e.get( "open" ) else { } ) } )
        for k, v in e.items():
            if k not in KEYS and isinstance( v, ( int, float ) ):
                out[ "curves" ].setdefault( k, [ ] ).append( v )
    out[ "curves" ] = { k: v[ -POINTS : ] for k, v in out[ "curves" ].items() }
    if len( dones ) > 1:
        ( t0, d0 ), ( t1, d1 ) = dones[ 0 ], dones[ -1 ]
        if d1 > d0 and t1 > t0 and d1 < 1:
            out[ "eta" ] = ( 1 - d1 ) * ( t1 - t0 ) / ( d1 - d0 )
    return out


# ── saying it ────────────────────────────────────────────────────────────────

def bar( done: float, width = 10 ) -> str:
    """`▕████▌     ▏`: `done` in eighths of a cell."""
    eighths = round( max( 0.0, min( 1.0, done ) ) * width * 8 )
    full, part = divmod( eighths, 8 )
    cells = "█" * full + ( " ▏▎▍▌▋▊▉"[ part ] if full < width else "" )
    return f"▕{cells:<{width}}▏"


def spark( values ) -> str:
    """`▁▂▃▅▇`, on a log scale when the values are positive and span more than two decades."""
    import math
    values = [ v for v in values if isinstance( v, ( int, float ) ) and math.isfinite( v ) ]
    if not values:
        return ""
    lo, hi = min( values ), max( values )
    if lo > 0 and hi / lo > 100:
        values, lo, hi = [ math.log10( v ) for v in values ], math.log10( lo ), math.log10( hi )
    if hi == lo:
        return "▄" * len( values )
    return "".join( "▁▂▃▄▅▆▇█"[ min( 7, int( ( v - lo ) / ( hi - lo ) * 8 ) ) ] for v in values )


def number( v ) -> str:
    return f"{v:.3g}" if isinstance( v, float ) else str( v )


def trend( values ) -> str:
    if len( values ) < 2 or values[ -1 ] == values[ -2 ]:
        return ""
    return "↘" if values[ -1 ] < values[ -2 ] else "↗"


def duration( s: float ) -> str:
    s = int( max( 0, s ) )
    return f"{s} s" if s < 90 else f"{s // 60} min" if s < 5400 else f"{s // 3600} h {s % 3600 // 60:02d}"


def line( s: dict | None, width = 10 ) -> str:
    """One line for a person: `iteration 41 · ▕████▌     ▏ 41 % · 2 min left · residual 3e-07 ↘`."""
    if not s:
        return ""
    said = [ s[ "text" ] ] if s.get( "text" ) else [ ]
    if s.get( "done" ) is not None:
        said.append( f"{bar( s[ 'done' ], width )} {int( 100 * s[ 'done' ] )} %" )
    if s.get( "eta" ) is not None:
        said.append( f"{duration( s[ 'eta' ] )} left" )
    for k, v in ( s.get( "curves" ) or { } ).items():
        said.append( f"{k} {number( v[ -1 ] )} {trend( v )}".rstrip() )
    return " · ".join( said )
