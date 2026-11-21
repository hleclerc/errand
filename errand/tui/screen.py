"""The screen's state, and what a key does to it: no drawing here ( `loop` ).

Two panes: the machines and what they run on the left, the detail of the row under the cursor on
the right -- what it is, the files of its run, the end of its output, read again every 2 s.
"""
from __future__ import annotations

import re
from typing import NamedTuple

import shlex
import tempfile
import threading
import time
from pathlib import Path

from .. import steps
from . import rows as R
from .panes import Pane, Row

DETAIL = 2.0              # seconds between readings of the detail
TAIL   = 16384            # bytes of output shown
WHOLE  = 64 << 20         # at most this much is fetched for the pager
BROWSED = ( ".html", ".htm", ".svg" )     # opened in the browser rather than the pager
IMAGES  = ( ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".pdf", ".svg" )


class Confirm( NamedTuple ):
    """What waits for a yes, drawn as a window ( `loop._confirm` ): `title`, the `lines` of what it touches,
    `verb` the action ( enter does it ), `go` what does it, `danger` whether it ends work."""
    title  : str
    lines  : list
    verb   : str
    go     : object
    danger : bool = False


class Prompt( NamedTuple ):
    """A line to type, in a window ( `loop._prompt` ): `title`, the `text` so far, `go( text )` on enter.
    `fresh`: the text is the current value, as if selected: the first letter typed replaces it."""
    title : str
    text  : str
    go    : object
    fresh : bool = True


