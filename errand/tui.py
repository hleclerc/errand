"""`errand --tui`: a screen for choosing what to run, and watching it happen.

The only part of errand that has a dependency, and the only one that may: it is
built on `textual` ( `pip install "errand-run[tui]"` ). The core cannot afford
one -- it builds the environments the work runs in, so it has to run before any
environment exists -- but a screen is not on that path, and writing a second
terminal toolkit by hand to save an install nobody is forced to do would be a
poor trade.

Everything that is not drawing lives in `session.py`, which has no textual in
it and is tested without a terminal. What is here is the view: three lists, a
pane facing each, and one dialog.

**The dialog is where a matrix is written.** Enter on a case opens it; cases,
environments, tag values and parameter values are all boxes you tick, and
ticking two of anything is the comma that would have said the same thing on a
command line. Enter runs it.
"""
from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, Log, SelectionList, Static, TabbedContent,
    TabPane,
)
from textual.widgets.selection_list import Selection

from . import session as S
from .session import Session

LOOK = 0.5           # seconds between askings of the output tree


def short( path, root ):
    try:
        return str( Path( path ).relative_to( root ) )
    except ValueError:
        return str( path )


# ── the dialog ───────────────────────────────────────────────────────────────

class Launch( ModalScreen[ dict ] ):
    """Every dimension of one run, in one window.

    Nothing here is remembered between openings on purpose: what you ticked
    last time is not what you mean this time, and a dialog that quietly keeps
    an old environment ticked is a dialog that runs something you did not ask
    for.
    """

    BINDINGS = [
        Binding( "escape", "cancel", "cancel" ),
        Binding( "enter", "run", "run", priority = True ),
        Binding( "ctrl+b", "detach", "detach" ),
    ]

    def __init__( self, session: Session, chosen ):
        super().__init__()
        self.session = session
        self.chosen  = list( chosen )

    def compose( self ) -> ComposeResult:
        s = self.session
        with Vertical( id = "dialog" ):
            yield Label( "run", classes = "title" )
            with Horizontal( classes = "columns" ):
                with Vertical( classes = "column" ):
                    yield Label( "cases", classes = "section" )
                    yield SelectionList[ int ](
                        *[ Selection( e.name, i, e in self.chosen )
                           for i, e in enumerate( s.entries ) ],
                        id = "cases" )
                with Vertical( classes = "column" ):
                    if s.envs:
                        yield Label( "environments", classes = "section" )
                        yield SelectionList[ str ](
                            *[ Selection( e.name, e.name, False ) for e in s.envs ],
                            id = "envs" )
                    for name, values in sorted( s.tag_values().items() ):
                        yield Label( f"--{name}", classes = "section" )
                        yield SelectionList[ str ](
                            *[ Selection( v, v, False ) for v in values ],
                            id = f"tag-{name}", classes = "tags" )
                with Vertical( classes = "column" ):
                    yield Label( "parameters", classes = "section" )
                    yield Vertical( id = "params" )
                    yield Label( "at once", classes = "section" )
                    yield Input( value = "1", id = "jobs", classes = "tiny" )
            yield Static( "", id = "preview", classes = "dim", markup = False )
            with Horizontal( id = "buttons" ):
                yield Button( "run", variant = "primary", id = "do-run" )
                yield Button( "detach", id = "do-detach" )
                yield Button( "cancel", id = "do-cancel" )

    def on_mount( self ):
        self.rebuild_params()
        self.refresh_preview()
        self.query_one( "#cases", SelectionList ).focus()

    # The parameters follow the cases: they are the flags those entries
    # declare, so ticking another case may bring another flag with it.
    def rebuild_params( self ):
        holder = self.query_one( "#params", Vertical )
        holder.remove_children()
        params = self.session.params_of( self.picked_entries() or self.session.entries )
        if not params:
            holder.mount( Static( "none declared", classes = "dim" ) )
            return
        for name, param in params.items():
            flag = f"--{name.replace( '_', '-' )}"
            if param.choices:
                holder.mount( Label( flag, classes = "section" ) )
                holder.mount( SelectionList[ str ](
                    *[ Selection( str( v ), str( v ), False ) for v in param.choices ],
                    id = f"choice-{name}", classes = "tags" ) )
            else:
                holder.mount( Label( f"{flag}   {param.help}".rstrip(), classes = "section" ) )
                holder.mount( Input( placeholder = str( param.default ),
                                     id = f"param-{name}", classes = "param" ) )

    def picked_entries( self ):
        try:
            picked = self.query_one( "#cases", SelectionList ).selected
        except Exception:
            return [ ]
        return [ self.session.entries[ i ] for i in picked ]

    def argv( self, detach = False ):
        tags   = { }
        params = { }
        for widget in self.query( SelectionList ):
            if widget.id and widget.id.startswith( "tag-" ):
                tags[ widget.id[ 4 : ] ] = list( widget.selected )
            elif widget.id and widget.id.startswith( "choice-" ):
                params[ widget.id[ 7 : ] ] = list( widget.selected )
        for widget in self.query( Input ):
            if widget.id and widget.id.startswith( "param-" ) and widget.value.strip():
                params[ widget.id[ 6 : ] ] = [ widget.value.strip() ]
        envs = list( self.query_one( "#envs", SelectionList ).selected ) if self.session.envs else [ ]
        jobs = self.query_one( "#jobs", Input ).value.strip() or "1"
        return self.session.command(
            entries = self.picked_entries(), envs = envs, tags = tags, params = params,
            jobs = int( jobs ) if jobs.isdigit() else 1, batch = detach )

    def refresh_preview( self ):
        # Shown, but small and out of the way: it is what this window is about
        # to do, not something anybody is being asked to type.
        self.query_one( "#preview", Static ).update( self.session.as_line( self.argv() ) )

    @on( SelectionList.SelectedChanged )
    def touched( self, event ):
        if event.selection_list.id == "cases":
            self.rebuild_params()
        self.refresh_preview()

    @on( Input.Changed )
    def typed( self, _ ):
        self.refresh_preview()

    @on( Button.Pressed, "#do-run" )
    def action_run( self, _ = None ):
        self.dismiss( { "argv": self.argv() } )

    @on( Button.Pressed, "#do-detach" )
    def action_detach( self, _ = None ):
        self.dismiss( { "argv": self.argv( detach = True ) } )

    @on( Button.Pressed, "#do-cancel" )
    def action_cancel( self, _ = None ):
        self.dismiss( { } )


