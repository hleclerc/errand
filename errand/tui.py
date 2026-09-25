"""`errand --tui`: a screen for choosing what to run, and watching it happen.

Drawn with the curses of the standard library, so errand still installs with
nothing at all. Everything that is not drawing is in `session.py`, which has no
screen in it and is tested without a terminal.

**There is no focus to manage.** One pane is active, the arrows drive it, and
clicking a pane selects it. The wheel scrolls whatever is under the pointer and
changes nothing else -- which is what a wheel is for.

**One function key per rectangle, written in its own title**: F1 cases, F2
about, F3 runs, F4 files, F5 preview. One press from anywhere, and the page
follows -- a key written where it takes you has to be neither remembered nor
cycled through.

    ╭─ F1 cases ───────────────╮╭─ F4 files ───────────────────╮
    │ ▾ bench_solver.py        ││   shape.svg         12.1 kB  │
    │   [x] solve              ││   result.yaml          512 B │
    │   [ ] gradient           ││   output.txt         1.2 kB  │
    ╰──────────────────────────╯╰──────────────────────────────╯
    ╭─ F3 runs ────────────────╮╭─ F5 output.txt ──────────────╮
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

import contextlib
import curses
import os
import time
from pathlib import Path

from . import fuzzy, session as S
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


def dim( ):
    """Faded, and faded ON PURPOSE: the default colour is what ordinary text
    already is, so saying `C_DIM` alone said nothing. What is there to be read
    only if you look for it -- helps, sizes, details -- goes through here."""
    return curses.color_pair( C_DIM ) | curses.A_DIM | curses.A_DIM

PAGES = ( "cases", "runs" )

# **The letters are the search, so the verbs are the function keys.** There are
# twelve of them; a screen that has to be typed at cannot also be driven by
# letters, and a verb on a function key is a verb nothing else can claim.
def _f( n ):
    return curses.KEY_F0 + n




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


def _parts( path, root ):
    """Where a file sits, one directory at a time. A file outside the project
    keeps its whole name and lands at the top: it is not part of the layout."""
    try:
        return Path( path ).relative_to( root ).parts
    except ValueError:
        return ( str( path ), )


class _Node:
    """One directory, or one file with its cases -- the project as it is laid
    out on disk, which is the only tree nobody has to be taught."""

    __slots__ = ( "path", "children", "entries" )

    def __init__( self, path ):
        self.path     = Path( path )
        self.children : dict = { }
        self.entries  : list = [ ]

    def put( self, parts, path, entries ):
        node, here = self, self.path
        for part in parts:
            here = here / part
            node = node.children.setdefault( part, _Node( here ) )
        node.path    = Path( path )
        node.entries = entries

    def count( self ):
        return len( self.entries ) + sum( c.count() for c in self.children.values() )

    def sorted( self ):
        """Directories first, then files, each in alphabetical order: the order
        a listing has, so the eye already knows it."""
        return sorted( self.children.items(), key = lambda kv: ( bool( kv[ 1 ].entries ),
                                                                 kv[ 0 ] ) )


# ── rows and panes ───────────────────────────────────────────────────────────

class Row:
    __slots__ = ( "label", "detail", "kind", "data", "depth", "checked", "mark", "open",
                  "hits" )

    def __init__( self, label, detail = "", *, kind = "plain", data = None, depth = 0,
                  checked = None, mark = None, open = None, hits = ( ) ):
        self.label, self.detail, self.kind, self.data = label, detail, kind, data
        self.depth   = depth
        self.checked = checked      # None: not something that can be ticked
        self.mark    = mark         # what stands where the box would be
        self.open    = open         # None: not something that can be folded
        # Which letters of the label answered the search. Shown in bold: a list
        # that says WHY a row is in it is one you can trust after a glance.
        self.hits    = tuple( hits )


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
           else dim()
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
        for i in row.hits:
            at = len( lead ) + i
            if at < width:
                put( win, y, left + at, row.label[ i ], 1,
                     base | curses.color_pair( C_ACTIVE ) | curses.A_BOLD )
        if row.detail:
            room = width - len( text ) - 2
            if room > 4:
                shown = row.detail[ : room ]
                put( win, y, left + width - len( shown ), shown, len( shown ),
                     base | dim() )


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

class Chip:
    """A thing to tick, sitting on the line of the flag it belongs to."""

    __slots__ = ( "label", "data", "checked", "span" )

    def __init__( self, label, data ):
        self.label, self.data, self.checked = label, data, False
        self.span = None                 # where it was drawn, so it can be clicked


class Option:
    """One line, always the same shape: **the flag on the left, the field in
    the middle, what it means on the right, faded.** An eye that has read one
    line has read them all, and a thing spread over two lines is a thing you
    have to assemble before you can read it.
    """

    __slots__ = ( "kind", "flag", "help", "chips", "text", "ghost", "spot", "name", "y" )

    def __init__( self, kind, flag, help = "", chips = ( ), ghost = "", name = None ):
        self.kind  = kind                # "chips" | "text"
        self.flag, self.help = flag, help
        self.chips = list( chips )
        self.text  = ""                  # what was TYPED, as opposed to the ghost
        self.ghost = ghost               # what happens if nothing is
        self.spot  = 0                   # which chip the cursor is on
        self.name  = name                # what it is, when the command is built
        self.y     = None                # where it was drawn


class Dialog:
    """Where, with which tags, with which parameters -- and nothing else.

    Not *which case*: that was the list enter was pressed in, and a window
    asking it again would be asking a question already answered.

    Everything here is one line: `--fp  [x] 32  [ ] 64      which precision`.
    Ticking two environments and two values is four runs -- **a tick is a
    comma**, and the window is the matrix said out loud.
    """

    def __init__( self, session: Session, cases ):
        self.session = session
        self.cases   = list( cases )
        self.options = self._options()
        self.cursor  = 0
        self.top     = 0

    def _options( self ):
        s = self.session
        out = [ ]
        if s.envs:
            out.append( Option( "chips", "--env", "two ticks is two runs",
                                [ Chip( e.name, e.name ) for e in s.envs ], name = "env" ) )
        for name, values in sorted( s.tag_values().items() ):
            out.append( Option( "chips", f"--{name}", "only the ones that say so",
                                [ Chip( v, ( name, v ) ) for v in values ], name = "tag" ) )
        for name, param in s.params_of( self.cases ).items():
            flag = f"--{name.replace( '_', '-' )}"
            if param.choices:
                out.append( Option( "chips", flag, param.help,
                                    [ Chip( str( v ), ( name, str( v ) ) )
                                      for v in param.choices ], name = "choice" ) )
            else:
                out.append( Option( "text", flag, param.help, ghost = str( param.default ),
                                    name = ( "param", name ) ) )
        out.append( Option( "text", "-j", "how many at once", ghost = "1", name = "jobs" ) )
        out.append( Option( "chips", "--batch", "outlives this window",
                            [ Chip( "detach", "batch" ) ], name = "batch" ) )
        return out

    # ── what it is ───────────────────────────────────────────────────────────

    def current( self ):
        return self.options[ self.cursor ]

    def move( self, delta ):
        self.cursor = max( 0, min( len( self.options ) - 1, self.cursor + delta ) )

    def sideways( self, delta ):
        option = self.current()
        if option.kind == "chips":
            option.spot = max( 0, min( len( option.chips ) - 1, option.spot + delta ) )

    def toggle( self ):
        option = self.current()
        if option.kind == "chips" and option.chips:
            chip = option.chips[ option.spot ]
            chip.checked = not chip.checked
            return True
        return False

    def type( self, key ):
        """A field is typed into where it stands; there is no mode to be in."""
        option = self.current()
        if option.kind != "text":
            return False
        if key in ( curses.KEY_BACKSPACE, 127, 8 ):
            option.text = option.text[ : -1 ]
        elif 32 <= key < 127:
            option.text += chr( key )
        return True

    def click( self, y, x ):
        for index, option in enumerate( self.options ):
            if option.y != y:
                continue
            self.cursor = index
            for spot, chip in enumerate( option.chips ):
                if chip.span and chip.span[ 0 ] <= x < chip.span[ 1 ]:
                    option.spot = spot
                    chip.checked = not chip.checked
            return

    def argv( self ):
        envs, tags, params, jobs, detach = [ ], { }, { }, 1, False
        for option in self.options:
            ticked = [ c for c in option.chips if c.checked ]
            typed  = option.text.strip()
            if option.name == "env":
                envs = [ c.data for c in ticked ]
            elif option.name == "tag":
                for c in ticked:
                    tags.setdefault( c.data[ 0 ], [ ] ).append( c.data[ 1 ] )
            elif option.name == "choice":
                for c in ticked:
                    params.setdefault( c.data[ 0 ], [ ] ).append( c.data[ 1 ] )
            elif option.name == "batch":
                detach = bool( ticked )
            elif option.name == "jobs":
                jobs = int( typed ) if typed.isdigit() else 1
            elif typed:
                params[ option.name[ 1 ] ] = [ typed ]
        return self.session.command( entries = self.cases, envs = envs, tags = tags,
                                     params = params, jobs = jobs, batch = detach )

    # ── what it looks like ───────────────────────────────────────────────────

    def draw( self, win ):
        height, width = win.getmaxyx()
        w = max( 40, min( width - 4, 100 ) )
        shown = max( 1, min( len( self.options ), height - 7 ) )
        h = shown + 5
        y0, x0 = max( 0, ( height - h ) // 2 ), max( 0, ( width - w ) // 2 )
        for i in range( h ):
            put( win, y0 + i, x0, " " * w, w )
        title = "run: " + ", ".join( e.name for e in self.cases )
        draw_box( win, ( y0, x0, h, w ), title[ : w - 6 ], True )

        self.top = max( self.cursor - shown + 1, min( self.top, self.cursor ) )
        self.top = max( 0, min( self.top, len( self.options ) - shown ) )

        # Three columns, the same three on every line.
        flagw = max( len( o.flag ) for o in self.options )
        helpw = min( max( ( len( o.help ) for o in self.options ), default = 0 ), w // 3 )
        left  = x0 + 2
        field = left + flagw + 2
        helpx = x0 + w - 2 - helpw
        room  = max( 8, helpx - field - 2 )

        spot = None
        for option in self.options:
            option.y = None
        for i in range( shown ):
            index = self.top + i
            if index >= len( self.options ):
                break
            option, y = self.options[ index ], y0 + 1 + i
            option.y  = y
            here = index == self.cursor
            put( win, y, x0 + 1, "›" if here else " ", 1,
                 curses.color_pair( C_ACTIVE ) | curses.A_BOLD )
            put( win, y, left, option.flag, flagw,
                 curses.color_pair( C_TITLE ) | ( curses.A_BOLD if here else 0 ) )
            if option.kind == "chips":
                at = field
                for index_chip, chip in enumerate( option.chips ):
                    text = f"[{'x' if chip.checked else ' '}] {chip.label}"
                    attr = curses.color_pair( C_OK ) if chip.checked else 0
                    if here and index_chip == option.spot:
                        attr |= curses.A_REVERSE
                    put( win, y, at, text, max( 0, helpx - at - 1 ), attr )
                    chip.span = ( at, at + len( text ) )
                    at += len( text ) + 2
            elif option.text:
                # What was typed stands out from what would happen anyway.
                put( win, y, field, option.text[ : room ], room, curses.A_BOLD )
                spot = ( y, field + min( len( option.text ), room ) ) if here else spot
            else:
                put( win, y, field, option.ghost[ : room ], room, dim() )
                spot = ( y, field ) if here else spot
            if option.help:
                put( win, y, helpx, option.help[ : helpw ], helpw, dim() )

        # Said once, at the bottom, in its own colour: not a prompt, nobody is
        # being asked to type it -- it is what this window is about to do.
        put( win, y0 + h - 3, x0 + 2, "─" * ( w - 4 ), w - 4, dim() )
        put( win, y0 + h - 2, x0 + 2, self.session.as_line( self.argv() )[ : w - 4 ], w - 4,
             curses.color_pair( C_OK ) | curses.A_BOLD )
        # A cursor that blinks where a field is is the only way of saying "type
        # here" that nobody has to be taught.
        curses.curs_set( 1 if spot else 0 )
        if spot:
            with contextlib.suppress( curses.error ):
                win.move( *spot )


# ── the screen ───────────────────────────────────────────────────────────────

class Screen:
    def __init__( self, session: Session ):
        self.session = session
        self.cases   = Pane( "cases", "cases" )
        self.about   = Pane( "about", "about" )
        self.about.plain = True
        self.runs    = Pane( "runs", "runs" )
        self.files   = Pane( "files", "files" )
        self.look    = Pane( "look", "preview" )
        self.look.plain = True
        # Two pages, because they answer two questions: WHAT DO I RUN, and
        # WHAT CAME OF IT. Putting both on one screen made each of them half a
        # screen wide, and there are more cases than a half screen holds.
        self.pages   = { "cases": [ self.cases, self.about ],
                         "runs" : [ self.runs, self.files, self.look ] }
        self.tabs    : list = [ ]      # where the page names are, for clicking
        self.page    = "cases"
        self.active  = 0
        self.ticked  : set = set()     # cases, by ( file, line, name )
        self.folded  : set = set()     # files whose cases are hidden
        self.opened  : set = set()     # commands whose runs are shown
        # One search per page, because they are two lists: the one you keep on
        # `cases` is not lost by going to look at `runs`.
        self.queries = { "cases": "", "runs": "" }
        self.dialog  : Dialog | None = None
        self.message = ""
        self.past    : dict = { }      # command -> ( plan, states )
        self.looked  = 0.0
        self.dirty   = False           # a key changed what the lists hold
        self.help    = False

    # ── the lists ────────────────────────────────────────────────────────────

    def build_cases( self ):
        query = self.queries[ "cases" ]
        rows = self._found() if query.strip() else self._tree()
        for path, why, trace in self.session.broken:
            # Loudly, at the end: a file that declares work and would not
            # import is not a detail, and a short list must give the reason it
            # is short.
            rows.append( Row( short( path, self.session.root ), why[ : 44 ], kind = "broken",
                              data = ( "broken", path, why, trace ), mark = "!" ) )
        if not rows:
            rows.append( Row( "nothing answers that" if query.strip()
                              else "nothing declares work here" ) )
        self.cases.keep( rows, key = lambda r: ( r.kind, str( r.data ) ) )
        count = sum( 1 for r in rows if r.kind == "case" )
        self.cases.title = ( f"cases  {count} found" if query.strip() else
                             f"cases  {len( self.ticked )} ticked" if self.ticked else "cases" )

    def _tree( self ):
        """Directories, then files, then the cases in them: a tree, because
        that is the shape the work has -- a project is a layout before it is a
        list, and the directory is how somebody remembers where a case lives.

        A directory holding one single thing does NOT cost a row of its own:
        its name joins its child's, `src/bench/gpu.py` on one line. A row you
        can only walk through is a row that tells you nothing.
        """
        by_file: dict = { }
        for e in self.session.entries:
            by_file.setdefault( e.file, [ ] ).append( e )
        root = _Node( self.session.root )
        for path, mine in by_file.items():
            root.put( _parts( path, self.session.root ), path,
                      sorted( mine, key = lambda e: e.line ) )
        rows: list = [ ]
        self._branch( root, "", 0, rows )
        return rows

    def _branch( self, node, name, depth, rows ):
        """Emit `node` under the name it has ended up with, and what is in it."""
        while len( node.children ) == 1 and not node.entries:
            ( part, only ), = node.children.items()
            name, node = ( f"{name}/{part}" if name else part ), only
        below, shown = depth, True
        if name:                      # the root itself is the screen, not a row
            shown = node.path not in self.folded
            rows.append( Row( name, f"{node.count()}", kind = "group",
                              data = ( "node", node.path ), open = shown, depth = depth ) )
            below = depth + 1
        if not shown:
            return
        for part, child in node.sorted():
            self._branch( child, part, below, rows )
        for e in node.entries:
            rows.append( Row( e.name, f"{e.kind}:{e.line}", kind = "case", data = e,
                              depth = below, checked = _id( e ) in self.ticked ) )

    def _found( self ):
        """What the search found, best first -- and flat, because a ranking has
        an order of its own and a tree would fight it."""
        ranked = fuzzy.rank( self.queries[ "cases" ], self.session.entries, self._fields )
        rows = [ ]
        for e, _, marks in ranked:
            where = short( e.file, self.session.root )
            rows.append( Row( e.name, f"{where}:{e.line}", kind = "case", data = e,
                              checked = _id( e ) in self.ticked,
                              hits = marks.get( "name", ( ) ) ) )
        return rows

    def _fields( self, e ):
        """What a search looks in, and what each is worth. The name is what
        somebody types; the file is how they remember where it lives; the tags
        are how they say which KIND they mean."""
        return { "name": ( e.name, 1.0 ),
                 "file": ( short( e.file, self.session.root ), 0.75 ),
                 "tags": ( " ".join( e.tags ) + " " + e.kind, 0.9 ) }

    def build_about( self ):
        """Facing the list: everything about the case under the cursor, and how
        it went the last time it ran."""
        row = self.cases.current()
        if row is None:
            self.about.rows, self.about.title = [ Row( "" ) ], "about"
            return
        if row.kind == "broken":
            _, path, why, trace = row.data
            self.about.title = path.name
            self.about.rows = [ Row( why ), Row( "" ) ] + [
                Row( line.replace( "\t", "    " ) ) for line in trace.splitlines() ]
            return
        if row.kind != "case":
            self.about.title, self.about.rows = "about", [ Row( "" ) ]
            return
        e = row.data
        lines = [ f"{short( e.file, self.session.root )}:{e.line}", f"kind: {e.kind}" ]
        if e.tags:
            lines.append( "tags: " + ", ".join( e.tags ) )
        if e.resources:
            lines.append( "needs: " + ", ".join( f"{k}={v}" for k, v in e.resources.items() ) )
        traits = [ k for k, v in e.traits.items() if v ]
        if traits:
            lines.append( "traits: " + " ".join( traits ) )
        for name, param in e.params.items():
            lines += [ "", f"--{name.replace( '_', '-' )}   default {param.default!r}"
                           + ( f"   choices {param.choices}" if param.choices else "" ) ]
            if param.help:
                lines.append( f"  {param.help}" )
        got = self.session.last_result( e )
        if got:
            lines += [ "", "last run", f"  {got.get( 'status' )}   {got.get( 'env' )}"
                                       f"   {got.get( 'place' )}" ]
            if got.get( "date" ):
                lines.append( f"  {got[ 'date' ]}" )
            if got.get( "duration_s" ) is not None:
                lines.append( f"  {got[ 'duration_s' ]:g}s" )
            for key, value in ( got.get( "results" ) or { } ).items():
                lines.append( f"  {key} = {value}" )
            if got.get( "error" ):
                lines.append( f"  {got[ 'error' ]}" )
        lines += [ "", "enter asks where to run it" ]
        self.about.title = e.name
        self.about.rows = [ Row( line ) for line in lines ]

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
        lines, marks = self.command_lines(), { }
        query = self.queries[ "runs" ]
        if query.strip():
            # The same search, over the thing a runs page is a list of: the
            # command. A history is only useful once you can find one line in it.
            ranked = fuzzy.rank( query, lines, lambda l: { "command": ( l, 1.0 ) } )
            lines = [ line for line, _, _ in ranked ]
            marks = { line: hit.get( "command", ( ) ) for line, _, hit in ranked }
        rows = [ ]
        for line in lines:
            shown = line in self.opened
            states = ( self.states_for( line ) if shown or self.is_current( line )
                       else self.past.get( line, ( None, None ) )[ 1 ] )
            rows.append( Row( line, _summary( states ), kind = "group",
                              data = ( "command", line ), open = shown,
                              hits = marks.get( line, ( ) ) ) )
            if shown and states:
                for state in states:
                    rows.append( Row( S.labelled( state, True ), S.detail_of( state ),
                                      kind = "run", data = state, depth = 1,
                                      mark = S.MARKS[ S.mark_of( state ) ] ) )
        if not rows:
            rows.append( Row( "nothing answers that" if query.strip()
                              else "nothing has been run from here yet" ) )
        self.runs.keep( rows, key = lambda r: ( r.kind, _run_key( r ) ) )
        self.runs.title = f"runs  {len( lines )} found" if query.strip() else "runs"

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

    def build_files( self ):
        rows = [ ]
        for state in self.chosen_states():
            for path in self.session.files_of( state.get( "dir" ) ):
                rows.append( Row( path.name, size_of( path ), kind = "file", data = path ) )
        if not rows:
            rows.append( Row( "nothing written yet" ) )
        self.files.keep( rows, key = lambda r: str( r.data ) )

    def build_preview( self ):
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
        if path.name == "output.txt" and moved and self.pane() is not self.look:
            self.look.top = max( 0, len( rows ) - self.look.inner[ 2 ] )
            self.look.cursor = max( 0, len( rows ) - 1 )

    # ── what a key does ──────────────────────────────────────────────────────

    @property
    def panes( self ):
        return self.pages[ self.page ]

    def pane( self ):
        self.active = min( self.active, len( self.panes ) - 1 )
        return self.panes[ self.active ]

    @property
    def query( self ):
        return self.queries[ self.page ]

    def typed( self, text ):
        self.queries[ self.page ] = text
        self.build_cases() if self.page == "cases" else self.build_runs()

    def show( self, page ):
        self.page, self.active = page, 0

    def turn( self, delta ):
        """The page before, the page after. Two pages and two keys next to each
        other: there is nothing to aim at, only a direction."""
        self.show( PAGES[ ( PAGES.index( self.page ) + delta ) % len( PAGES ) ] )

    def step( self, delta ):
        """tab goes to the next rectangle OF THIS PAGE, and stays there.

        It used to run off the end into the other page; going somewhere by
        pressing the same key until you arrive is not going somewhere. The
        function keys are how you leave: one per rectangle, written in its
        title, one press from wherever you are.
        """
        self.active = ( self.active + delta ) % len( self.panes )

    def open_file( self ):
        row = self.files.current()
        if row is not None and row.kind == "file":
            self.message = S.open_file( row.data ) or f"opening {row.data.name}"
        else:
            self.message = "no file under the cursor"

    def fold( self, row ):
        if row.data[ 0 ] == "node":
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
                self.active = self.panes.index( self.files )   # its files are next
        elif pane in ( self.files, self.look ):
            self.open_file()

    def run_again( self ):
        row = self.runs.current()
        if row is None or row.kind != "group":
            self.message = "put the cursor on a command in `runs`"
            return
        self.launch( self.session.args_of( row.data[ 1 ] ) )

    def run_last( self ):
        """The last thing that was run, run again -- from either page, without
        going to look for it. It is the one thing you ask for twice."""
        lines = self.command_lines()
        if not lines:
            self.message = "nothing has been run from here yet"
            return
        self.launch( self.session.args_of( lines[ 0 ] ) )

    def reread( self ):
        self.session.discover()
        self.past.clear()
        self.message = ( f"{len( self.session.entries )} case(s)"
                         + ( f", {len( self.session.broken )} unreadable file(s)"
                             if self.session.broken else "" ) )

    def launch( self, argv ):
        why = self.session.launch( argv )
        self.message = why or self.session.command_line
        if why:
            return
        self.past.clear()
        self.opened.add( self.session.command_line[ len( "errand " ) : ] )
        self.show( "runs" )
        self.runs.cursor = 0

    def mouse( self, y, x, state ):
        if TRACE:
            open( TRACE, "a" ).write( f"mouse y={y} x={x} state={hex(state)} "
                                      f"boxes={[p.box for p in self.panes]}\n" )
        if y == 0 and state & PRESSED:
            for left, right, name in self.tabs:
                if left <= x < right:
                    self.show( name )
            return
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

HINTS = {
    "cases": "type to search · enter runs it · space ticks · tab next box · "
             "F3 runs · F1 keys · F12 quit",
    "runs" : "type to search · enter its files · F5 last again · F8 open · tab next box · "
             "F2 cases · F1 keys · F12 quit",
}

KEYS = [
    ( "F1",     "these keys" ),
    ( "F2 F3",  "the page before · the page after" ),
    ( "F5 F6",  "run the last command again · the one under the cursor" ),
    ( "F7 F8",  "interrupt what is running · open the file under the cursor" ),
    ( "F9",     "read the project again" ),
    ( "F12",    "leave" ),
    ( "typing", "the search, on either page" ),
    ( "esc",    "clear what you typed, then leave" ),
    ( "tab",    "the next rectangle of this page; shift-tab the one before" ),
    ( "arrows", "move in the active rectangle" ),
    ( "click",  "choose a row, and that rectangle becomes the active one" ),
    ( "wheel",  "scroll whatever is under the pointer" ),
    ( "space",  "tick a case, or fold — ctrl-space while a search is on" ),
    ( "enter",  "cases: ask where to run · runs: its files · files: open it" ),
]


def layout( screen: Screen, height, width ):
    """A line for the pages, a line for the search, a line for the keys, and
    the rectangles between.

    The search has a line of its own on BOTH pages: it is what you type into,
    so it is never somewhere you have to go and find, and it is in the same
    place whichever list you are looking at.
    """
    body = height - 3
    if screen.page == "cases":
        left = max( 30, min( 80, width * 55 // 100 ) )
        screen.cases.box = ( 2, 0, body, left )
        screen.about.box = ( 2, left, body, width - left )
        return
    left = max( 30, min( 76, width * 50 // 100 ) )
    files = max( 4, body * 35 // 100 )
    screen.runs.box  = ( 2, 0, body, left )
    screen.files.box = ( 2, left, files, width - left )
    screen.look.box  = ( 2 + files, left, body - files, width - left )


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
    screen.tabs, at = [ ], 1
    for name in PAGES:
        shown = f"[{name}]" if name == screen.page else f" {name} "
        put( win, 0, at, shown, max( 0, width - at ),
             curses.color_pair( C_ACTIVE if name == screen.page else C_DIM )
             | ( curses.A_BOLD if name == screen.page else 0 ) )
        screen.tabs.append( ( at, at + len( shown ), name ) )
        at += len( shown ) + 2
    right = f"errand · {screen.session.root.name} · {state}"
    put( win, 0, max( 0, width - len( right ) - 1 ), right, width - 1,
         dim() )

    put( win, 1, 1, "find: ", 6, curses.color_pair( C_TITLE ) | curses.A_BOLD )
    if screen.query:
        put( win, 1, 7, screen.query.ljust( width - 9 )[ : width - 9 ], width - 9,
             curses.A_BOLD )
    else:
        put( win, 1, 7, ( "a case: name, file or tag" if screen.page == "cases"
                          else "a command" ).ljust( width - 9 )[ : width - 9 ],
             width - 9, dim() )

    hint = screen.message or (
        "space ticks · ←→ picks · type into a field · enter runs · esc gives up"
        if screen.dialog is not None else
        "enter runs the first one · esc clears what you typed · ctrl-space ticks"
        if screen.query else HINTS[ screen.page ] )
    put( win, height - 1, 0, hint.ljust( width - 1 )[ : width - 1 ], width - 1,
         curses.color_pair( C_WARN ) if screen.message else dim() )
    if screen.dialog is not None:
        screen.dialog.draw( win )
    else:
        curses.curs_set( 0 )
        if screen.help:
            _help( win, height, width )
    win.noutrefresh()
    curses.doupdate()


def _help( win, height, width ):
    w, h = min( width - 4, 78 ), len( KEYS ) + 4
    y0, x0 = max( 0, ( height - h ) // 2 ), max( 0, ( width - w ) // 2 )
    for i in range( h ):
        put( win, y0 + i, x0, " " * w, w, curses.A_REVERSE )
    put( win, y0 + 1, x0 + 2, "keys", w - 4, curses.A_REVERSE | curses.A_BOLD )
    for i, ( key, what ) in enumerate( KEYS ):
        put( win, y0 + 2 + i, x0 + 2, f"{key:<10} {what}", w - 4, curses.A_REVERSE )
    put( win, y0 + h - 1, x0 + 2, "any key closes this", w - 4, curses.A_REVERSE )


def loop( win, screen: Screen ):
    curses.curs_set( 0 )
    if curses.has_colors():
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
        # Twice a second by itself, and at once after a key: a fold or a tick
        # that waited for the next tick to show would feel like a lost press.
        if now - screen.looked > LOOK or screen.dirty:
            screen.dirty = False
            if now - screen.looked > LOOK:
                screen.looked = now
                if screen.session.plan:
                    screen.session.look()
            screen.build_cases()
            screen.build_runs()
        screen.build_about()
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

        screen.message = ""
        screen.dirty   = True
        answer = _common( screen, key )
        if answer is None:
            answer = _list_key( screen, key )
        if answer == "quit":
            # A run started here belongs here: leaving would break the pipe
            # under it. Detaching is how work outlives a window.
            if screen.session.running:
                screen.message = ( "something is running: x interrupts it, "
                                   "or tick `detach` next time" )
            else:
                return 0


def _common( screen: Screen, key ):
    """What every page does the same way. -> "quit", "" when it acted, or None."""
    pane = screen.pane()
    if key == curses.KEY_MOUSE:
        try:
            _, x, y, _, state = curses.getmouse()
        except curses.error:
            return ""
        screen.mouse( y, x, state )
    elif key in ( curses.KEY_DOWN, 14 ):                 # ctrl-n, for while typing
        pane.move( 1 )
    elif key in ( curses.KEY_UP, 16 ):                   # ctrl-p
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
        screen.step( 1 )         # the next rectangle OF THIS PAGE
    elif key == curses.KEY_BTAB:
        screen.step( -1 )
    elif key in ( 10, 13, curses.KEY_ENTER ):
        screen.enter()
    elif key == curses.KEY_RIGHT:
        row = pane.current()
        if row is not None and row.open is False:
            screen.fold( row )
    elif key == curses.KEY_LEFT:
        row = pane.current()
        if row is not None and row.open:
            screen.fold( row )
    elif key == _f( 1 ):
        screen.help = True
    elif key == _f( 2 ):
        screen.turn( -1 )
    elif key == _f( 3 ):
        screen.turn( 1 )
    elif key == _f( 5 ):
        screen.run_last()
    elif key == _f( 6 ):
        screen.run_again()
    elif key == _f( 7 ):
        screen.message = screen.session.stop() or "interrupted"
    elif key == _f( 8 ):
        screen.open_file()
    elif key in ( _f( 9 ), 18 ):                         # ctrl-r
        screen.reread()
    elif key == _f( 12 ):
        return "quit"
    else:
        return None
    return ""


def _list_key( screen: Screen, key ):
    """**What you type is the search**, on either page. It is the fastest thing
    you can do with a keyboard, and finding one line among three hundred is
    what both these lists need.

    So `esc` clears what was typed -- the filter is the thing you most want
    gone -- and only then leaves. Space is a word separator while a search is
    on ( adding a word narrows, it does not rewrite ), and ctrl-space is the
    tick, as is a click straight on the box.
    """
    if key == 27:                                        # esc
        if screen.query:
            screen.typed( "" )
        else:
            return "quit"
    elif key in ( curses.KEY_BACKSPACE, 127, 8 ):
        screen.typed( screen.query[ : -1 ] )
    elif key == 0:                                       # ctrl-space
        screen.toggle_row()
    elif key == ord( " " ) and not screen.query:
        screen.toggle_row()
    elif 32 <= key < 127:
        screen.typed( screen.query + chr( key ) )
    return ""


def _dialog_key( screen: Screen, key ):
    dialog = screen.dialog
    if key == 27:
        screen.dialog = None
    elif key in ( 10, 13, curses.KEY_ENTER ):
        screen.dialog = None
        screen.launch( dialog.argv() )
    elif key == curses.KEY_MOUSE:
        try:
            _, x, y, _, state = curses.getmouse()
        except curses.error:
            return
        if state & PRESSED:
            dialog.click( y, x )
        elif state & WHEEL_UP:
            dialog.move( -1 )
        elif state & WHEEL_DOWN:
            dialog.move( 1 )
    elif key in ( curses.KEY_DOWN, 9 ):
        dialog.move( 1 )
    elif key in ( curses.KEY_UP, curses.KEY_BTAB ):
        dialog.move( -1 )
    elif key == curses.KEY_RIGHT:
        dialog.sideways( 1 )
    elif key == curses.KEY_LEFT:
        dialog.sideways( -1 )
    elif key == ord( " " ) and dialog.toggle():
        pass
    else:
        dialog.type( key )


def main( root: Path, out_root: Path ):
    import sys

    if not sys.stdout.isatty():
        print( "errand --tui needs a terminal", file = sys.stderr )
        return 2
    return curses.wrapper( loop, Screen( Session( root, out_root ).discover() ) ) or 0
