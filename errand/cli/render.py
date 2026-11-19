"""What `errand run` draws ( ADR 0016 ): each case under a header, its output behind a gutter, its end on
one line -- here, on the side that drives, whatever ran the case.

    ▸ solve  exp_demo.py:5 · n=3
    │ it 0 residual 1.0e+00                 stdout, behind a dim bar, under the case's `▸`
    ┃ warning: slow convergence             stderr, behind an amber one
    │ adjust      it=230 loss 0.0035        a row ( `errand.row`, `rows` ): its pieces aligned with the rows before
    ╰ PASS solve  2.1 s · residual 0.001

The gutter is colored, never the text: the program's own colors are kept, and carried over the gutter
when a line starts inside one. Three modes ( `mode()` ): `bar` ( the default ), `spaces`, `off`;
`plain` is `off` without colors ( `--plain` ). Off a terminal there are no colors, and the gutter stays.

A session's lines arrive as events ( `agents.ops`: `banner`, `head`, `tail`, `ran`, `note` ) among its
bytes, in the order they were said: a `Renderer` is fed both, in that order, by whoever reads the
stream ( `sessions.Marked` ), or by the case itself when it runs in this process ( `here.run_case` ).
"""
from __future__ import annotations

import codecs
import os
import re
import shutil
import sys
import threading
import time

from .. import rows

MODES = ( "bar", "spaces", "off", "plain" )
ENV   = "ERRAND_OUTPUT"