class Files( ModalScreen[ dict ] ):
    """What a run wrote. Enter hands one to the desktop."""

    BINDINGS = [ Binding( "escape", "close", "close" ) ]

    def __init__( self, paths, root ):
        super().__init__()
        self.paths = list( paths )
        self.root  = root

    def compose( self ) -> ComposeResult:
        with Vertical( id = "dialog" ):
            yield Label( "files", classes = "title" )
            table = DataTable( id = "files", cursor_type = "row" )
            table.add_columns( "name", "size", "where" )
            yield table
            yield Static( "enter opens it, escape closes", classes = "dim" )

    def on_mount( self ):
        table = self.query_one( "#files", DataTable )
        for path in self.paths:
            try:
                size = f"{path.stat().st_size:,}"
            except OSError:
                size = "-"
            table.add_row( path.name, size, short( path.parent, self.root ) )
        if not self.paths:
            table.add_row( "( nothing written )", "", "" )
        table.focus()

    @on( DataTable.RowSelected )
    def chosen( self, event ):
        if event.cursor_row < len( self.paths ):
            why = S.open_file( self.paths[ event.cursor_row ] )
            self.app.notify( why or f"opening {self.paths[ event.cursor_row ].name}",
                             severity = "warning" if why else "information" )

    def action_close( self ):
        self.dismiss( { } )


# ── the screen ───────────────────────────────────────────────────────────────