class Screen:
    def __init__( self, machines, mine = ( ) ):
        self.machines = machines
        self.mine     = set( mine )                 # the current project's names, highlighted
        self.list     = Pane( "list", "machines" )
        self.detail   = Pane( "detail", "detail" )
        self.panes    = [ self.list, self.detail ]
        self.active   = 0
        self.folded   : set = set()                 # machines whose rows are hidden
        self.opened   : set = set()                 # machines whose history is shown
        self.shown    = 50                          # runs of the history shown
        self.tab      = "runs"                      # or "machines", "caches": 1, 2, 3
        self.cache_days  = 30                       # caches: unused after this many days ( `n` )
        self.cache_every = False                    # caches: every entry, or the dead and unused only ( `v` )
        self.only     = False                       # `p`: the current project only
        self.query    = ""
        self.typing   = False                       # `/` was pressed: keys go to the filter
        self.message  = ""
        self.confirm  = None
        self.prompt   = None                        # a line typed in a window ( `rename` )                        # ( question, what to do on `y` )
        self.help     = False
        self.seen     : dict = { }                  # row key -> { "at", "files", "out", "error" }
        self.chosen   : dict = { }                  # row key -> the output looked at in the detail ( None: the console )
        self.peeked   : dict = { }                  # ( machine, path ) -> { "at", "text", "size", "error" }
        self.fetching : set = set()
        self.run_outside = None                     # set by the loop: runs argv with curses suspended
        self.marked   : set = set()                 # the runs' rows chosen together ( ⇧↑ ⇧↓ ), by key, for d and D
        self.anchor   = None                        # where they were chosen from
        self.poke     = lambda: None                # set by the loop: draw again now ( a thread said something )

    # ── the lists ────────────────────────────────────────────────────────────

    def machine( self, name ):
        return next( m for m in self.machines if m.name == name )

    def reader( self, row ) -> str | None:
        """the machine a row's files are read on: a run of this machine's record has its directory here ( ADR 0025 ),
        wherever it ran"""
        machine, what = row.data if isinstance( row.data, tuple ) else ( None, None )
        if row.kind == "run" and isinstance( what, dict ) and what.get( "rel" ) and not what.get( "there" ) or \
                ( machine and not any( m.name == machine for m in self.machines ) ):
            return next( ( m.name for m in self.machines if m.here ), machine )
        return machine

    def build( self ):
        if self.tab == "caches":
            from . import caches as K
            K.want( self.machines, entries = [ o[ 8 : ] for o in self.opened if isinstance( o, str ) and o.startswith( "entries:" ) ],
                    days = self.cache_days )
        for m in self.machines:                       # their gauges: measured while the machines tab is shown ( ADR 0024 )
            want = getattr( m, "want_resources", None )
            if want is not None:
                want( self.tab == "machines" )
        rows = R.build( self.machines, folded = self.folded, opened = self.opened, query = self.query,
                        only = self.mine if self.only else None, mine = self.mine, shown = self.shown, tab = self.tab,
                        days = self.cache_days, every = self.cache_every )
        self.list.keep( rows, R.key )
        if self.marked:
            keys = [ R.key( r ) for r in rows ]
            self.marked &= set( keys )
            self.list.marked = { i for i, k in enumerate( keys ) if k in self.marked } if len( self.marked ) > 1 else set()
        else:
            self.list.marked = set()
        self.list.title = { "runs": "running, waiting, done", "machines": "machines",
                            "caches": f"library caches  ·  unused: {self.cache_days:g} days"
                                      + ( "  ·  every entry" if self.cache_every else "" ) }[ self.tab ] \
                          + ( f"  ·  {', '.join( sorted( self.mine ) )} only" if self.only else "" ) \
                          + ( f"  ·  /{self.query}" if self.query else "" )
        detail = self._detail()
        self.detail.keep( detail, _detail_key )
        here = self.detail.current()
        row = self.list.current()
        if self.active == 1 and here is not None and here.kind == "output" and row is not None \
                and self.chosen.get( R.key( row ) ) != here.data[ 1 ]:
            self.chosen[ R.key( row ) ] = here.data[ 1 ]            # the cursor on an output: it is shown below
            self.detail.keep( self._detail(), _detail_key )

    def _detail( self ):
        detail = self.describe( self.list.current() )
        if self.active == 0:
            # Looked at from the list, the detail shows the END of the output: the oldest lines go
            # first. Focused ( tab ), all of it is there to scroll through.
            extra = len( detail ) - self.detail.inner[ 2 ]
            if extra > 0:
                outs = [ i for i, r in enumerate( detail ) if r.kind == "out" ]
                cut = set( outs[ : extra ] )
                detail = [ r for i, r in enumerate( detail ) if i not in cut ]
        return _number( detail )

    # ── the detail ───────────────────────────────────────────────────────────

    def describe( self, row ) -> list:
        """The rows of the detail pane, for the row under the cursor ( `detail_rows` ), its files and
        output read again in a thread ( `fetch` )."""
        if row is None:
            return [ Row( "nothing here", kind = "note" ) ]
        machine = self.reader( row )
        m = self.machine( machine ) if machine else None
        got = None
        if row.kind in ( "proc", "run" ):
            self.fetch( row, m )
            got = self.seen.get( R.key( row ) )
        chosen = self.chosen.get( R.key( row ) ) if self.active == 1 else None
        return detail_rows( row, m, got, self.preview( m, chosen ) if chosen is not None else None )

    def preview( self, m, path ) -> list:
        """The beginning of a file of the run, read through its agent ( again every `DETAIL` s )."""
        k = ( m.name, path )
        got = self.peeked.get( k )
        if k not in self.fetching and ( got is None or time.time() - got[ "at" ] >= DETAIL ):
            self.fetching.add( k )

            def read():
                try:
                    r = m.ask( { "op": "tail", "path": path, "offset": 0, "size": TAIL } )
                    self.peeked[ k ] = { "at": time.time(), "text": r.get( "data" ) or "", "size": r.get( "size", 0 ),
                                         "end": r.get( "end", 0 ), "missing": r.get( "missing" ) }
                except Exception as err:
                    self.peeked[ k ] = { "at": time.time(), "error": str( err ).strip().splitlines()[ -1 ] if str( err ).strip() else type( err ).__name__ }
                finally:
                    self.fetching.discard( k )

            threading.Thread( target = read, daemon = True ).start()
        name = path.rsplit( "/", 1 )[ -1 ]
        out = [ Row( f"▸ {name}", kind = "chead" ) ]
        if got is None:
            return out + [ Row( "  reading…", kind = "note" ) ]
        if got.get( "error" ) or got.get( "missing" ):
            return out + [ Row( f"  cannot read: {got.get( 'error' ) or 'gone'}", kind = "broken" ) ]
        text = got[ "text" ]
        if name.lower().endswith( IMAGES ):
            return out + [ Row( f"  an image, {_size( got[ 'size' ] )}: enter opens it", kind = "note" ) ]
        if "\x00" in text or text.count( "\ufffd" ) > max( 8, len( text ) // 50 ):
            return out + [ Row( f"  binary, {_size( got[ 'size' ] )}: enter opens it", kind = "note" ) ]
        lines = text.replace( "\t", "    " ).splitlines()
        if got[ "end" ] < got[ "size" ] and len( lines ) > 1:
            lines = lines[ : -1 ]                               # a line cut in two is not shown
        out += [ Row( f"  │ {line}", kind = "out", data = i ) for i, line in enumerate( lines ) ] or [ Row( "  │ ( empty )", kind = "out", data = 0 ) ]
        if got[ "end" ] < got[ "size" ]:
            out.append( Row( f"  ┆ … {_size( got[ 'size' ] - got[ 'end' ] )} more ( enter, o, e: all of it )", kind = "note" ) )
        return out

    def fetch( self, row, m ):
        """Read the files and the output of `row` again, in a thread, if the last reading is old."""
        k = R.key( row )
        got = self.seen.get( k )
        if k in self.fetching or ( got and time.time() - got[ "at" ] < DETAIL ):
            return
        self.fetching.add( k )
        what = row.data[ 1 ]

        def read():
            try:
                self.seen[ k ] = { "at": time.time(), **_read( m, what ) }
            except Exception as err:
                self.seen[ k ] = { "at": time.time(), "error": str( err ).strip().splitlines()[ -1 ] if str( err ).strip() else type( err ).__name__ }
            finally:
                self.fetching.discard( k )

        threading.Thread( target = read, daemon = True ).start()

    # ── what a key does ──────────────────────────────────────────────────────

    def pane( self ):
        return self.panes[ self.active ]

    def select( self, tab: str ):
        """`1`, `2`: a tab ( runs, machines ), the cursor at its top."""
        if tab != self.tab:
            self.tab = tab
            self.list.cursor = self.list.top = 0
        self.active = 0

    def toggle( self, row ):
        machine, what = row.data
        if row.kind == "cache":
            self.folded.symmetric_difference_update( { ( "cache", what[ "cache" ] ) } )
        elif row.kind == "centries":
            self.opened.symmetric_difference_update( { f"entries:{what[ 'cache' ]}" } )
        elif row.kind in ( "machine", "broken" ):
            self.folded.symmetric_difference_update( { machine } )
        elif row.kind == "group":
            self.opened.symmetric_difference_update( { machine } )
        elif row.kind == "day":
            self.folded.symmetric_difference_update( { ( "day", what ) } )
        elif row.kind in ( "tnode", "tset" ):            # the runs' tree ( ADR 0023 ): folded until opened, busy ones open
            k = f"t:{what[ 'tree' ]}"
            if row.open:
                self.opened.discard( k ); self.folded.add( k )
            else:
                self.folded.discard( k ); self.opened.add( k )
        elif row.kind == "more":
            self.shown += 50

    def fold( self, unfold: bool ):
        """`→` unfolds the row under the cursor, `←` folds it -- or, on a row inside, goes up to what holds it."""
        pane = self.pane()
        row = pane.current()
        if row is None or pane is not self.list:
            return
        if row.open is not None and row.open != unfold:
            self.toggle( row )
        elif not unfold and row.open is None:
            i = pane.cursor
            while i > 0:                                    # the heading above: a machine, a day
                i -= 1
                if pane.rows[ i ].open is not None and ( pane.rows[ i ].depth < row.depth or row.depth == 0 ):
                    pane.cursor = i
                    pane.reveal()
                    break
        elif unfold and row.open:
            pane.move( 1 )

    def enter( self ):
        row = self.pane().current()
        if row is None:
            return
        if row.open is not None or row.kind == "more":
            self.toggle( row )
        elif row.kind == "output":
            self.open_output( *row.data )
        elif self.pane() is self.list:
            self.active = 1
        else:
            self.whole()

    def _local( self, machine, path ):
        """`path` of `machine` as a file here: itself, or a copy fetched through its agent. None when it cannot be."""
        m = self.machine( machine )
        if m.here:
            return path
        try:
            return str( _fetch( m, path ) )
        except Exception as err:
            self.message = f"cannot read {path}: {err}"
            return None

    def _console_path( self ):
        row = self.list.current()
        got = self.seen.get( R.key( row ) ) or { } if row is not None else { }
        if not got.get( "path" ):
            self.message = "no output yet"
        return got.get( "path" )

    def open_output( self, machine, path ):
        """Enter on an output: opened by what opens it here ( `open`, `xdg-open` ); the console in the pager."""
        import subprocess
        import sys
        if path is None:
            path = self._console_path()
            if path:
                self.page( machine, path )
            return
        local = self._local( machine, path )
        if local is None:
            return
        try:
            subprocess.Popen( [ "open" if sys.platform == "darwin" else "xdg-open", local ], stdin = subprocess.DEVNULL,
                              stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL, start_new_session = True )
            self.message = f"opened {Path( path ).name}" + ( "" if self.machine( machine ).here else f" ( a copy: {local} )" )
        except OSError as err:
            self.message = f"cannot open {local}: {err}"

    def edit( self ):
        """`e`: the output under the cursor in `$VISUAL` / `$EDITOR`; a copy, when it is on another machine."""
        import os
        row = self.detail.current() if self.pane() is self.detail else None
        if row is None or row.kind != "output":
            self.message = "e: tab to the detail, on an output"
            return
        machine, path = row.data[ : 2 ]
        if path is None:
            path = self._console_path()
            if not path:
                return
        local = self._local( machine, path )
        if local is None:
            return
        editor = shlex.split( os.environ.get( "VISUAL" ) or os.environ.get( "EDITOR" ) or "vi" )
        self.run_outside( [ *editor, local ] )
        if not self.machine( machine ).here:
            self.message = f"that was a copy ( {local} ): {machine} keeps its own"

    def whole( self ):
        """`o`: the file under the cursor in the detail, or the whole output of the row in the list."""
        if self.pane() is self.detail:
            row = self.detail.current()
            if row is not None and row.kind == "output" and row.data[ 1 ] is not None:
                return self.page( row.data[ 0 ], row.data[ 1 ] )
        row = self.list.current()
        if row is None or row.kind not in ( "proc", "run" ):
            self.message = "no output here"
            return
        got = self.seen.get( R.key( row ) ) or { }
        if not got.get( "path" ):
            self.message = "no output yet"
            return
        self.page( self.reader( row ), got[ "path" ] )

    def page( self, machine, path ):
        """A file in `$PAGER`, fetched first when it is on another machine."""
        import os
        m = self.machine( machine )
        if not m.here:
            try:
                local = _fetch( m, path )
            except Exception as err:
                self.message = f"cannot read {path}: {err}"
                return
        else:
            local = path
        if str( local ).endswith( BROWSED ):
            import sys
            self.run_outside( [ "open" if sys.platform == "darwin" else "xdg-open", str( local ) ] )
            return
        pager = shlex.split( os.environ.get( "PAGER" ) or "less -R" )
        self.run_outside( [ *pager, str( local ) ] )

    def shell( self ):
        """`x`: a shell where the row under the cursor works, on its machine."""
        import os
        row = self.list.current()
        if row is None:
            return
        machine, what = row.data
        m = self.machine( machine )
        where = None
        if isinstance( what, dict ):
            where = what.get( "leaf" ) if row.kind == "run" else what.get( "project" ) or what.get( "cwd" )
        if m.here:
            self.run_outside( [ os.environ.get( "SHELL" ) or "sh" ], cwd = where if where and Path( where ).is_dir() else None )
            return
        from ..layers.gateways import ssh_options
        go = f"cd {shlex.quote( where )} 2>/dev/null; " if where else ""
        self.run_outside( [ "ssh", "-t", *ssh_options( m.target.get( "options" ) ), m.target[ "host" ],
                            go + 'exec "${SHELL:-sh}" -l' ] )

    def kill( self ):
        """`k`: what is under the cursor is killed, once confirmed -- a process, a VM's keeper, or, on a
        machine's row, everything errand runs there ( `actions.kill_plan` )."""
        from . import actions as A
        row = self.list.current()
        try:
            m = self.machine( row.data[ 0 ] ) if row is not None and isinstance( row.data, tuple ) and row.data[ 0 ] else None
            plan = A.kill_plan( row, m )
        except ValueError as err:
            self.message = str( err )
            return

        def go():
            def run():
                self.message = A.send( plan )
            threading.Thread( target = run, daemon = True ).start()

        self.confirm = Confirm( plan.title, plan.lines, "kill", go, danger = True )

    def forget( self ):
        """`f`: the machine under the cursor is not asked any more, once confirmed ( `actions.forget` ):
        out of the list until work is sent there again. Nothing over there stops."""
        from . import actions as A
        row = self.list.current()
        if row is None or row.kind not in ( "machine", "broken", "dormant" ):
            self.message = "put the cursor on a machine"
            return
        m = self.machine( row.data[ 0 ] )
        if m.here:
            self.message = "this machine is always shown: nothing to forget"
            return

        def go():
            self.message = A.forget( m, self.machines )

        self.confirm = Confirm( f"forget {m.name}?", A.forget_lines( m ), "forget", go )

    def rename( self ):
        """`r`: the machine of the row under the cursor -- a machine, or a run or a process on it -- shown under
        another name, every name it is reached by alike. This machine too: its hostname until then."""
        from . import actions as A
        row = self.list.current()
        machine = row.data[ 0 ] if row is not None and isinstance( row.data, tuple ) else None
        if machine is None:
            self.confirm = Confirm( "nothing to name here", [ "r names a machine: put the cursor on it,",
                                                            "or on a run or a process of it" ], "close", lambda: None )
            return
        m = self.machine( machine )

        def go( label ):
            self.message = A.rename( m, label )

        self.prompt = Prompt( A.rename_title( m ), m.name, go )

    def check_runs( self ):
        """`c` in the runs tab: the other machines asked for the runs they hold that this one's record does not
        ( ADR 0025 ), from a thread; found, they are listed at their place, marked"""
        from . import rows as R

        def run():
            try:
                self.message = R.check( self.machines )
            except Exception as err:
                self.message = f"check: {err}"
            self.poke()
        self.message = "checking the other machines…"
        threading.Thread( target = run, daemon = True ).start()

    def bring_back( self ):
        """`b` in the runs tab: a run the check found on another machine only, brought here"""
        from . import rows as R
        row = self.list.current()
        what = row.data[ 1 ] if row is not None and isinstance( row.data, tuple ) else None
        if row is None or row.kind != "run" or not isinstance( what, dict ) or not what.get( "there" ):
            self.message = "b: on a run the check found on another machine only"
            return
        m = self.machine( row.data[ 0 ] )

        def run():
            try:
                self.message = R.bring_back( m, what )
            except Exception as err:
                self.message = f"bring back: {err}"
            self.poke()
        self.message = "bringing it back…"
        threading.Thread( target = run, daemon = True ).start()

    def extend( self, delta: int ):
        """⇧↓ ⇧↑ in the runs tab: the rows from where it started to the cursor, chosen together ( for d, D )"""
        pane = self.list
        if self.tab != "runs" or self.active != 0 or not pane.rows:
            return
        keys = [ R.key( r ) for r in pane.rows ]
        if not self.marked or self.anchor not in keys:
            self.anchor = keys[ pane.cursor ]
        pane.move( delta )
        a = keys.index( self.anchor )
        lo, hi = sorted( ( a, pane.cursor ) )
        self.marked = set( keys[ lo : hi + 1 ] )
        pane.marked = set( range( lo, hi + 1 ) ) if hi > lo else set()

    def unmark( self ) -> bool:
        had = bool( self.marked )
        self.marked, self.list.marked = set(), set()
        return had

    def remove_runs( self, how: str ):
        """`d` / `D` in the runs tab: the runs under the row ( or the rows chosen together ) removed, or all but the
        latest of each set, once confirmed. The window at once ( `removal.plan` asks nobody ), the room freed in it when
        the machines said it ( `measure`, from a thread ); yes: the runs greyed, removed from a thread. For good."""
        from . import removal as RM
        pane = self.list
        chosen = [ r for r in pane.rows if R.key( r ) in self.marked ] if len( self.marked ) > 1 else [ pane.current() ]
        chosen = [ r for r in chosen if r is not None and r.kind in ( "run", "tnode", "tset", "thead" ) and r.mark != "going" ]
        try:
            r = RM.plan( chosen, self.machines, how )
        except ValueError as err:
            self.message = str( err )
            return

        def measure():
            try:
                RM.measure( r )
            except Exception as err:
                r.lines[ : ] = r.lines + [ f"the room freed: not known ( {err} )" ]
            c = self.confirm
            if c is not None and c.lines is r.lines:      # ( its window still shown: with the count the machines said )
                self.confirm = c._replace( title = r.title )
            self.poke()
        threading.Thread( target = measure, daemon = True ).start()

        def go():
            RM.mark( r )
            self.unmark()
            n = r.count
            self.message = f"removing {n} run{'s' if n > 1 else ''}…"

            def run():
                try:
                    self.message = RM.send( r )
                except Exception as err:
                    self.message = f"remove: {err}"
                self.poke()
            threading.Thread( target = run, daemon = True ).start()

        self.confirm = Confirm( r.title, r.lines, "remove for good", go, danger = True )

    def sort_column( self ):
        """`s` in the runs tab: the parameter table under the cursor sorted by its next column ( each column up, then
        down ), its header found above the row"""
        pane = self.list
        i = pane.cursor
        while i >= 0 and pane.rows[ i ].kind not in ( "thead", ) and pane.rows[ i ].kind in ( "tset", "run" ):
            i -= 1
        if i < 0 or pane.rows[ i ].kind != "thead":
            self.message = "s: on a table of parameters, to sort it"
            return
        what = pane.rows[ i ].data[ 1 ]
        cols = [ c[ 0 ] for c in what[ "cols" ] ]
        pre = f"s:{what[ 'tree' ]}="
        now = next( ( o[ len( pre ) : ] for o in self.opened if isinstance( o, str ) and o.startswith( pre ) ), None )
        self.opened -= { o for o in self.opened if isinstance( o, str ) and o.startswith( pre ) }
        if now is None:
            nxt = cols[ 0 ]
        elif not now.startswith( "-" ):
            nxt = "-" + now
        else:
            j = cols.index( now[ 1 : ] ) if now[ 1 : ] in cols else -1
            nxt = cols[ ( j + 1 ) % len( cols ) ]
        self.opened.add( pre + nxt )
        self.message = f"sorted by {nxt.lstrip( '-' )} {'down' if nxt.startswith( '-' ) else 'up'}"

    def browse( self ):
        """`w`: the page of the run under the cursor in the browser ( `errand web`: its dashboard ), with a code used once
        ( no cookie needed ). From a thread: the page may have to be started."""
        row = self.list.current()
        what = row.data[ 1 ] if row is not None and isinstance( row.data, tuple ) and isinstance( row.data[ 1 ], dict ) else { }
        if row is None or row.kind not in ( "proc", "run" ) or not what.get( "leaf" ):
            self.message = "w: on a run, to open its page"
            return

        def go():
            from ..cli.render import _browse
            from ..web import run_link
            try:
                link = run_link( what[ "leaf" ], start = True )
            except Exception:
                link = None
            if not link:
                self.message = "no page served here ( errand web )"
                return
            _browse( link )
            self.message = f"opened {link}"
        self.message = "opening its page…"
        threading.Thread( target = go, daemon = True ).start()

    def activate( self ):
        """`a`: a machine not contacted, contacted from now on; one contacted, its gauges off or on ( `actions.toggle_watch` )."""
        from . import actions as A
        row = self.list.current()
        if row is None or row.kind not in ( "machine", "broken", "dormant" ):
            self.message = "a: on a machine, to watch it, or its gauges off or on"
            return
        try:
            self.message = A.toggle_watch( self.machine( row.data[ 0 ] ) )
        except ValueError as err:
            self.message = str( err )

    def remove_cached( self, how: str ):
        """`i`, `u`, `d`, `D` in the caches tab: what goes, once confirmed ( `caches.plan` ), removed from a thread."""
        from . import caches as K
        try:
            r = K.plan( self.list.current(), how, self.machines, self.cache_days )
        except ValueError as err:
            self.message = str( err )
            return

        def go():
            def run():
                self.message = K.send( r )
                K.want( self.machines, days = self.cache_days, force = True )
            threading.Thread( target = run, daemon = True ).start()

        self.confirm = Confirm( r.title, r.lines, "remove", go, danger = True )

    def hold_cached( self ):
        """`h` in the caches tab: the machine of the place under the cursor holds its directory, once confirmed."""
        from . import caches as K
        try:
            r = K.hold_plan( self.list.current(), self.machines )
        except ValueError as err:
            self.message = str( err )
            return

        def go():
            def run():
                self.message = K.send( r )
                K.want( self.machines, days = self.cache_days, force = True )
            threading.Thread( target = run, daemon = True ).start()

        self.confirm = Confirm( r.title, r.lines, "hold", go )

    def ask_cache_days( self ):
        """`n`: the days after which an entry counts as unused."""
        def go( text ):
            try:
                days = float( text )
                assert days > 0
            except ( ValueError, AssertionError ):
                self.message = f"{text!r}: a number of days, above 0"
                return
            self.cache_days = days
            self.message = f"unused: not used for {days:g} days"
        self.prompt = Prompt( "unused after how many days?", f"{self.cache_days:g}", go )

    def refresh( self ):
        for m in self.machines:
            m.caches_at = 0.0
            m.history_at = 0.0
            m.wake.set()
        self.seen.clear()
        self.message = "asking again"


def detail_rows( row, m, got, preview = None ) -> list:
    """What the detail says of `row` ( a row of the list, on machine `m` ): its facts; for a run or a
    process, its step, its views, its outputs ( the console, then its files ), and the console itself --
    or `preview`, the rows of the output chosen. `got`: what `_read` read of it, None while it is read.
    Shared by `errand tui` and `errand web`."""
    what = row.data[ 1 ] if isinstance( row.data, tuple ) else None
    out = [ Row( f"{k:<9} {v}", data = ( k, v ) ) for k, v in R.facts( row, m ) ]
    if row.kind not in ( "proc", "run" ):
        return out
    if got is None:
        out.append( Row( "reading…", kind = "note" ) )
        return out
    if got.get( "error" ):
        out.append( Row( f"cannot read: {got[ 'error' ]}", kind = "broken" ) )
    step = what.get( "step" ) if row.kind == "proc" else got.get( "step" )
    if row.kind == "run":
        out += [ Row( f"{k:<9} {v}", data = ( k, v ) ) for k, v in R.step_facts( step, m.now() ) ]
    # The outputs ( ADR 0017 §5 ): what it printed, as `errand run` draws it, first; then what is made to be looked at --
    # the views the run designated ( ADR 0010 ), its pages, images, documents, its bundles ( `foam.sviz/`: one line, with
    # its state ) -- in the order they appeared; then its other files; apart, at the end, the files errand writes in
    # every run ( `OWN` ). The one under the cursor ( tab to get there ) is shown below; enter opens it, e edits it.
    out.append( Row( "", kind = "note" ) )
    out.append( Row( "outputs", "", kind = "head" ) )
    rich, plain = outputs( m, what, step, got.get( "files" ) or [ ] )
    own = [ r for r in plain if r.label in OWN ]
    out.append( Row( "console", got.get( "source" ) or "", kind = "output", data = ( m.name, None ) ) )
    out += rich + [ r for r in plain if r.label not in OWN ]
    if own:                                             # always there, seldom read: apart, at the end
        out.append( Row( "", kind = "note" ) )
        out.append( Row( "errand's files", "", kind = "head" ) )
        out += own
    out.append( Row( "", kind = "note" ) )
    out += console( row, got ) if preview is None else preview
    return out


OWN  = ( "stdout.txt", "stderr.txt", "steps.jsonl", "result.yaml", "launch.yaml", "summary.yaml" )   # what errand writes in every run
RICH = ( ".html", ".htm", ".svg", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm" )


def _rich( name: str ) -> bool:
    """an output made to be looked at ( a page, an image, a document, a video ): before the others. Each view draws
    its own icons, from the name ( `web/page.py`: `iconOf` )"""
    return name.lower().endswith( RICH )


def outputs( m, what: dict, step, files: list ) -> tuple:
    """`( rich, plain )`: the rows of a run's outputs. `rich`: its views, pages, images, documents and bundles, in the
    order they appeared; a bundle -- a directory of the leaf with an extension -- is one row, with
    its state when its `manifest.json` says one ( `bundle_state` ). `plain`: its other files, newest first."""
    leaf = what.get( "leaf" )
    now = m.now()
    rich, plain, seen = [ ], [ ], set()
    bundles = { }                                     # name -> ( mtime of its newest file, its files )
    for f in files:
        top, sep, _ = f[ "name" ].partition( "/" )
        if sep and "." in top.strip( "." ):
            b = bundles.setdefault( top, [ 0.0, [ ] ] )
            b[ 0 ] = max( b[ 0 ], f[ "mtime" ] )
            b[ 1 ].append( f )
    by_path = { f[ "path" ]: f for f in files }
    first = { }                                        # what appeared when: a view when the journal said it
    for v in ( step or { } ).get( "views" ) or [ ]:
        if not leaf:
            break
        path = _in_leaf( v[ "view" ], leaf )
        name = v[ "view" ].rsplit( "/", 1 )[ -1 ]
        if path in seen:
            continue
        seen.add( path )
        shown = v.get( "title" ) or name                                    # its name, not where it is
        f = by_path.get( path )
        top = path[ len( leaf ) + 1 : ].partition( "/" )[ 0 ] if path.startswith( f"{leaf}/" ) else None
        if top in bundles and path == f"{leaf}/{top}":
            detail = bundle_state( m, path, bundles[ top ][ 1 ], bundles[ top ][ 0 ], now )
        else:
            detail = name if v.get( "title" ) else f"{_size( f[ 'size' ] )}  {R.ago( now - f[ 'mtime' ] )}" if f else ""
        served = _served( m, leaf, path, v.get( "open" ) )
        # to be looked at ( the run's dashboard, `web/page.py` ): a page served as it is, or a file that shows itself
        if served:
            look = { "url": served[ 0 ], "look": "static", "ready": served[ 1 ] }
        elif _rich( name ):
            look = { "look": "file", "ready": f is not None }
        else:
            look = None
        if look:
            look[ "t" ] = v.get( "t" ) or 0.0
        first[ path ] = ( v.get( "t" ) or 0.0, Row( shown, detail, kind = "output",
                                                    data = ( m.name, path ) + ( ( look, ) if look else ( ) ) ) )
    for name, ( mtime, fs ) in bundles.items():
        path = f"{leaf}/{name}"
        if path in seen:
            continue
        seen.add( path )
        first[ path ] = ( min( f[ "mtime" ] for f in fs ),
                          Row( name, bundle_state( m, path, fs, mtime, now ), kind = "output", data = ( m.name, path ) ) )
    for f in files:
        if f[ "name" ] == "output.txt" or f[ "path" ] in seen:
            continue                                    # the console is it; a view said already
        top, sep, _ = f[ "name" ].partition( "/" )
        if sep and top in bundles:
            continue                                    # inside a bundle: the bundle's row is it
        detail = f"{_size( f[ 'size' ] )}  {R.ago( now - f[ 'mtime' ] )}"
        if _rich( f[ "name" ] ):
            first[ f[ "path" ] ] = ( f[ "mtime" ], Row( f[ "name" ], detail, kind = "output", data = ( m.name, f[ "path" ] ) ) )
        else:
            plain.append( Row( f[ "name" ], detail, kind = "output", data = ( m.name, f[ "path" ] ) ) )
    rich = [ r for _, r in sorted( first.values(), key = lambda tr: tr[ 0 ] ) ]
    return rich, plain


def _served( m, leaf: str, path: str, opens ) -> tuple | None:
    """`( url, ready )` of a view opened as it is ( `errand.Static` ), when its copy is served here ( `web.static` ): the
    one the side that drove the run registered, or, for a run of this machine, the directory itself. Ready: its server
    answers, its index is here, and, a store, its first frame ( a `frames/` with a file )."""
    static = next( ( o for o in opens or [ ] if isinstance( o, dict ) and "static" in o ), None )
    if static is None or not path.startswith( f"{leaf}/" ):
        return None
    try:
        from ..web import static as S
        vid = S.view_id( leaf, path[ len( leaf ) + 1 : ] )
        if vid not in S.registered():
            if not ( m.here and Path( path ).is_dir() ):
                return None
            S.register( vid, path )
        here = Path( S.registered()[ vid ] )
        frames = here / "frames"
        ready = S.serving() and ( here / static[ "static" ] ).is_file() and \
            ( not frames.is_dir() or next( frames.iterdir(), None ) is not None )
        return S.url( vid, static[ "static" ] ), bool( ready )
    except Exception:
        return None


def _in_leaf( view: str, leaf: str ) -> str:
    """where a view is, in the leaf's own spelling: a path said absolute by the run ( `/home/h/Projects-rsync/…/<leaf>/x` )
    may name the leaf through a link ( `/data/Projects-rsync/…` ): the same file, one row"""
    if not view.startswith( "/" ):
        return f"{leaf}/{view}"
    mark = f"/{leaf.rstrip( '/' ).rsplit( '/', 1 )[ -1 ]}/"
    return f"{leaf}/{view.split( mark, 1 )[ 1 ]}" if mark in view and not view.startswith( f"{leaf}/" ) else view


def bundle_state( m, path: str, files: list, mtime: float, now: float ) -> str:
    """What a bundle says of itself: `331 frames`, `· running` while its manifest is not `complete` ( a scene store,
    ADR 0017 ); else its size. Two small reads of its `manifest.json` through the agent: its head ( `complete` ) and
    its end ( the last frame's file )."""
    import re
    size = _size( sum( f[ "size" ] for f in files ) )
    if not any( f[ "name" ].endswith( "/manifest.json" ) for f in files ):
        return f"{size}  {R.ago( now - mtime )}"
    try:
        head = m.ask( { "op": "tail", "path": f"{path}/manifest.json", "offset": 0, "size": 512 } )[ "data" ]
        end = m.ask( { "op": "tail", "path": f"{path}/manifest.json", "size": 4096 } )[ "data" ]
    except Exception:
        return f"{size}  {R.ago( now - mtime )}"
    last = re.findall( r'"frames/(\d+)\.bin"', end )
    frames = f"{int( last[ -1 ] ) + 1} frames" if last else ""
    running = '"complete":false' in head.replace( " ", "" )
    return "  ".join( x for x in ( frames, "running" if running else "", R.ago( now - mtime ) ) if x )


def _detail_key( r ):
    """The detail's rows kept across rebuilds: an output by its name, a fact by its name, a line of text
    by its place -- each the n-th of its kind ( `_number` )."""
    return r.ident


def _number( rows ):
    seen = { }
    for r in rows:
        if r.kind in ( "output", "file" ):
            k = ( r.kind, r.label )
        elif r.kind == "out":
            k = ( r.kind, r.data )
        else:
            k = ( r.kind, r.label.split( " ", 1 )[ 0 ] if r.label else "" )
        seen[ k ] = seen.get( k, -1 ) + 1
        r.ident = ( *k, seen[ k ] )
    return rows


def console( row, got ) -> list:
    """A run's output as `errand run` drew it ( ADR 0016 ): its header, its lines behind the gutter, its
    end -- what was read of `output.txt`, the end of it when it is long."""
    what = row.data[ 1 ] or { }
    name = what.get( "what" ) or "?"
    out = [ Row( f"▸ {name}" + ( f"  {what[ 'env' ]}" if what.get( "env" ) else "" ), kind = "chead" ) ]
    text = ( got.get( "out" ) or "" ).replace( "\t", "    " )
    lines = text.splitlines()
    if len( lines ) > 400:
        out.append( Row( f"  ┆ … {len( lines ) - 400} lines before ( o: all of it )", kind = "note" ) )
    empty = "( no output )" if what.get( "status" ) else "( nothing yet )"
    for i, line in enumerate( drawn( lines[ -400 : ] ) or ( [ empty ] if row.kind == "run" else [ ] ) ):
        out.append( Row( f"  │ {line}", kind = "out", data = i ) )
    if row.kind == "run" and what.get( "status" ):
        took = f"  {R.ago( what[ 'duration' ] )}" if what.get( "duration" ) is not None else ""
        out.append( Row( f"  ╰ {what[ 'status' ]} {name}{took}", kind = "cend", data = what[ "status" ] ) )
    return out


ROW_HEAD = "\033[38;5;75m"           # the head of a row, as `errand run` draws it ( `cli.render.ROW` )
_OSC = re.compile( r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)" )


def drawn( lines: list ) -> list:
    """Lines of `output.txt` as `errand run` drew them: a row ( `errand.row` ) at the widths of the rows of the whole
    output, its head coloured; any other escape a terminal shows nothing of ( an OSC ) taken out. Colours ( SGR ) stay:
    the page draws them, the TUI takes them out ( `drawing` )."""
    from .. import rows as RW
    table, parsed = RW.Table(), [ RW.parse( l ) for l in lines ]
    for p in parsed:
        if p:
            table.add( *p )
    return [ table.draw( *p, ROW_HEAD ) if p else _OSC.sub( "", l ) for l, p in zip( lines, parsed ) ]


def _size( n ) -> str:
    for unit in ( "B", "kB", "MB", "GB" ):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000


def _read( m, what: dict ) -> dict:
    """The files of a run's leaf, and the end of its output: `output.txt` in the leaf if it has one,
    the process's own output otherwise."""
    leaf = what.get( "leaf" )
    files, path, source = [ ], None, None
    if leaf:
        files = [ { **f, "path": f"{leaf}/{f[ 'name' ]}" } for f in m.ask( { "op": "ls", "path": leaf } )[ "files" ] ]
        if any( f[ "name" ] == "output.txt" for f in files ):
            path, source = f"{leaf}/output.txt", "output.txt"
    if path is None and what.get( "dir" ) and what.get( "kind" ) == "agent":
        # a bridge to an environment agent: its stdout is the protocol ( binary frames ), its stderr what it says
        path, source = f"{what[ 'dir' ]}/err", "the bridge's stderr"
    elif path is None and what.get( "dir" ):
        path, source = f"{what[ 'dir' ]}/out", "the process's output"
    step = _step( m, leaf ) if leaf and any( f[ "name" ] == steps.FILE for f in files ) else None
    if path is None:
        return { "files": files, "out": "", "path": None, "step": step }
    got = m.ask( { "op": "tail", "path": path, "size": TAIL } )
    text = got[ "data" ]
    if got[ "offset" ]:
        text = text.split( "\n", 1 )[ -1 ]            # a line cut in two is not shown
    if source == "the process's output":
        err = m.ask( { "op": "tail", "path": f"{what[ 'dir' ]}/err", "size": TAIL } )
        if err[ "data" ].strip():
            text += "\n── stderr ──\n" + err[ "data" ]
    return { "files": files, "out": text, "path": path, "source": source, "step": step }


def _step( m, leaf: str ) -> dict | None:
    """The summary of a run's journal ( ADR 0010 ), from its two ends, as `steps.summary` reads it."""
    path = f"{leaf}/{steps.FILE}"
    head = m.ask( { "op": "tail", "path": path, "offset": 0, "size": steps.EDGE } )
    data = head[ "data" ]
    if head.get( "end", 0 ) < head.get( "size", 0 ):
        start = max( head[ "end" ], head[ "size" ] - steps.EDGE )
        tail = m.ask( { "op": "tail", "path": path, "offset": start, "size": steps.EDGE } )
        if start == head[ "end" ]:
            data += tail[ "data" ]                          # the rest, right after the head
        else:
            data = data.rsplit( "\n", 1 )[ 0 ] + "\n" + tail[ "data" ].split( "\n", 1 )[ -1 ]
    return steps.summarize( steps.parse( data ) )


def _fetch( m, path: str ) -> Path:
    """A file of another machine, copied here for the pager, in pieces through its agent."""
    local = Path( tempfile.mkdtemp( prefix = "errand-tui-" ) ) / Path( path ).name
    offset = 0
    with open( local, "w" ) as f:
        while offset < WHOLE:
            got = m.ask( { "op": "tail", "path": path, "offset": offset } )
            if got.get( "missing" ):
                raise FileNotFoundError( "gone" )
            f.write( got[ "data" ] )
            offset = got[ "end" ]
            if got[ "end" ] == got[ "offset" ] or offset >= got[ "size" ]:
                break
    return local
