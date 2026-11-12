"""The `Lists` part of the screen: what each pane holds.
"""
from __future__ import annotations

from .. import fuzzy, session as S
from .tree import _id, _Node, _parts, short, size_of
from .panes import Row


# ── the screen ───────────────────────────────────────────────────────────────

class Lists:
    """What each pane holds, built from the session: the cases, what one is, the runs, their files, a preview."""

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
