"""`errand --tui`: a screen for choosing what to run, and watching it happen.

Drawn with the curses of the standard library, so errand still installs with
nothing at all. Everything that is not drawing is in `session.py`, which has no
screen in it and is tested without a terminal.

**There is no focus to manage.** One pane is active, the arrows drive it, tab
goes to the next, and clicking a pane makes it the active one. The wheel
scrolls whatever is under the pointer and changes nothing else -- which is what
a wheel is for.

    ╭─ cases ──────────────────╮╭─ files ──────────────────────╮
    │ ▾ bench_solver.py        ││   shape.svg         12.1 kB  │
    │   [x] solve              ││   result.yaml          512 B │
    │   [ ] gradient           ││   output.txt         1.2 kB  │
    ╰──────────────────────────╯╰──────────────────────────────╯
    ╭─ runs ───────────────────╮╭─ output.txt ─────────────────╮
    │ ▾ errand bench_solver    ││ iteration 41  residual 3e-07 │
    │   ok   solve  n=1000     ││ iteration 42  residual 2e-07 │
    │   ..   solve  n=5000     ││                              │
    ╰──────────────────────────╯╰──────────────────────────────╯

**Runs and history are one list**, because they are one thing: a command, and
what it produced. Today's is at the top and still moving, yesterday's is three
rows down, and both read the same way -- since both are read out of the output
tree rather than remembered.

**Enter on a case asks the only question left** -- where, with which tags, with
which parameters. Not *which case*: that was the list enter was pressed in.
"""
from __future__ import annotations

import curses
import os
import time
from pathlib import Path

from . import session as S
from .session import Session

LOOK  = 0.5          # seconds between askings of the output tree
WHEEL = 3            # rows per notch

# ncurses reports the wheel as buttons 4 and 5; the constant for the second is
# missing from some builds of the module.
WHEEL_UP   = curses.BUTTON4_PRESSED
WHEEL_DOWN = getattr( curses, "BUTTON5_PRESSED", 0x200000 )

# A press is an intention; a RELEASE is the end of one, and acting on both
# would do everything twice -- and, worse, would make the release of a wheel
# notch land as a click wherever the pointer happened to be.
PRESSED = ( curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED
            | curses.BUTTON1_DOUBLE_CLICKED | curses.BUTTON1_TRIPLE_CLICKED )

C_TITLE, C_ACTIVE, C_DIM, C_OK, C_BAD, C_WARN = 1, 2, 3, 4, 5, 6

# Set when something is READING the screen rather than looking at it: every
# frame is then painted in full, instead of ncurses sending only the cells that
# changed. A test that had to reconstruct which those were would be testing its
# own reconstruction.
REPAINT = bool( os.environ.get( "ERRAND_TUI_REPAINT" ) )
# Every key and every mouse report, appended to a file. Not a feature: a way
# of answering "did that even arrive" without guessing, which is the only
# question worth asking when a screen does not react.
TRACE = os.environ.get( "ERRAND_TUI_TRACE" )


BOX = "╭╮╰╯─│"


def short( path, root ):
    try:
        return str( Path( path ).relative_to( root ) )
    except ValueError:
        return str( path )


def size_of( path ):
    try:
        n = float( path.stat().st_size )
    except OSError:
        return "-"
    for unit in ( "B", "kB", "MB", "GB" ):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _id( entry ):
    """An entry told apart from every other: two may share a name."""
    return ( str( entry.file ), entry.line, entry.name )


# ── rows and panes ───────────────────────────────────────────────────────────

class Row:
    __slots__ = ( "label", "detail", "kind", "data", "depth", "checked", "mark", "open" )

    def __init__( self, label, detail = "", *, kind = "plain", data = None, depth = 0,
                  checked = None, mark = None, open = None ):
        self.label, self.detail, self.kind, self.data = label, detail, kind, data
        self.depth   = depth
        self.checked = checked      # None: not something that can be ticked
        self.mark    = mark         # what stands where the box would be
        self.open    = open         # None: not something that can be folded