class Errand( App ):
    CSS = """
    Screen { background: $surface; }
    TabbedContent { height: 1fr; }
    .pane { height: 1fr; }
    .list { width: 46%; border-right: tall $panel; }
    .detail { width: 1fr; padding: 0 1; }
    .dim { color: $text-muted; }
    #filter { display: none; dock: top; }
    #filter.on { display: block; }
    DataTable { height: 1fr; }
    Log { height: 1fr; }

    #dialog {
        width: 90%; max-width: 120; height: auto; max-height: 90%;
        border: round $accent; background: $surface; padding: 1 2;
    }
    #dialog .title { text-style: bold; color: $accent; width: 1fr; }
    #dialog .section { color: $accent; margin-top: 1; }
    #dialog .columns { height: auto; }
    #dialog .column { width: 1fr; height: auto; padding-right: 2; }
    #dialog SelectionList { height: auto; max-height: 10; background: $surface; }
    #dialog Input { width: 24; }
    #dialog .tiny { width: 8; }
    #dialog #preview { margin-top: 1; }
    #dialog #buttons { height: auto; margin-top: 1; align-horizontal: right; }
    #dialog Button { margin-left: 2; }
    #dialog #files { height: auto; max-height: 20; }
    """

    BINDINGS = [
        Binding( "slash", "filter", "filter" ),
        Binding( "escape", "unfilter", "clear filter", show = False ),
        Binding( "o", "files", "files" ),
        Binding( "x", "stop", "stop" ),
        Binding( "d", "reread", "reread" ),
        Binding( "q", "leave", "quit" ),
    ]

    def __init__( self, session: Session ):
        super().__init__()
        self.session = session
        self.rows    : list = [ ]      # what the cases table shows, in its order
        self.lines   : list = [ ]      # what the history table shows, in its order
        self.shown   = None            # what the output pane is already showing
        self.past    : dict = { }      # history line -> its plan, worked out once

    def compose( self ) -> ComposeResult:
        yield Header( show_clock = False )
        with TabbedContent( id = "tabs" ):
            with TabPane( "cases", id = "tab-cases" ):
                yield Input( placeholder = "filter…", id = "filter" )
                with Horizontal( classes = "pane" ):
                    yield DataTable( id = "cases", cursor_type = "row", classes = "list" )
                    # markup off: what goes in there is a traceback or somebody
                    # else's help text, and a square bracket in it is a square
                    # bracket.
                    yield VerticalScroll( Static( id = "about", markup = False ),
                                          classes = "detail" )
            with TabPane( "runs", id = "tab-runs" ):
                with Horizontal( classes = "pane" ):
                    yield DataTable( id = "runs", cursor_type = "row", classes = "list" )
                    yield Log( id = "out", classes = "detail" )
            with TabPane( "history", id = "tab-history" ):
                with Horizontal( classes = "pane" ):
                    yield DataTable( id = "history", cursor_type = "row", classes = "list" )
                    yield VerticalScroll( Static( id = "past", markup = False ),
                                          classes = "detail" )
        yield Footer()

    def on_mount( self ):
        self.title = "errand"
        self.sub_title = str( self.session.root )
        self.query_one( "#cases", DataTable ).add_columns( " ", "case", "where", "tags" )
        self.query_one( "#runs", DataTable ).add_columns( " ", "case", "env", "what" )
        self.query_one( "#history", DataTable ).add_columns( "command" )
        self.fill_cases()
        self.fill_history()
        self.set_interval( LOOK, self.tick )

    # ── the lists ────────────────────────────────────────────────────────────

    def fill_cases( self ):
        table = self.query_one( "#cases", DataTable )
        table.clear()
        self.rows = [ ]
        needle = self.query_one( "#filter", Input ).value.strip().lower()
        root = self.session.root
        for e in sorted( self.session.entries, key = lambda e: ( str( e.file ), e.line ) ):
            text = f"{e.name} {e.file} {' '.join( e.tags )}".lower()
            if needle and needle not in text:
                continue
            self.rows.append( ( "entry", e ) )
            table.add_row( e.kind[ : 4 ], e.name, f"{short( e.file, root )}:{e.line}",
                           " ".join( e.tags ) )
        # Loudly, at the end: a file that declares work and would not import is
        # not a detail, and an empty list is a poor way of saying so.
        for path, why, trace in self.session.broken:
            self.rows.append( ( "broken", ( path, why, trace ) ) )
            table.add_row( "!", short( path, root ), why[ : 40 ], "" )
        if not self.rows:
            table.add_row( "", "nothing declares work here", "", "" )
        self.show_about()

    def fill_history( self ):
        table = self.query_one( "#history", DataTable )
        table.clear()
        self.lines = self.session.history()
        for line in self.lines:
            table.add_row( line )
        if not self.lines:
            table.add_row( "nothing run from here yet" )

    def tick( self ):
        alive = self.session.running
        if self.session.plan:
            self.session.look()
            self.fill_runs()
        self.sub_title = ( f"{self.session.root}   "
                           + ( "running" if alive else
                               "following" if self.session.record else "idle" ) )
        self.show_output()

    def fill_runs( self ):
        table = self.query_one( "#runs", DataTable )
        where = table.cursor_row
        table.clear()
        # The command itself gets the first row. What it says on its way --
        # building an environment, an rsync, waiting for the machine to be free
        # -- belongs to no single case, and is where trouble shows up first.
        table.add_row( "$", self.session.command_line or "nothing launched yet", "",
                       "running" if self.session.running else "" )
        for state in self.session.states:
            table.add_row( S.MARKS[ S.mark_of( state ) ], S.labelled( state ),
                           state[ "env" ], S.detail_of( state ) )
        if where is not None:
            table.move_cursor( row = min( where, len( self.session.states ) ) )

    # ── the pane facing each ─────────────────────────────────────────────────

    def show_about( self ):
        target = self.query_one( "#about", Static )
        row = self.current( "cases" )
        if row is None:
            target.update( "" )
            return
        kind, payload = row
        if kind == "broken":
            path, why, trace = payload
            target.update( f"{path}\n\n{why}\n\n{trace}" )
            return
        e = payload
        out = [ f"{short( e.file, self.session.root )}:{e.line}", f"kind: {e.kind}" ]
        if e.tags:
            out.append( "tags: " + ", ".join( e.tags ) )
        if e.resources:
            out.append( "needs: " + ", ".join( f"{k}={v}" for k, v in e.resources.items() ) )
        traits = [ k for k, v in e.traits.items() if v ]
        if traits:
            out.append( "traits: " + " ".join( traits ) )
        for name, p in e.params.items():
            out.append( "" )
            out.append( f"--{name.replace( '_', '-' )}   default {p.default!r}"
                        + ( f"   choices {p.choices}" if p.choices else "" ) )
            if p.help:
                out.append( f"  {p.help}" )
        out += [ "", "enter to run it" ]
        target.update( "\n".join( out ) )

    def show_output( self ):
        """The pane facing a case is the file that case is writing -- and facing
        the command, what the command itself is saying.

        Redrawn only when it has moved: this is called twice a second, and a
        pane that rewrote itself every time could never be scrolled back.
        """
        if self.query_one( "#tabs", TabbedContent ).active != "tab-runs":
            return
        state = self.current_run()
        if state is None:
            lines = list( self.session.log ) or [ "nothing launched yet" ]
            key = ( "the command", len( lines ) )
        else:
            lines = self.session.tail( state[ "output" ] ) or [ "nothing written yet" ]
            key = ( str( state[ "output" ] ), len( lines ) )
        if key != self.shown:
            log = self.query_one( "#out", Log )
            log.clear()
            log.write_lines( lines )
            self.shown = key

    def show_past( self ):
        target = self.query_one( "#past", Static )
        line = self.current_line()
        if line is None:
            target.update( "" )
            return
        plan = self.past.get( line )
        if plan is None:
            plan = self.past[ line ] = self.session.predict( self.session.args_of( line ) )
        states = self.session.states_of( plan )        # nobody here started these
        out = [ line, "" ]
        for state in states:
            out.append( f"{S.MARKS[ S.mark_of( state ) ]:5} {S.labelled( state, True )}"
                        f"   {S.detail_of( state )}" )
        last = next( ( s for s in reversed( states ) if s.get( "output" ) ), None )
        if last:
            out += [ "", *self.session.tail( last[ "output" ] )[ -60 : ] ]
        files = [ p for s in states for p in self.session.files_of( s.get( "dir" ) ) ]
        if files:
            out += [ "", f"{len( files )} file(s) -- o to open one" ]
        out += [ "", "enter runs it again" ]
        target.update( "\n".join( out ) )

    # ── what the cursor is on ────────────────────────────────────────────────

    def current( self, table_id ):
        table = self.query_one( f"#{table_id}", DataTable )
        index = table.cursor_row
        return self.rows[ index ] if 0 <= index < len( self.rows ) else None

    def current_run( self ):
        """None on the first row, which is the command and not a case."""
        index = self.query_one( "#runs", DataTable ).cursor_row - 1
        states = self.session.states
        return states[ index ] if 0 <= index < len( states ) else None

    def current_line( self ):
        index = self.query_one( "#history", DataTable ).cursor_row
        return self.lines[ index ] if 0 <= index < len( self.lines ) else None

    @on( DataTable.RowHighlighted, "#cases" )
    def moved_cases( self, _ ):
        self.show_about()

    @on( DataTable.RowHighlighted, "#runs" )
    def moved_runs( self, _ ):
        self.shown = None
        self.show_output()

    @on( DataTable.RowHighlighted, "#history" )
    def moved_history( self, _ ):
        self.show_past()

    @on( Input.Changed, "#filter" )
    def filtering( self, _ ):
        self.fill_cases()

    # ── doing things ─────────────────────────────────────────────────────────

    @on( DataTable.RowSelected, "#cases" )
    def open_dialog( self, _ = None ):
        row = self.current( "cases" )
        if row is None or row[ 0 ] != "entry":
            return
        self.push_screen( Launch( self.session, [ row[ 1 ] ] ), self.launch )

    @on( DataTable.RowSelected, "#history" )
    def again( self, _ = None ):
        line = self.current_line()
        if line:
            self.launch( { "argv": self.session.args_of( line ) } )

    @on( DataTable.RowSelected, "#runs" )
    def run_files( self, _ = None ):
        self.action_files()

    def launch( self, answer ):
        argv = ( answer or { } ).get( "argv" )
        if not argv:
            return
        why = self.session.launch( argv )
        if why:
            self.notify( why, severity = "warning" )
            return
        self.past.clear()
        self.query_one( "#tabs", TabbedContent ).active = "tab-runs"
        self.shown = None
        self.fill_runs()
        self.fill_history()

    def action_files( self ):
        active = self.query_one( "#tabs", TabbedContent ).active
        if active == "tab-runs":
            state = self.current_run()
            paths = self.session.files_of( state.get( "dir" ) ) if state else [ ]
        elif active == "tab-history":
            line = self.current_line()
            plan = self.past.get( line ) if line else None
            paths = [ p for s in self.session.states_of( plan or [ ] )
                      for p in self.session.files_of( s.get( "dir" ) ) ]
        else:
            paths = [ ]
        self.push_screen( Files( paths, self.session.root ) )

    def action_filter( self ):
        field = self.query_one( "#filter", Input )
        self.query_one( "#tabs", TabbedContent ).active = "tab-cases"
        field.add_class( "on" )
        field.focus()

    def action_unfilter( self ):
        field = self.query_one( "#filter", Input )
        field.value = ""
        field.remove_class( "on" )
        self.query_one( "#cases", DataTable ).focus()
        self.fill_cases()

    def action_stop( self ):
        self.notify( self.session.stop() or "interrupted" )

    def action_reread( self ):
        self.session.discover()
        self.past.clear()
        self.fill_cases()
        self.notify( f"{len( self.session.entries )} case(s)"
                     + ( f", {len( self.session.broken )} unreadable file(s)"
                         if self.session.broken else "" ) )

    def action_leave( self ):
        # A run started from here belongs to here: leaving would break the pipe
        # under it and kill it halfway. Detaching is how work outlives a window.
        if self.session.running:
            self.notify( "something is running: x interrupts it, "
                         "ctrl+b in the dialog detaches", severity = "warning" )
            return
        self.exit( 0 )


def main( root: Path, out_root: Path ):
    session = Session( root, out_root ).discover()
    return Errand( session ).run() or 0
