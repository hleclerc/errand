"""The dialog Enter opens on a case: where, with which tags, with which parameters.
"""
from __future__ import annotations

import contextlib
import curses

from ..session import Session
from .terminal import C_ACTIVE, C_OK, C_TITLE, dim
from .drawing import draw_box, put


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