class Pane:
    """A titled box of rows, with its own cursor and its own scroll."""

    def __init__( self, name, title ):
        self.name, self.title = name, title
        self.rows   : list = [ ]
        self.cursor = 0
        self.top    = 0
        self.box    = ( 0, 0, 0, 0 )      # y, x, height, width
        self.plain  = False               # text, rather than a list of choices

    @property
    def inner( self ):
        y, x, h, w = self.box
        return y + 1, x + 1, max( 0, h - 2 ), max( 0, w - 2 )

    def current( self ):
        return self.rows[ self.cursor ] if 0 <= self.cursor < len( self.rows ) else None

    def move( self, delta ):
        if self.rows:
            self.cursor = max( 0, min( len( self.rows ) - 1, self.cursor + delta ) )
        self.reveal()

    def scroll( self, delta ):
        """The wheel moves the window and not the cursor: looking is not
        choosing, and a list that jumped its selection under the pointer would
        be choosing for you."""
        height = self.inner[ 2 ]
        self.top = max( 0, min( max( 0, len( self.rows ) - height ), self.top + delta ) )

    def reveal( self ):
        height = self.inner[ 2 ]
        if height:
            self.top = max( self.cursor - height + 1, min( self.top, self.cursor ) )
            self.top = max( 0, min( self.top, max( 0, len( self.rows ) - height ) ) )

    def holds( self, y, x ):
        by, bx, h, w = self.box
        return by <= y < by + h and bx <= x < bx + w

    def row_at( self, y ):
        index = self.top + ( y - self.inner[ 0 ] )
        return index if 0 <= index < len( self.rows ) else None

    def keep( self, rows, key ):
        """Replace the rows, leaving the cursor on the same thing when it is
        still there -- these lists are rebuilt twice a second."""
        was = self.current()
        self.rows = rows
        if was is not None:
            for i, row in enumerate( rows ):
                if key( row ) == key( was ):
                    self.cursor = i
                    break
            else:
                self.cursor = min( self.cursor, max( 0, len( rows ) - 1 ) )
        else:
            self.cursor = min( self.cursor, max( 0, len( rows ) - 1 ) )
        # The scroll is NOT brought back to the cursor here. These lists are
        # rebuilt twice a second, and a rebuild that dragged the view back to
        # the selection would undo, half a second later, every turn of the
        # wheel -- which is exactly what a wheel is not for.
        self.top = max( 0, min( self.top, max( 0, len( rows ) - self.inner[ 2 ] ) ) )


# ── drawing ──────────────────────────────────────────────────────────────────

def put( win, y, x, text, width, attr = 0 ):
    if y < 0 or x < 0 or width <= 0:
        return
    try:
        win.addnstr( y, x, str( text ), width, attr )
    except curses.error:
        pass                # the bottom right cell of a terminal is a lie


def draw_box( win, box, title, active ):
    y, x, h, w = box
    if h < 2 or w < 4:
        return
    tl, tr, bl, br, hor, ver = BOX
    attr = ( curses.color_pair( C_ACTIVE ) | curses.A_BOLD ) if active \
           else curses.color_pair( C_DIM )
    head = f" {title} "[ : max( 0, w - 4 ) ]
    put( win, y, x, tl + head + hor * ( w - 2 - len( head ) ) + tr, w, attr )
    for i in range( 1, h - 1 ):
        put( win, y + i, x, ver, 1, attr )
        put( win, y + i, x + w - 1, ver, 1, attr )
    put( win, y + h - 1, x, bl + hor * ( w - 2 ) + br, w, attr )


def draw_rows( win, rows, cursor, box_inner, active, plain = False ):
    top_y, left, height, width = box_inner
    for i in range( height ):
        index = cursor[ 0 ] + i          # cursor is ( top, selected )
        if index >= len( rows ):
            break
        row = rows[ index ]
        y = top_y + i
        chosen = active and index == cursor[ 1 ]
        base = curses.A_REVERSE if chosen else 0
        if plain:
            put( win, y, left, row.label, width, base | _colour( row ) )
            continue
        lead = "  " * row.depth
        if row.open is not None:
            lead += "▾ " if row.open else "▸ "
        elif row.checked is not None:
            lead += "[x] " if row.checked else "[ ] "
        elif row.mark is not None:
            lead += f"{row.mark:<5}"
        else:
            lead += "  "
        text = lead + row.label
        put( win, y, left, text.ljust( width )[ : width ], width, base | _colour( row ) )
        if row.detail:
            room = width - len( text ) - 2
            if room > 4:
                shown = row.detail[ : room ]
                put( win, y, left + width - len( shown ), shown, len( shown ),
                     base | curses.color_pair( C_DIM ) )