BOLD, DIM, GREEN, RED, YELLOW, CYAN, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[0m" )
MAGENTA = "\033[35m"
ROW = "\033[38;5;75m"          # the head of a row ( `errand.row` ): the step, in a sky blue
PLACE = BOLD + MAGENTA          # where the cases run ( `place` ): not the cases' colour
INSET = "  "                    # a case under its place

_SGR  = re.compile( r"\x1b\[[0-9;]*m" )
_lock = threading.RLock()          # one terminal: every renderer draws whole pieces


def mode( ) -> str:
    """`$ERRAND_OUTPUT`, else `configure( output = … )`, else `bar`."""
    got = os.environ.get( ENV )
    if not got:
        try:
            from .. import config
            got = getattr( config.settings, "output", None )
        except Exception:
            got = None
    return got if got in MODES else "bar"


COLOR = "ERRAND_COLOR"       # "1": colors though not on a terminal ( a child of `-j`, whose parent is one )


def colors_on( stream ) -> bool:
    if mode() == "plain" or os.environ.get( "NO_COLOR" ):
        return False
    if os.environ.get( COLOR ) == "1":
        return True
    try:
        return stream.isatty() and os.environ.get( "TERM", "dumb" ) != "dumb"
    except ( AttributeError, ValueError ):
        return False


FORCED = ( "FORCE_COLOR", "CLICOLOR_FORCE" )


def forced_colors( ) -> dict:
    """What a case run elsewhere is told so that it colors what it writes, as it would on this terminal
    ( ADR 0016 ): only when this terminal shows colors, and never against `NO_COLOR` or a value already
    chosen in the environment."""
    if not colors_on( sys.stdout ) or os.environ.get( "NO_COLOR" ) or any( k in os.environ for k in FORCED ):
        return { }
    return { k: "1" for k in FORCED }


def duration( s ) -> str:
    if s is None:
        return ""
    if s < 1:
        return f"{s * 1000:.0f} ms"
    if s < 60:
        return f"{s:.1f} s"
    m, s = divmod( int( s ), 60 )
    return f"{m} min {s:02d} s" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def short( v ) -> str | None:
    """A result as the end line shows it, or None when it does not fit there."""
    if isinstance( v, bool ) or v is None:
        return str( v ).lower() if isinstance( v, bool ) else None
    if isinstance( v, int ):
        return str( v )
    if isinstance( v, float ):
        return f"{v:.4g}"
    if isinstance( v, str ) and len( v ) <= 24 and "\n" not in v:
        return v
    return None


def results_line( results: dict | None, most = 4 ) -> str:
    shown = [ f"{k} {s}" for k, v in ( results or { } ).items() if ( s := short( v ) ) is not None ]
    return " · ".join( shown[ : most ] ) + ( " · …" if len( shown ) > most else "" )


def recent_lines( text: str, n: int ) -> list:
    """The last `n` lines of `text` as a terminal leaves them: after its last `\r`, each."""
    out = [ l.rsplit( "\r", 1 )[ -1 ] for l in text.replace( "\r\n", "\n" ).split( "\n" ) ]
    while out and not out[ -1 ].strip():
        out.pop()
    return out[ -n : ]


class _Stream:
    """One of the two streams: where it goes, whether a line is open, the program's color in force."""

    def __init__( self, stream, err: bool ):
        self.stream  = stream
        self.err     = err
        self.decoder = codecs.getincrementaldecoder( "utf-8" )( errors = "replace" )
        self.at_start = True
        self.sgr     = ""                    # the program's last color, carried over the gutter
        self.rowbuf  = ""                    # a row ( `rows` ) begun and not ended in what came so far

    def write( self, text: str ):
        try:
            self.stream.write( text )
            self.stream.flush()
        except ( OSError, ValueError ):
            pass


class Renderer:
    """Draws one source of cases ( a session, or this process ) on this terminal."""

    def __init__( self, out = None, err = None ):
        self.out_ = _Stream( out or sys.stdout, False )
        self.err_ = _Stream( err or sys.stderr, True )
        self.mode = mode()
        self.color = colors_on( self.out_.stream )
        self.in_case = False
        self.head_seen = False
        self.env = None                     # the environment of its cases ( `banner` ), said after each name
        # Under the case's last line, while it runs and says nothing: how long it has run, its step
        # ( `steps` ), whether it seems to wait for input -- erased by whatever it writes next.
        self.since = None
        self.step = None
        self.shown = False
        self.eol = True                     # the last thing written ended its line
        self._ticking = False
        # `-j` ( ADR 0016 ): a case is drawn as one block when it ends -- its header, everything its
        # source wrote meanwhile, whoever wrote it, then its end line -- never interleaved with another's.
        self.blocks = False
        self.last_write = 0.0
        self._held: list = [ ]             # ( stream, text ) of the case under way, in the order they came
        # The rows of the case ( `errand.row` ): their columns, and those on the terminal, at which line
        # of it, to draw them again when a column grows. Lines counted as the terminal shows them.
        self.table = rows.Table()
        self.drawn: list = [ ]             # ( line, head, groups, gutter )
        self.line, self.col = 0, 0

    # -- pieces --------------------------------------------------------------

    def _c( self, code: str, text: str ) -> str:
        return f"{code}{text}{RESET}" if self.color else text

    def gutter( self, err: bool ) -> str:
        if self.mode in ( "off", "plain" ):
            return ""
        if self.mode == "spaces":
            return INSET + "  "
        color = colors_on( ( self.err_ if err else self.out_ ).stream )
        bar = "┃" if err else "│"
        return f"{INSET}{YELLOW if err else DIM}{bar}{RESET} " if color else f"{INSET}{bar} "

    def _put( self, s: _Stream, text: str ):
        """`text` to `s`, or held with the case's block."""
        if self.blocks and self.in_case:
            self._held.append( ( s, text ) )
        else:
            self._unshow()
            s.write( text )
            self._count( text )

    def _count( self, text: str ):
        """The lines of the terminal `text` takes, a long line wrapped: where the rows drawn are."""
        width = shutil.get_terminal_size( ( 100, 24 ) ).columns
        for i, seg in enumerate( text.split( "\n" ) ):
            if i:
                self.line += 1 + max( 0, self.col - 1 ) // width
                self.col = 0
            if "\r" in seg:
                self.col = max( self.col, rows.visible( seg.rpartition( "\r" )[ 2 ] ) )
            else:
                self.col += rows.visible( seg )

    def _row( self, head: str, groups, gutter: str ) -> str:
        return gutter + self.table.draw( head, groups, ROW if self.color else "" )

    def _redraw( self ):
        """The rows of the case drawn before, at the widths known now, where they are on the terminal --
        those it still shows, on one line each."""
        if not ( self.out_.at_start and self.err_.at_start ):
            return
        size = shutil.get_terminal_size( ( 100, 24 ) )
        self._unshow()
        for line, head, groups, gutter in self.drawn:
            up, text = self.line - line, self._row( head, groups, gutter )
            if 0 < up < size.lines and rows.visible( text ) < size.columns:
                self.out_.write( f"\x1b[{up}A\r\x1b[K{text}\x1b[{up}B\r" )

    # -- how long it has run, under it -----------------------------------------

    def _live( self ) -> bool:
        if self.mode not in ( "bar", "spaces" ) or self.blocks:
            return False
        try:
            return self.out_.stream.isatty() and os.environ.get( "TERM", "dumb" ) != "dumb"
        except ( AttributeError, ValueError ):
            return False

    def _unshow( self ):
        if self.shown:
            self.shown = False
            self.out_.write( "\r\x1b[K" )

    def status( self ) -> str:
        took = int( time.time() - ( self.since or time.time() ) )
        bits = [ f"{took} s" if took < 60 else f"{took // 60} min {took % 60:02d} s" ]
        if self.step:
            bits.append( self.step )
        return f"{INSET}┆ " + " · ".join( bits )

    def set_step( self, text: str | None ):
        """The case's step now ( `steps`, ADR 0010 ), said under it with its time."""
        self.step = text

    def _tick( self ):
        while True:
            time.sleep( 0.5 )
            with _lock:
                if not self.in_case:
                    self._ticking = False
                    return
                quiet = time.time() - max( self.last_write, self.since or 0 ) > 1.0
                if quiet and self.eol and self.out_.at_start and self.err_.at_start:
                    text = self.status()
                    if self.waiting( 2.0 ):
                        text += " · ⌨ waits for input?"
                    width = shutil.get_terminal_size( ( 100, 24 ) ).columns
                    self.out_.write( "\r\x1b[K" + self._c( DIM, text[ : width - 1 ] ) )
                    self.shown = True

    def closing( self, blank = False ) -> str:
        """Before a case's end line: its gutter closed ( `╰` ), at the column of its output -- the eye
        runs down one column and finds every end ( ADR 0016 ). `blank`: the lines under it."""
        if self.mode in ( "off", "plain" ):
            return ""
        if self.mode == "spaces" or blank:
            return INSET + "  "
        return f"{INSET}{DIM}╰{RESET} " if self.color else f"{INSET}╰ "

    def _line( self, text: str ):
        """A line of errand's, on stdout, on a line of its own."""
        self.eol = True
        with _lock:
            for s in ( self.out_, self.err_ ):
                if not s.at_start:
                    self._put( s, ( RESET if s.sgr and colors_on( s.stream ) else "" ) + "\n" )
                    s.at_start = True
            self._put( self.out_, text + "\n" )

    def typed( self, data: bytes, echoed: bool ):
        """A line typed here for the case ( ADR 0016 ). `echoed`: the terminal showed it and ended the line
        itself; else it goes in the case's output, as a terminal would have shown it ( under Focus )."""
        if echoed:
            with _lock:
                self.out_.at_start = self.err_.at_start = True
        else:
            self.write( data )

    def waiting( self, after: float = 2.0 ) -> bool:
        """It wrote a line it did not end, then nothing for `after` seconds: maybe a question ( ADR 0016 ).
        A hint, never a decision."""
        return self.in_case and not self.out_.at_start and time.time() - self.last_write > after

    def recent( self, n: int ) -> list:
        """The last `n` lines of the block held ( `-j` ), as they will be drawn: what Focus shows live
        ( `bottom` ). A bar redrawn in place shows its last state."""
        with _lock:
            text = "".join( self._row( *t ) if isinstance( t, tuple ) else t for _, t in self._held )
        return recent_lines( text, n )

    def _release( self ):
        """The case's block, at once, under the terminal's lock."""
        with _lock:
            self._unshow()
            held, self._held = self._held, [ ]
            for s, text in held:
                if isinstance( text, tuple ):                  # a row: at the widths of the whole case
                    text = self._row( *text )
                s.write( text )
                self._count( text )

    # -- what a case's source says -------------------------------------------

    def banner( self, n: int, env: str, place: str ):
        """Where the cases run: said once by the place line when they were sent there ( `place.Place` ),
        else here, `▸ host`. The env goes with each case ( `head` ); the count when there are several."""
        from . import place as P
        self.env = env
        what = f"{n} entr{'y' if n == 1 else 'ies'}"
        jobs = place.split( "  ", 1 )[ 1 ] if "  " in place else ""          # `  -j 4`
        if P.drawn:
            if n > 1 or jobs:
                self._line( self._c( DIM, f"{INSET}{what}" + ( f" · {jobs.strip()}" if jobs else "" ) ) )
            return
        host = place.split( "  ", 1 )[ 0 ].rpartition( "@" )[ 2 ] or place
        self._line( "\n" + self._c( PLACE, f"▸ {host}" )
                    + ( self._c( DIM, f"  {what}" + ( f" · {jobs.strip()}" if jobs else "" ) ) if n > 1 or jobs else "" ) )

    def head( self, name: str, site: str, params: dict | None = None, gpus = None ):
        """`▸ solve (lmo-torch · gpu 0)  s.py:3 · n=3`: its name, where it runs and on which cards, its values."""
        told = " · ".join( f"{k}={v}" for k, v in ( params or { } ).items() )
        self.in_case = True                   # first: under `-j` the header opens the held block
        self.head_seen = True
        where = [ self.env ] if self.env else [ ]
        if gpus:
            where.append( f"gpu{'s' if len( gpus ) > 1 else ''} {','.join( str( g ) for g in gpus )}" )
        env = f" ({' · '.join( where )})" if where else ""
        self.since, self.step = time.time(), None
        self.table, self.drawn = rows.Table(), [ ]
        if self._live() and not self._ticking:
            self._ticking = True
            threading.Thread( target = self._tick, daemon = True ).start()
        self._line( INSET + self._c( BOLD + CYAN, f"▸ {name}" ) + self._c( DIM, env ) + "  "
                    + self._c( DIM, site + ( f" · {told}" if told else "" ) ) )

    def tail( self, status: str, name: str, site: str = "", *, error = None, seconds = None, results = None,
              output = None ):
        """`PASS solve  2.1 s · residual 0.001`, `FAIL broken  0.1 s  ValueError: …` and where its output is."""
        for s in ( self.out_, self.err_ ):                    # a row the case did not end
            if s.rowbuf:
                rest, s.rowbuf = s.rowbuf, ""
                self._text( s, rest, final = True )
        word = { "PASS": self._c( GREEN, "PASS" ), "SKIP": self._c( YELLOW, "SKIP" ) }.get( status, self._c( RED, status ) )
        where = f"  {self._c( DIM, site )}" if site and not self.head_seen else ""
        facts = " · ".join( b for b in ( duration( seconds ), results_line( results ) if status == "PASS" else "" ) if b )
        line = f"{word} {name}{where}" + ( f"  {self._c( DIM, facts )}" if facts else "" ) + ( f"  {error}" if error else "" )
        self._line( self.closing() + line )
        if output and status not in ( "PASS", "SKIP" ):
            self._line( self.closing( blank = True ) + self._c( DIM, f"↳ {output}" ) )
        self.in_case = False
        self.head_seen = False
        self._release()

    def note( self, text: str, kind: str = "dim" ):
        """What errand says between cases ( a wait for room, a group of values ): under the place, as the
        place's notes are ( `┆` ); a group's heading at the cases' level."""
        code = { "dim": DIM, "warn": YELLOW, "bad": RED, "head": BOLD + CYAN }.get( kind, "" )
        if kind == "head":
            return self._line( "\n" + INSET + ( self._c( code, text ) if code else text ) )
        self._line( INSET + self._c( DIM, "┆ " ) + ( self._c( code, text ) if code else text ) )

    def aside( self, text: str ):
        """A line about a case that may come after its end ( a view brought back, `views.Views` ):
        indented, on a line of its own."""
        self._line( INSET + "  " + text )

    def view( self, link: str ):
        """A file of the case to open ( `errand.view` ), its link behind a `↗`: inside the case, behind its
        gutter, while it runs; on a line of its own after. `OUTPUT: link` when the output is plain: what
        reads it finds it as the run says it."""
        if self.mode in ( "off", "plain" ):
            return self._line( f"OUTPUT: {link}" )
        arrow = self._c( CYAN, "↗" ) + " " + link
        if not self.in_case:
            return self._line( INSET + "  " + arrow )
        with _lock:
            for s in ( self.out_, self.err_ ):
                if not s.at_start:
                    self._put( s, ( RESET if s.sgr and colors_on( s.stream ) else "" ) + "\n" )
                    s.at_start = True
            self._put( self.out_, self.gutter( False ) + arrow + "\n" )

    def write( self, data, err: bool = False ):
        """Bytes or text the case wrote: behind the gutter inside a case, as they are outside one."""
        s = self.err_ if err else self.out_
        text = s.decoder.decode( data ) if isinstance( data, ( bytes, bytearray ) ) else data
        if text:
            self._text( s, text )

    def _text( self, s: _Stream, text: str, final = False ):
        err = s.err
        self.last_write = time.time()
        with _lock:
            text, s.rowbuf = s.rowbuf + text, ""
            if not final:                                      # a row is drawn whole: wait for its line's end
                begun = text.rfind( rows.MARK )
                if begun >= 0 and "\n" not in text[ begun : ]:
                    text, s.rowbuf = text[ : begun ], text[ begun : ]
                else:
                    for k in range( len( rows.MARK ) - 1, 0, -1 ):
                        if text.endswith( rows.MARK[ : k ] ):
                            text, s.rowbuf = text[ : -k ], text[ -k : ]
                            break
                if not text:
                    return
            if not self.in_case or self.mode in ( "off", "plain" ):
                text = self._plain_rows( text )
                self._put( s, text )
                s.at_start = text.endswith( ( "\n", "\r" ) )
                return
            g = self.gutter( err )
            out, grew = [ ], False
            for piece in re.split( r"(\r\n|\n|\r)", text ):
                if not piece:
                    continue
                if piece in ( "\n", "\r\n", "\r" ):
                    self.eol = piece != "\r"
                    if s.at_start and piece != "\r":
                        out.append( g.rstrip() )          # an empty line keeps the column of its block
                    out.append( ( RESET if s.sgr and colors_on( s.stream ) else "" ) + piece )
                    s.at_start = True
                    continue
                self.eol = False
                if s.at_start and ( got := rows.parse( piece ) ):
                    head, groups = got
                    grew = self.table.add( head, groups ) or grew
                    if out:
                        self._put( s, "".join( out ) )
                        out = [ ]
                    if self.blocks:
                        self._put( s, ( head, groups, g + s.sgr ) )
                    else:
                        self.drawn.append( ( self.line, head, groups, g + s.sgr ) )
                        self._put( s, self._row( head, groups, g + s.sgr ) )
                    s.at_start = False
                    continue
                if s.at_start:
                    out.append( g + s.sgr )
                    s.at_start = False
                    if piece.startswith( "OUTPUT: " ) and not err:      # a view the case said itself ( `errand.view` )
                        piece = self._c( CYAN, "↗" ) + " " + piece[ len( "OUTPUT: " ) : ]
                out.append( piece )
                for m in _SGR.finditer( piece ):
                    s.sgr = "" if m.group() in ( "\x1b[0m", "\x1b[m" ) else s.sgr + m.group()
            if out:
                self._put( s, "".join( out ) )
            if grew and self._live():
                self._redraw()

    def _plain_rows( self, text: str ) -> str:
        """The rows of `text` aligned on those before, without colour, never drawn again: off a case, or
        when nothing is drawn around the output ( `off`, `plain` )."""
        if rows.MARK not in text:
            return text
        lines = text.split( "\n" )
        for i, l in enumerate( lines ):
            if got := rows.parse( l ):
                if self.in_case:
                    self.table.add( *got )
                    lines[ i ] = self.table.draw( *got )
                else:
                    lines[ i ] = l.partition( rows.END )[ 2 ]
        return "\n".join( lines )

    def mark( self, m: dict ) -> bool:
        """An event of a session, drawn. -> whether it was one to draw."""
        op = m.get( "op" )
        if op == "banner":
            self.banner( m[ "n" ], m[ "env" ], m[ "place" ] )
        elif op == "head":
            self.head( m[ "name" ], m[ "site" ], m.get( "params" ), gpus = m.get( "gpus" ) )
        elif op == "ran" and "status" in m:
            e = m.get( "entry" ) or { }
            t = m.get( "tail" ) or { }
            self.tail( m[ "status" ], e.get( "name", "?" ), f"{os.path.basename( e.get( 'file', '' ) )}:{e.get( 'line', '' )}",
                       error = m.get( "error" ), seconds = t.get( "seconds" ), results = t.get( "results" ),
                       output = t.get( "output" ) )
        elif op == "note":
            self.note( m[ "text" ], m.get( "kind", "dim" ) )
        else:
            return False
        return True
