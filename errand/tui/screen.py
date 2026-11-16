"""The screen's state, and what a key does to it: no drawing here ( `loop` ).

Two panes: the machines and what they run on the left, the detail of the row under the cursor on
the right -- what it is, the files of its run, the end of its output, read again every 2 s.
"""
from __future__ import annotations

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
        self.shown    = 50                          # runs of a history shown
        self.only     = False                       # `p`: the current project only
        self.query    = ""
        self.typing   = False                       # `/` was pressed: keys go to the filter
        self.message  = ""
        self.confirm  = None                        # ( question, what to do on `y` )
        self.help     = False
        self.seen     : dict = { }                  # row key -> { "at", "files", "out", "error" }
        self.fetching : set = set()
        self.run_outside = None                     # set by the loop: runs argv with curses suspended

    # ── the lists ────────────────────────────────────────────────────────────

    def machine( self, name ):
        return next( m for m in self.machines if m.name == name )

    def build( self ):
        rows = R.build( self.machines, folded = self.folded, opened = self.opened, query = self.query,
                        only = self.mine if self.only else None, mine = self.mine, shown = self.shown )
        self.list.keep( rows, R.key )
        self.list.title = "machines" + ( f"  ·  {', '.join( sorted( self.mine ) )} only" if self.only else "" ) \
                          + ( f"  ·  /{self.query}" if self.query else "" )
        detail = self.describe( self.list.current() )
        if self.active == 0:
            # Looked at from the list, the detail shows the END of the output: the oldest lines go
            # first. Focused ( tab ), all of it is there to scroll through.
            extra = len( detail ) - self.detail.inner[ 2 ]
            if extra > 0:
                outs = [ i for i, r in enumerate( detail ) if r.kind == "out" ]
                cut = set( outs[ : extra ] )
                detail = [ r for i, r in enumerate( detail ) if i not in cut ]
        self.detail.keep( detail, lambda r: ( r.kind, r.label if r.kind == "file" else None ) )

    # ── the detail ───────────────────────────────────────────────────────────

    def describe( self, row ) -> list:
        """The rows of the detail pane, for the row under the cursor."""
        if row is None:
            return [ Row( "nothing here", kind = "note" ) ]
        machine, what = row.data if isinstance( row.data, tuple ) else ( None, None )
        m = self.machine( machine ) if machine else None
        out = [ Row( f"{k:<9} {v}" ) for k, v in R.facts( row, m ) ]
        if row.kind not in ( "proc", "run" ):
            return out
        self.fetch( row, m )
        got = self.seen.get( R.key( row ) )
        if got is None:
            out.append( Row( "reading…", kind = "note" ) )
            return out
        if got.get( "error" ):
            out.append( Row( f"cannot read: {got[ 'error' ]}", kind = "broken" ) )
        step = what.get( "step" ) if row.kind == "proc" else got.get( "step" )
        if row.kind == "run":
            out += [ Row( f"{k:<9} {v}" ) for k, v in R.step_facts( step, m.now() ) ]
        views = ( step or { } ).get( "views" ) or [ ]
        if views and what.get( "leaf" ):
            # What the run designated to be looked at as it evolves ( ADR 0010 ), before the files.
            out.append( Row( "", kind = "note" ) )
            out.append( Row( "views  ( enter opens one )", kind = "head" ) )
            for v in views:
                path = v[ "view" ] if v[ "view" ].startswith( "/" ) else f"{what[ 'leaf' ]}/{v[ 'view' ]}"
                out.append( Row( v.get( "title" ) or v[ "view" ], v[ "view" ] if v.get( "title" ) else "", kind = "file",
                                 data = ( m.name, path ) ) )
        if got.get( "files" ):
            out.append( Row( "", kind = "note" ) )
            out.append( Row( "files  ( enter opens one )", kind = "head" ) )
            for f in got[ "files" ]:
                out.append( Row( f[ "name" ], f"{_size( f[ 'size' ] )}  {R.ago( m.now() - f[ 'mtime' ] )}", kind = "file",
                                 data = ( m.name, f[ "path" ] ) ) )
        out.append( Row( "", kind = "note" ) )
        out.append( Row( f"output  {got.get( 'source' ) or ''}", kind = "head" ) )
        for text in ( got.get( "out" ) or "( nothing yet )" ).splitlines()[ -400 : ]:
            out.append( Row( text.replace( "\t", "    " ), kind = "out" ) )
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

    def toggle( self, row ):
        machine, what = row.data
        if row.kind in ( "machine", "broken" ):
            self.folded.symmetric_difference_update( { machine } )
        elif row.kind == "group":
            self.opened.symmetric_difference_update( { machine } )
        elif row.kind == "more":
            self.shown += 50

    def enter( self ):
        row = self.pane().current()
        if row is None:
            return
        if row.open is not None or row.kind == "more":
            self.toggle( row )
        elif row.kind == "file":
            self.page( row.data[ 0 ], row.data[ 1 ] )
        elif self.pane() is self.list:
            self.active = 1
        else:
            self.whole()

    def whole( self ):
        """`o`: the file under the cursor in the detail, or the whole output of the row in the list."""
        if self.pane() is self.detail:
            row = self.detail.current()
            if row is not None and row.kind == "file":
                return self.page( row.data[ 0 ], row.data[ 1 ] )
        row = self.list.current()
        if row is None or row.kind not in ( "proc", "run" ):
            self.message = "no output here"
            return
        got = self.seen.get( R.key( row ) ) or { }
        if not got.get( "path" ):
            self.message = "no output yet"
            return
        self.page( row.data[ 0 ], got[ "path" ] )

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

    def stop( self ):
        """`s`: what is under the cursor stops, once confirmed -- a process, or a VM's keeper."""
        row = self.list.current()
        try:
            m = self.machine( row.data[ 0 ] ) if row is not None else None
            req, said = R.stop_request( row, m )
        except ValueError as err:
            self.message = str( err )
            return

        def go():
            try:
                m.ask( req, timeout = 30 )
                self.message = f"stopping {said}: INT, then TERM, then KILL"
            except Exception as err:
                self.message = f"could not stop {said}: {err}"
            m.wake.set()

        self.confirm = ( f"stop {said}?  y stops it, any other key does not", lambda: threading.Thread( target = go, daemon = True ).start() )

    def refresh( self ):
        for m in self.machines:
            m.history_at = 0.0
            m.wake.set()
        self.seen.clear()
        self.message = "asking again"


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
    if path is None and what.get( "dir" ):
        path, source = f"{what[ 'dir' ]}/out", "the process's output"
    step = _step( m, leaf ) if leaf and any( f[ "name" ] == steps.FILE for f in files ) else None
    if path is None:
        return { "files": files, "out": "", "path": None, "step": step }
    got = m.ask( { "op": "tail", "path": path, "size": TAIL } )
    text = got[ "data" ]
    if got[ "offset" ]:
        text = text.split( "\n", 1 )[ -1 ]            # a line cut in two is not shown
    if source != "output.txt" and what.get( "dir" ):
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