def _colour( row ):
    if row.kind == "group":
        return curses.color_pair( C_TITLE ) | curses.A_BOLD
    if row.kind == "broken" or row.mark in ( "FAIL", "lost" ):
        return curses.color_pair( C_BAD )
    if row.mark == "ok":
        return curses.color_pair( C_OK )
    if row.mark == "skip":
        return curses.color_pair( C_WARN )
    if row.checked:
        return curses.color_pair( C_OK )
    return 0


def draw_pane( win, pane, active ):
    draw_box( win, pane.box, pane.title, active )
    draw_rows( win, pane.rows, ( pane.top, pane.cursor ), pane.inner, active, pane.plain )


# ── the dialog ───────────────────────────────────────────────────────────────

class Dialog:
    """Where, with which tags, with which parameters -- and nothing else.

    Not *which case*: that was the list enter was pressed in, and a window
    asking it again would be asking a question already answered.
    """

    def __init__( self, session: Session, cases ):
        self.session = session
        self.cases   = list( cases )
        self.rows    = self._rows()
        self.cursor  = 0
        self.top     = 0
        self.first()

    def _rows( self ):
        s = self.session
        rows = [ ]
        if s.envs:
            rows.append( Row( "environments", kind = "group" ) )
            for e in s.envs:
                tags = " ".join( k if v is True else f"{k}={v}"
                                 for k, v in sorted( e.tags.items() ) )
                rows.append( Row( e.name, tags, kind = "env", data = e.name,
                                  checked = False, depth = 1 ) )
        for name, values in sorted( s.tag_values().items() ):
            rows.append( Row( f"--{name}", kind = "group" ) )
            for v in values:
                rows.append( Row( v, kind = "tag", data = ( name, v ),
                                  checked = False, depth = 1 ) )
        for name, param in s.params_of( self.cases ).items():
            rows.append( Row( f"--{name.replace( '_', '-' )}", param.help, kind = "group" ) )
            if param.choices:
                for v in param.choices:
                    rows.append( Row( str( v ), kind = "choice", data = ( name, str( v ) ),
                                      checked = False, depth = 1 ) )
            else:
                rows.append( Row( "", f"default {param.default!r}", kind = "field",
                                  data = name, depth = 1 ) )
        rows.append( Row( "how many at once", kind = "group" ) )
        rows.append( Row( "1", "-j", kind = "jobs", data = "jobs", depth = 1 ) )
        rows.append( Row( "detach, and give the shell back", "--batch",
                          kind = "batch", data = "batch", checked = False ) )
        return rows

    def first( self ):
        for i, row in enumerate( self.rows ):
            if row.kind != "group":
                self.cursor = i
                return

    def move( self, delta ):
        step = 1 if delta >= 0 else -1
        target = max( 0, min( len( self.rows ) - 1, self.cursor + delta ) )
        while 0 <= target < len( self.rows ) and self.rows[ target ].kind == "group":
            target += step
        if 0 <= target < len( self.rows ):
            self.cursor = target

    def toggle( self ):
        row = self.rows[ self.cursor ]
        if row.checked is not None:
            row.checked = not row.checked

    def type( self, key ):
        """A field is edited where it stands; there is no mode to be in."""
        row = self.rows[ self.cursor ]
        if row.kind not in ( "field", "jobs" ):
            return False
        if key in ( curses.KEY_BACKSPACE, 127, 8 ):
            row.label = row.label[ : -1 ]
        elif 32 <= key < 127:
            row.label += chr( key )
        return True

    def argv( self ):
        envs, tags, params, jobs, detach = [ ], { }, { }, 1, False
        for row in self.rows:
            if row.kind == "env" and row.checked:
                envs.append( row.data )
            elif row.kind == "tag" and row.checked:
                tags.setdefault( row.data[ 0 ], [ ] ).append( row.data[ 1 ] )
            elif row.kind == "choice" and row.checked:
                params.setdefault( row.data[ 0 ], [ ] ).append( row.data[ 1 ] )
            elif row.kind == "field" and row.label.strip():
                params[ row.data ] = [ row.label.strip() ]
            elif row.kind == "jobs" and row.label.strip().isdigit():
                jobs = int( row.label.strip() )
            elif row.kind == "batch":
                detach = bool( row.checked )
        return self.session.command( entries = self.cases, envs = envs, tags = tags,
                                     params = params, jobs = jobs, batch = detach )

    def draw( self, win ):
        height, width = win.getmaxyx()
        w = max( 24, min( width - 4, 78 ) )
        h = max( 8, min( height - 2, len( self.rows ) + 5 ) )
        y0, x0 = max( 0, ( height - h ) // 2 ), max( 0, ( width - w ) // 2 )
        for i in range( h ):
            put( win, y0 + i, x0, " " * w, w )
        title = "run: " + ", ".join( e.name for e in self.cases )
        draw_box( win, ( y0, x0, h, w ), title[ : w - 6 ], True )

        page = h - 4
        self.top = max( self.cursor - page + 1, min( self.top, self.cursor ) )
        self.top = max( 0, min( self.top, max( 0, len( self.rows ) - page ) ) )
        inner = ( y0 + 1, x0 + 2, page, w - 4 )
        for i in range( page ):
            index = self.top + i
            if index >= len( self.rows ):
                break
            row = self.rows[ index ]
            attr = curses.A_REVERSE if index == self.cursor else 0
            lead = "  " * row.depth
            if row.checked is not None:
                lead += "[x] " if row.checked else "[ ] "
            elif row.kind in ( "field", "jobs" ):
                lead += "  "
            text = lead + ( row.label or "" )
            if row.kind in ( "field", "jobs" ) and index == self.cursor:
                text += "_"
            put( win, inner[ 0 ] + i, inner[ 1 ], text.ljust( inner[ 3 ] )[ : inner[ 3 ] ],
                 inner[ 3 ], attr | _colour( row ) )
            if row.detail:
                room = inner[ 3 ] - len( text ) - 2
                if room > 4:
                    shown = row.detail[ : room ]
                    put( win, inner[ 0 ] + i, inner[ 1 ] + inner[ 3 ] - len( shown ), shown,
                         len( shown ), attr | curses.color_pair( C_DIM ) )
        # Said once, small, out of the way: what this window is about to do --
        # not a prompt, and nobody is being asked to type it.
        put( win, y0 + h - 3, x0 + 2, self.session.as_line( self.argv() )[ : w - 4 ], w - 4,
             curses.color_pair( C_DIM ) )
        put( win, y0 + h - 2, x0 + 2, "space ticks   enter runs   esc gives up", w - 4,
             curses.color_pair( C_DIM ) )


# ── the screen ───────────────────────────────────────────────────────────────

class Screen:
    def __init__( self, session: Session ):
        self.session = session
        self.cases   = Pane( "cases", "cases" )
        self.runs    = Pane( "runs", "runs" )
        self.files   = Pane( "files", "files" )
        self.look    = Pane( "look", "preview" )
        self.look.plain = True
        self.panes   = [ self.cases, self.runs, self.files, self.look ]
        self.active  = 0
        self.ticked  : set = set()     # cases, by ( file, line, name )
        self.folded  : set = set()     # files whose cases are hidden
        self.opened  : set = set()     # commands whose runs are shown
        self.filter  = ""
        self.typing  = False
        self.dialog  : Dialog | None = None
        self.message = ""
        self.past    : dict = { }      # command -> ( plan, states )
        self.looked  = 0.0
        self.help    = False

    # ── the lists ────────────────────────────────────────────────────────────

    def build_cases( self ):
        """A file, and its cases under it: a tree, because that is the shape the
        work has -- the file is where you go looking for it."""
        rows, needle = [ ], self.filter.lower()
        by_file: dict = { }
        for e in self.session.entries:
            by_file.setdefault( e.file, [ ] ).append( e )
        for path in sorted( by_file, key = str ):
            mine = [ e for e in sorted( by_file[ path ], key = lambda e: e.line )
                     if not needle or needle in f"{e.name} {path} {' '.join( e.tags )}".lower() ]
            if not mine:
                continue
            folded = path in self.folded
            rows.append( Row( short( path, self.session.root ), f"{len( mine )}",
                              kind = "group", data = ( "file", path ), open = not folded ) )
            if not folded:
                for e in mine:
                    rows.append( Row( e.name, f"{e.kind}:{e.line}", kind = "case", data = e,
                                      depth = 1, checked = _id( e ) in self.ticked ) )
        # Loudly, at the end: a file that declares work and would not import is
        # not a detail, and a short list must give the reason it is short.
        for path, why, trace in self.session.broken:
            rows.append( Row( short( path, self.session.root ), why[ : 44 ], kind = "broken",
                              data = ( "broken", path, why, trace ), mark = "!" ) )
        if not rows:
            rows.append( Row( f"nothing matches /{self.filter}" if self.filter
                              else "nothing declares work here" ) )
        self.cases.keep( rows, key = lambda r: ( r.kind, str( r.data ) ) )
        self.cases.title = ( f"cases  /{self.filter}" if self.filter else
                             f"cases  {len( self.ticked )} ticked" if self.ticked else "cases" )

    def command_lines( self ):
        """Every command run from here, the one going on now first."""
        lines = self.session.history()
        here = self.session.command_line
        mine = here[ len( "errand " ) : ] if here.startswith( "errand " ) else here
        if mine:
            if mine in lines:
                lines.insert( 0, lines.pop( lines.index( mine ) ) )
            else:
                lines.insert( 0, mine )
        return lines

    def is_current( self, line ):
        here = self.session.command_line
        return bool( here ) and here[ len( "errand " ) : ] == line and bool( self.session.plan )

    def states_for( self, line, fresh = False ):
        """What that command produced, read out of the tree.

        The one running now is this session's own business; every other line is
        worked out from the command itself -- which is why one from yesterday
        reads exactly like the one moving right now.
        """
        if self.is_current( line ):
            return self.session.states
        if line not in self.past or fresh:
            plan = self.past.get( line, ( None, None ) )[ 0 ]
            if plan is None:
                plan = self.session.predict( self.session.args_of( line ) )
            self.past[ line ] = ( plan, self.session.states_of( plan ) )
        return self.past[ line ][ 1 ]

    def build_runs( self ):
        """One list, because a run and a line of history are one thing: a
        command, and what it produced."""
        rows = [ ]
        for line in self.command_lines():
            shown = line in self.opened
            states = ( self.states_for( line ) if shown or self.is_current( line )
                       else self.past.get( line, ( None, None ) )[ 1 ] )
            rows.append( Row( line, _summary( states ), kind = "group",
                              data = ( "command", line ), open = shown ) )
            if shown and states:
                for state in states:
                    rows.append( Row( S.labelled( state, True ), S.detail_of( state ),
                                      kind = "run", data = state, depth = 1,
                                      mark = S.MARKS[ S.mark_of( state ) ] ) )
        if not rows:
            rows.append( Row( "nothing has been run from here yet" ) )
        self.runs.keep( rows, key = lambda r: ( r.kind, _run_key( r ) ) )

    def chosen_states( self ):
        """What the files pane is about: one run, or every run of a command."""
        row = self.runs.current()
        if row is None:
            return [ ]
        if row.kind == "run":
            return [ row.data ]
        if row.kind == "group":
            return self.states_for( row.data[ 1 ] ) or [ ] if row.open else [ ]
        return [ ]

    def broken_row( self ):
        """The cases pane, when it is sitting on a file that would not import.

        The right column follows whatever the left one is about, and what a
        file that would not import is about is the reason it would not.
        """
        row = self.cases.current()
        if self.panes[ self.active ] is self.cases and row is not None and row.kind == "broken":
            return row
        return None

    def build_files( self ):
        if self.broken_row() is not None:
            self.files.keep( [ Row( "nothing to show: this file would not import" ) ],
                             key = lambda r: r.label )
            return
        rows = [ ]
        for state in self.chosen_states():
            for path in self.session.files_of( state.get( "dir" ) ):
                rows.append( Row( path.name, size_of( path ), kind = "file", data = path ) )
        if not rows:
            rows.append( Row( "nothing written yet" ) )
        self.files.keep( rows, key = lambda r: str( r.data ) )

    def build_preview( self ):
        gone = self.broken_row()
        if gone is not None:
            _, path, why, trace = gone.data
            self.look.title = path.name
            self.look.rows = [ Row( why ), Row( "" ) ] + [
                Row( line.replace( "\t", "    " ) ) for line in trace.splitlines() ]
            return
        row = self.files.current()
        path = row.data if row is not None and row.kind == "file" else None
        if path is None:
            self.look.title, self.look.rows = "preview", [ Row( "" ) ]
            return
        lines, kind = self.session.preview( path )
        self.look.title = path.name
        if kind != "text":
            self.look.rows = [ Row( f"{kind}, {size_of( path )}" ), Row( "" ),
                               Row( "enter opens it with whatever the desktop uses" ) ]
            return
        rows = [ Row( line.replace( "\t", "    " ) ) for line in lines ]
        moved = len( rows ) != len( self.look.rows )
        self.look.rows = rows
        # What is being written right now is worth seeing from the end, but
        # only while nobody has scrolled it: following is a default, not a rule.
        if path.name == "output.txt" and moved and self.panes[ self.active ] is not self.look:
            self.look.top = max( 0, len( rows ) - self.look.inner[ 2 ] )
            self.look.cursor = max( 0, len( rows ) - 1 )

    # ── what a key does ──────────────────────────────────────────────────────

    def pane( self ):
        return self.panes[ self.active ]

    def fold( self, row ):
        if row.data[ 0 ] == "file":
            self.folded.symmetric_difference_update( { row.data[ 1 ] } )
        else:
            line = row.data[ 1 ]
            self.opened.symmetric_difference_update( { line } )
            if line in self.opened:
                self.states_for( line, fresh = True )

    def toggle_row( self ):
        row = self.pane().current()
        if row is None:
            return
        if row.open is not None:
            self.fold( row )
        elif row.kind == "case":
            self.ticked.symmetric_difference_update( { _id( row.data ) } )

    def enter( self ):
        pane, row = self.pane(), self.pane().current()
        if row is None:
            return
        if pane is self.cases:
            if row.kind == "case":
                # What was ticked, or what the cursor is on: pressing enter on
                # something is asking for THAT, and having to tick it first to
                # be taken seriously would be a ceremony.
                cases = [ e for e in self.session.entries if _id( e ) in self.ticked ] \
                        or [ row.data ]
                self.dialog = Dialog( self.session, cases )
            elif row.open is not None:
                self.fold( row )
        elif pane is self.runs:
            if row.kind == "group":
                self.fold( row )
            else:
                self.active = 2                    # its files are the next question
        elif pane in ( self.files, self.look ):
            target = self.files.current()
            if target is not None and target.kind == "file":
                self.message = S.open_file( target.data ) or f"opening {target.data.name}"

    def run_again( self ):
        row = self.runs.current()
        if row is None or row.kind != "group":
            self.message = "put the cursor on a command in `runs`"
            return
        self.launch( self.session.args_of( row.data[ 1 ] ) )

    def launch( self, argv ):
        why = self.session.launch( argv )
        self.message = why or self.session.command_line
        if why:
            return
        self.past.clear()
        self.opened.add( self.session.command_line[ len( "errand " ) : ] )
        self.active = 1
        self.runs.cursor = 0

    def mouse( self, y, x, state ):
        if TRACE:
            open( TRACE, "a" ).write( f"mouse y={y} x={x} state={hex(state)} "
                                      f"boxes={[p.box for p in self.panes]}\n" )
        for index, pane in enumerate( self.panes ):
            if not pane.holds( y, x ):
                continue
            if state & WHEEL_UP:
                pane.scroll( -WHEEL )
            elif state & WHEEL_DOWN:
                pane.scroll( WHEEL )
            elif not state & PRESSED:
                return                        # a release, or a button we do not use
            else:
                # Clicking a pane makes it the one the arrows drive: pointing at
                # a thing is as good a way of choosing it as walking to it.
                self.active = index
                where = pane.row_at( y )
                if where is not None:
                    pane.cursor = where
                    row = pane.rows[ where ]
                    # The little triangle and the box are targets of their own,
                    # so clicking one folds or ticks instead of only selecting.
                    column = x - pane.inner[ 1 ] - 2 * row.depth
                    if row.open is not None and column < 2:
                        self.fold( row )
                    elif row.checked is not None and column < 4:
                        self.toggle_row()
            return


def _run_key( row ):
    if row.kind == "run":
        return f"{row.data.get( 'label' )}|{row.data.get( 'env' )}|{row.data.get( 'params' )}"
    return str( row.data )


def _summary( states ):
    if states is None:
        return "…"
    if not states:
        return ""
    done = [ s for s in states if s[ "state" ] == "done" ]
    bad  = [ s for s in done if s.get( "status" ) != "PASS" ]
    if len( done ) < len( states ):
        return f"{len( done )}/{len( states )}"
    return f"{len( bad )} of {len( states )} failed" if bad else f"{len( states )} ok"


# ── the loop ─────────────────────────────────────────────────────────────────

KEYS = [
    ( "arrows", "move in the active pane; tab goes to the next" ),
    ( "click",  "choose, and make that pane the active one" ),
    ( "wheel",  "scroll whatever is under the pointer" ),
    ( "space",  "tick a case, or fold a file / a command" ),
    ( "enter",  "cases: run them · runs: its files · files: open it" ),
    ( "r",      "run the command under the cursor again" ),
    ( "o",      "open the file under the cursor" ),
    ( "/",      "filter the cases; esc clears it" ),
    ( "x",      "interrupt what is running" ),
    ( "d",      "read the project again" ),
    ( "q",      "leave" ),
]


def layout( screen: Screen, height, width ):
    """A line for the title, a line for the hint, and four boxes between."""
    left = max( 30, min( 70, width * 45 // 100 ) )
    body = height - 2
    top  = max( 5, body * 55 // 100 )
    screen.cases.box = ( 1, 0, top, left )
    screen.runs.box  = ( 1 + top, 0, body - top, left )
    right = width - left
    files = max( 4, body * 30 // 100 )
    screen.files.box = ( 1, left, files, right )
    screen.look.box  = ( 1 + files, left, body - files, right )


def draw( win, screen: Screen ):
    win.erase()
    if REPAINT:
        win.clearok( True )
    height, width = win.getmaxyx()
    layout( screen, height, width )
    for index, pane in enumerate( screen.panes ):
        draw_pane( win, pane, index == screen.active and screen.dialog is None )
    state = ( "running" if screen.session.running else
              "following" if screen.session.record else "idle" )
    put( win, 0, 1, f"errand · {screen.session.root.name} · {state}", max( 0, width - 2 ),
         curses.color_pair( C_ACTIVE ) | curses.A_BOLD )
    hint = ( f"/{screen.filter}_" if screen.typing else screen.message or
             "space tick   enter run   r again   o open   / filter   ? keys   q quit" )
    put( win, height - 1, 0, hint.ljust( width - 1 )[ : width - 1 ], width - 1,
         curses.color_pair( C_WARN ) if screen.message and not screen.typing
         else curses.color_pair( C_DIM ) )
    if screen.dialog is not None:
        screen.dialog.draw( win )
    elif screen.help:
        _help( win, height, width )
    win.noutrefresh()
    curses.doupdate()


def _help( win, height, width ):
    w, h = min( width - 4, 66 ), len( KEYS ) + 4
    y0, x0 = max( 0, ( height - h ) // 2 ), max( 0, ( width - w ) // 2 )
    for i in range( h ):
        put( win, y0 + i, x0, " " * w, w, curses.A_REVERSE )
    put( win, y0 + 1, x0 + 2, "keys", w - 4, curses.A_REVERSE | curses.A_BOLD )
    for i, ( key, what ) in enumerate( KEYS ):
        put( win, y0 + 2 + i, x0 + 2, f"{key:<7} {what}", w - 4, curses.A_REVERSE )
    put( win, y0 + h - 1, x0 + 2, "any key closes this", w - 4, curses.A_REVERSE )


def loop( win, screen: Screen ):
    curses.curs_set( 0 )
    with_colour = curses.has_colors()
    if with_colour:
        curses.use_default_colors()
        for pair, colour in ( ( C_TITLE, curses.COLOR_CYAN ), ( C_ACTIVE, curses.COLOR_CYAN ),
                              ( C_DIM, -1 ), ( C_OK, curses.COLOR_GREEN ),
                              ( C_BAD, curses.COLOR_RED ), ( C_WARN, curses.COLOR_YELLOW ) ):
            try:
                curses.init_pair( pair, colour, -1 )
            except curses.error:
                pass
    curses.mousemask( curses.ALL_MOUSE_EVENTS | WHEEL_UP | WHEEL_DOWN )
    curses.mouseinterval( 0 )            # a click is a click, not half a drag
    win.timeout( 200 )

    while True:
        now = time.time()
        if now - screen.looked > LOOK:
            screen.looked = now
            if screen.session.plan:
                screen.session.look()
            screen.build_cases()
            screen.build_runs()
        screen.build_files()
        screen.build_preview()
        draw( win, screen )

        key = win.getch()
        if TRACE and key != -1:
            open( TRACE, "a" ).write( f"key {key}\n" )
        if key == -1:
            continue
        if screen.dialog is not None:
            _dialog_key( screen, key )
            continue
        if screen.help:
            screen.help = False
            continue
        if screen.typing:
            _filter_key( screen, key )
            continue

        screen.message = ""
        pane = screen.pane()
        if key == curses.KEY_MOUSE:
            try:
                _, x, y, _, state = curses.getmouse()
            except curses.error:
                continue
            screen.mouse( y, x, state )
        elif key in ( curses.KEY_DOWN, ord( "n" ) ):
            pane.move( 1 )
        elif key in ( curses.KEY_UP, ord( "p" ) ):
            pane.move( -1 )
        elif key == curses.KEY_NPAGE:
            pane.move( max( 1, pane.inner[ 2 ] - 1 ) )
        elif key == curses.KEY_PPAGE:
            pane.move( -max( 1, pane.inner[ 2 ] - 1 ) )
        elif key == curses.KEY_HOME:
            pane.cursor = 0
            pane.reveal()
        elif key == curses.KEY_END:
            pane.cursor = max( 0, len( pane.rows ) - 1 )
            pane.reveal()
        elif key in ( 9, ord( "\t" ) ):
            screen.active = ( screen.active + 1 ) % len( screen.panes )
        elif key == curses.KEY_BTAB:
            screen.active = ( screen.active - 1 ) % len( screen.panes )
        elif key == curses.KEY_RIGHT:
            row = pane.current()
            if row is not None and row.open is False:
                screen.fold( row )
        elif key == curses.KEY_LEFT:
            row = pane.current()
            if row is not None and row.open:
                screen.fold( row )
        elif key == ord( " " ):
            screen.toggle_row()
        elif key in ( 10, 13, curses.KEY_ENTER ):
            screen.enter()
        elif key == ord( "r" ):
            screen.run_again()
        elif key == ord( "o" ):
            row = screen.files.current()
            if row is not None and row.kind == "file":
                screen.message = S.open_file( row.data ) or f"opening {row.data.name}"
        elif key == ord( "/" ):
            screen.typing, screen.active = True, 0
        elif key == 27:
            screen.filter = ""
            screen.build_cases()
        elif key == ord( "x" ):
            screen.message = screen.session.stop() or "interrupted"
        elif key == ord( "d" ):
            screen.session.discover()
            screen.past.clear()
            screen.message = ( f"{len( screen.session.entries )} case(s)"
                               + ( f", {len( screen.session.broken )} unreadable file(s)"
                                   if screen.session.broken else "" ) )
        elif key == ord( "?" ):
            screen.help = True
        elif key == ord( "q" ):
            # A run started here belongs here: leaving would break the pipe
            # under it. Detaching is how work is meant to outlive a window.
            if screen.session.running:
                screen.message = ( "something is running: x interrupts it, "
                                   "or tick `detach` next time" )
            else:
                return 0


def _filter_key( screen: Screen, key ):
    if key in ( 10, 13, curses.KEY_ENTER ):
        screen.typing = False
    elif key == 27:
        screen.typing, screen.filter = False, ""
    elif key in ( curses.KEY_BACKSPACE, 127, 8 ):
        screen.filter = screen.filter[ : -1 ]
    elif 32 <= key < 127:
        screen.filter += chr( key )
    screen.build_cases()


def _dialog_key( screen: Screen, key ):
    dialog = screen.dialog
    if key == 27:
        screen.dialog = None
    elif key in ( 10, 13, curses.KEY_ENTER ):
        screen.dialog = None
        screen.launch( dialog.argv() )
    elif key == curses.KEY_DOWN:
        dialog.move( 1 )
    elif key == curses.KEY_UP:
        dialog.move( -1 )
    elif key == ord( " " ) and dialog.rows[ dialog.cursor ].checked is not None:
        dialog.toggle()
    else:
        dialog.type( key )


def main( root: Path, out_root: Path ):
    import sys

    if not sys.stdout.isatty():
        print( "errand --tui needs a terminal", file = sys.stderr )
        return 2
    return curses.wrapper( loop, Screen( Session( root, out_root ).discover() ) ) or 0
