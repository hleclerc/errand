"""`errand --tui`: a screen for choosing what to run, and watching it happen.

Three rules hold the whole thing up.

**It runs nothing itself.** Every launch goes through an errand command line --
the one written at the bottom of the screen -- started as an ordinary child.
There is nothing the screen can do that the shell cannot, nothing it knows that
the command line does not, and what you learn here you can type tomorrow. The
screen is a way of WRITING a command and of READING what it produced.

**It reads the output tree, not the pipe.** The paths were worked out before
the run started, so each case's output is a file with a name this side already
knows: the pane facing a case is that file. Which is why it works the same for
eight cases at once under `-j`, for a run on another machine, and for a batch
job submitted yesterday -- three situations in which a single pipe of
interleaved lines says nothing about any particular case.

**A box you can tick is a matrix.** Ticking two environments, two values of a
tag and two values of a parameter asks for eight runs, for exactly the reason a
comma does on the command line -- and it produces exactly that comma.
"""
from __future__ import annotations

import contextlib
import curses
import io
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from . import batch, cli, config, discovery, history, layers as L, results as R, yamlish

DRAW  = 0.2      # seconds between redraws
LOOK  = 0.5      # seconds between askings of the output tree
PULL  = 5.0      # seconds between fetches of a remote submission
TAIL  = 64 * 1024


# ── the little pieces ────────────────────────────────────────────────────────

class Row:
    """One line of a list. `item` can be ticked, `text` can be typed into,
    `head` is neither -- a heading, so that a parameter's values sit under the
    parameter they belong to."""

    __slots__ = ( "label", "detail", "kind", "data", "checked", "mark" )

    def __init__( self, label, detail = "", *, kind = "item", data = None, checked = False,
                  mark = None ):
        self.label, self.detail, self.kind, self.data, self.checked = (
            label, detail, kind, data, checked )
        # What stands where the box would be, for a row that is not a choice:
        # a run is watched, not ticked, and offering to tick it would be a lie.
        self.mark = mark


class Panel:
    def __init__( self, key, name ):
        self.key, self.name = key, name
        self.rows   : list = [ ]
        self.cursor = 0
        self.top    = 0
        self.filter = ""

    def shown( self ):
        if not self.filter:
            return self.rows
        needle = self.filter.lower()
        return [ r for r in self.rows
                 if needle in r.label.lower() or needle in r.detail.lower() or r.kind == "head" ]

    def current( self ):
        rows = self.shown()
        return rows[ self.cursor ] if 0 <= self.cursor < len( rows ) else None

    def move( self, delta ):
        """A heading is passed over, never landed on: it is the name of a file
        or of a parameter, and there is nothing to do to it."""
        rows = self.shown()
        if not rows:
            return
        step = 1 if delta >= 0 else -1
        target = max( 0, min( len( rows ) - 1, self.cursor + delta ) )
        while 0 <= target < len( rows ) and rows[ target ].kind == "head":
            target += step
        if 0 <= target < len( rows ):
            self.cursor = target
        elif rows[ self.cursor ].kind == "head":
            self.first()

    def first( self ):
        for i, r in enumerate( self.shown() ):
            if r.kind != "head":
                self.cursor = i
                return

    def clamp( self ):
        self.cursor = max( 0, min( max( 0, len( self.shown() ) - 1 ), self.cursor ) )
        row = self.current()
        if row is not None and row.kind == "head":
            self.first()

    # A filter hides rows, it never unticks them: narrowing the list to find
    # one more case must not quietly drop the seven already chosen.
    def ticked( self ):
        return [ r for r in self.rows if r.kind == "item" and r.checked ]

    def set_all( self, value ):
        for r in self.shown():
            if r.kind == "item":
                r.checked = value

    def invert( self ):
        for r in self.shown():
            if r.kind == "item":
                r.checked = not r.checked


def tail_of( path: Path, cache: dict ):
    """The last of a file, re-read only when it has moved."""
    try:
        stat = path.stat()
    except OSError:
        return [ ]
    token = ( str( path ), stat.st_mtime_ns, stat.st_size )
    got = cache.get( str( path ) )
    if got and got[ 0 ] == token:
        return got[ 1 ]
    try:
        with open( path, "rb" ) as handle:
            if stat.st_size > TAIL:
                handle.seek( stat.st_size - TAIL )
            data = handle.read().decode( "utf-8", "replace" )
    except OSError:
        return [ ]
    lines = data.splitlines()
    if stat.st_size > TAIL and lines:
        lines = lines[ 1 : ]           # the first line was cut in half
    cache[ str( path ) ] = ( token, lines )
    return lines


def wrap( lines, width ):
    out = [ ]
    for line in lines:
        line = line.replace( "\t", "    " )
        if not line:
            out.append( "" )
        while line:
            out.append( line[ : width ] )
            line = line[ width : ]
    return out


# ── the screen ───────────────────────────────────────────────────────────────

class Screen:
    def __init__( self, root: Path, out_root: Path ):
        self.root, self.out_root = root, out_root
        self.entries  : list = [ ]
        self.panels   : list = [ ]
        self.focus    = 0
        # What has been ticked lives HERE and not on the rows: the lists are
        # rebuilt every time the tree is asked what has happened, and a choice
        # that lived only on a row would be lost twice a second.
        self.chosen   : set  = set()    # entries, by ( file, line, name )
        self.on_envs  : set  = set()    # environment names
        self.picks    : dict = { }      # ( "tag" | "choice", name ) -> [ values ]
        self.values   : dict = { }      # parameter name -> what was typed, commas and all
        self.seen_batches : set = set()
        self.expr_e   = ""              # -e, over entries
        self.expr_t   = ""              # -t, over environments
        self.jobs     = 1
        self.message  = ""
        self.noise    = ""              # whatever discovery printed
        self.child    = None
        self.command  = ""
        self.log      = deque( maxlen = 4000 )
        self.plan     : list = [ ]
        self.record   : dict | None = None     # a submission this screen adopted
        self.started  = 0.0
        self.states   : list = [ ]
        self.looked   = 0.0
        self.cache    : dict = { }
        self.offset   = 0               # how far the output pane is scrolled back
        self.help     = False

    # ── what there is to choose from ─────────────────────────────────────────

    def discover( self ):
        """Read the project: its config, its entries, its environments.

        Everything this prints is swallowed and kept: importing the files that
        declare work runs their module level, which is allowed to talk, and a
        stray `print` must not tear a hole in the screen.
        """
        buf = io.StringIO()
        self.entries = [ ]
        with contextlib.redirect_stdout( buf ), contextlib.redirect_stderr( buf ):
            try:
                config.load( self.root, warn = lambda m: print( f"warning: {m}" ) )
                cli._put_src_on_path( self.root )
                self.entries, _, _ = discovery.select(
                    None, self.root, bulk_only = False, exclude = config.settings.exclude,
                    providers = config.providers )
            except Exception as err:                       # a broken file, a bad config
                print( f"{type( err ).__name__}: {err}" )
        self.noise = buf.getvalue().strip()
        if self.noise:
            self.message = self.noise.splitlines()[ -1 ][ : 200 ]
        self.build()

    def build( self ):
        keep = { p.name: ( p.cursor, p.filter ) for p in self.panels }
        self.panels = [ self._entries(), self._envs(), self._tags(), self._params(),
                        self._runs(), self._history() ]
        for p in self.panels:
            if p.name in keep:
                p.cursor, p.filter = keep[ p.name ]
            else:
                p.first()
            p.clamp()

    def _entries( self ):
        p = Panel( "1", "entries" )
        last = None
        for e in sorted( self.entries, key = lambda e: ( str( e.file ), e.line ) ):
            if e.file != last:
                last = e.file
                p.rows.append( Row( str( _short( e.file, self.root ) ), kind = "head" ) )
            detail = f"{e.kind}:{e.line}" + ( "  " + " ".join( e.tags ) if e.tags else "" )
            p.rows.append( Row( e.name, detail, data = e, checked = _id( e ) in self.chosen ) )
        return p

    def _envs( self ):
        p = Panel( "2", "envs" )
        for name, e in config.envs.items():
            tags = " ".join( k if v is True else f"{k}={v}" for k, v in sorted( e.tags.items() ) )
            p.rows.append( Row( name, tags, data = e, checked = name in self.on_envs ) )
        if not p.rows:
            p.rows.append( Row( "( none declared -- work runs in this interpreter )",
                                kind = "head" ) )
        return p

    def _tags( self ):
        """One row per ( dimension, value ) an environment actually declares.

        `fp = "32|64"` is two values, because that is what it means: an
        environment that says it can do both is offered for both.
        """
        p = Panel( "3", "tags" )
        p.rows.append( Row( "-t  environments", self.expr_t, kind = "text", data = "t" ) )
        p.rows.append( Row( "-e  entries", self.expr_e, kind = "text", data = "e" ) )
        seen: dict = { }
        for e in config.envs.values():
            for name, value in e.tags.items():
                values = seen.setdefault( name, [ ] )
                for v in ( [ "yes" ] if value is True else str( value ).split( "|" ) ):
                    if v.strip() and v.strip() not in values:
                        values.append( v.strip() )
        for name in sorted( seen ):
            p.rows.append( Row( f"--{name}", kind = "head" ) )
            for value in seen[ name ]:
                p.rows.append( Row( f"  {value}", data = ( "tag", name, value ),
                                    checked = value in self.picks.get( ( "tag", name ), [ ] ) ) )
        return p

    def _params( self ):
        """The parameters of the entries that are ticked -- or of all of them
        while nothing is, since that is what a bare command would run."""
        p = Panel( "4", "params" )
        chosen = [ e for e in self.entries if _id( e ) in self.chosen ]
        for e in ( chosen or self.entries ):
            for name, param in e.params.items():
                if any( r.data == ( "param", name ) or
                        ( isinstance( r.data, tuple ) and r.data[ : 2 ] == ( "choice", name ) )
                        for r in p.rows ):
                    continue
                flag = f"--{name.replace( '_', '-' )}"
                if param.choices:
                    p.rows.append( Row( flag, f"default {param.default!r}  {param.help}",
                                        kind = "head" ) )
                    for value in param.choices:
                        p.rows.append( Row(
                            f"  {value}", data = ( "choice", name, str( value ) ),
                            checked = str( value ) in self.picks.get( ( "choice", name ), [ ] ) ) )
                else:
                    p.rows.append( Row( flag, self.values.get( name, "" ) or
                                        f"default {param.default!r}  {param.help}",
                                        kind = "text", data = ( "param", name ) ) )
        if not p.rows:
            p.rows.append( Row( "( the chosen entries declare no parameters )", kind = "head" ) )
        return p

    def _runs( self ):
        p = Panel( "5", "runs" )
        p.rows.append( Row( "the command", self.command or "( nothing launched yet )",
                            kind = "plain", data = ( "log", ), mark = "$" ) )
        # The environment is written on the row only when there is more than
        # one: what a list has to show is what TELLS the rows apart, and a
        # column repeating the same word in every line tells nothing.
        several = len( { st[ "env" ] for st in self.states } ) > 1
        for state in self.states:
            p.rows.append( Row( _labelled( state, several ), _detail( state ), kind = "plain",
                                data = ( "run", state ), mark = MARKS[ _mark( state ) ] ) )
        return p

    def _history( self ):
        p = Panel( "6", "history" )
        for line in reversed( history.load( self.root ) ):
            p.rows.append( Row( line, kind = "plain", data = ( "history", line ), mark = "" ) )
        if not p.rows:
            p.rows.append( Row( "( nothing run from here yet )", kind = "head" ) )
        return p

    def _panel( self, name ):
        return next( p for p in self.panels if p.name == name )

    def again( self, name ):
        """Rebuild one list in place, keeping where the cursor was."""
        index = [ p.name for p in self.panels ].index( name )
        was = self.panels[ index ]
        fresh = getattr( self, f"_{name}" )()
        fresh.cursor, fresh.filter = was.cursor, was.filter
        fresh.clamp()
        self.panels[ index ] = fresh

    def panel( self ):
        return self.panels[ self.focus ]

    # ── the command being written ────────────────────────────────────────────

    def pattern( self ):
        chosen = [ e for e in self.entries if _id( e ) in self.chosen ]
        if not chosen:
            return ""
        parts = [ ]
        for path in dict.fromkeys( e.file for e in chosen ):
            mine  = [ e for e in chosen if e.file == path ]
            whole = [ e for e in self.entries if e.file == path ]
            # Every case of a file is the file: shorter, and it stays true when
            # a case is added to it tomorrow.
            if len( mine ) == len( whole ):
                parts.append( path.stem )
            else:
                parts += [ f"{path.stem}::{e.name}" for e in mine ]
        return ",".join( dict.fromkeys( parts ) )

    def argv( self ):
        out = [ ]
        pattern = self.pattern()
        if pattern:
            out.append( pattern )
        names = [ n for n in config.envs if n in self.on_envs ]
        if names:
            out += [ "--env", ",".join( names ) ]
        # A tag and a parameter reach the command line the same way, because a
        # comma means the same thing on both: several values is a matrix.
        for ( _, name ), values in sorted( self.picks.items() ):
            if values:
                out += [ f"--{name.replace( '_', '-' )}", ",".join( values ) ]
        for name, raw in sorted( self.values.items() ):
            if raw.strip():
                out += [ f"--{name.replace( '_', '-' )}", raw.strip() ]
        if self.expr_e:
            out += [ "-e", self.expr_e ]
        if self.expr_t:
            out += [ "-t", self.expr_t ]
        if self.jobs > 1:
            out += [ "-j", str( self.jobs ) ]
        return out

    def line( self ):
        return " ".join( [ "errand", *( shlex.quote( a ) for a in self.argv() ) ] )

    # ── launching, and watching ──────────────────────────────────────────────

    def launch( self, args ):
        if self.child is not None and self.child.poll() is None:
            self.message = "something is already running -- x stops it"
            return
        self.plan    = self.predict( args )
        self.states  = [ ]
        self.record  = None
        self.started = time.time()
        self.offset  = 0
        self.log.clear()
        self.command = " ".join( [ "errand", *( shlex.quote( a ) for a in args ) ] )
        self.seen_batches = { r[ "id" ] for r in batch.load_all( self.root ) }
        try:
            self.child = subprocess.Popen(
                [ sys.executable, "-m", "errand", *args ], cwd = self.root,
                env = { **os.environ, "PYTHONUNBUFFERED": "1", "NO_COLOR": "1" },
                stdout = subprocess.PIPE, stderr = subprocess.STDOUT, text = True, bufsize = 1 )
        except OSError as err:
            self.message = f"could not start: {err}"
            return
        threading.Thread( target = self._drain, args = ( self.child, ), daemon = True ).start()
        self.build()
        self.focus = [ p.name for p in self.panels ].index( "runs" )
        self._panel( "runs" ).cursor = 0

    def _drain( self, child ):
        for line in child.stdout:
            self.log.append( line.rstrip( "\n" ) )
        child.stdout.close()

    def predict( self, args ):
        """Where the command about to run will write, worked out by the very
        code that will run it -- `plan_of`, the same function the batch ledger
        is built from. A screen that guessed differently would watch the wrong
        files, and would be believed."""
        noise = io.StringIO()
        try:
          with contextlib.redirect_stdout( noise ), contextlib.redirect_stderr( noise ):
            parser = cli.build_parser( config.tag_names() )
            known, _ = parser.parse_known_args( args )
            pattern = cli.positional_of( parser, args )
            kinds = { cli.KINDS[ k ] for k in known.kind if k in cli.KINDS }
            entries, _, _ = discovery.select(
                pattern, self.root, kinds = kinds, entry_tags = known.entry_tags,
                bulk_only = not pattern and not kinds, exclude = config.settings.exclude,
                providers = config.providers )
            declared = { }
            for e in entries:
                declared.update( e.params )
            for name in declared:
                parser.add_argument( f"--{name.replace( '_', '-' )}", dest = name, type = str,
                                     default = None )
            parsed = parser.parse_args( args )
            combos = cli.expand( { n: getattr( parsed, n, None ) for n in declared }, declared )
            targets = cli._targets( parsed, config.tag_names() )
            return cli.plan_of( targets, entries, combos,
                                root = self.root, out_root = self.out_root )
        except BaseException:
            # argparse says no by exiting, and a file that declares work is
            # allowed to talk while it is imported -- neither may reach the
            # screen.
            # A command the screen cannot read is still a command worth running:
            # it simply gets no per-case panes, and says so by having no rows.
            return [ ]

    def look( self ):
        """What the tree says about each expected run. Nothing is asked of the
        child: a result file where one was expected IS the completion."""
        running = self.child is not None and self.child.poll() is None
        if self.record is not None:
            running = any( batch.alive( p ) for p in self.record.get( "places", [ ] ) )
        rows = [ ]
        for run in self.plan:
            path = batch.result_path_for( self.root, run )
            if path is not None:
                got = yamlish.read( path ) or { }
                rows.append( { **run, "state": batch.DONE, "status": got.get( "status" ),
                               "place": got.get( "place" ) or run[ "place" ],
                               "seconds": got.get( "duration_s" ), "error": got.get( "error" ),
                               "results": got.get( "results" ) or { },
                               "output": path.parent / R.OUTPUT } )
            else:
                rows.append( { **run,
                               "state": batch.RUNNING if running else batch.LOST,
                               "output": self._live_output( run ) } )
        self.states = rows
        self.adopt()

    def _live_output( self, run ):
        """The file a case is writing INTO, before it has finished writing it.

        There is no result file yet to point the way, so the parameter
        directory -- which is predictable -- is searched for an output file
        touched since this command started. When the place is knowable the
        search is exact; when it is not ( another machine, a compute node the
        scheduler picked ) the newest is the best this side can honestly say.
        """
        under = self.root / run[ "under" ]
        pattern = ( f"{run[ 'place' ]}/*/{R.OUTPUT}" if run[ "place" ] != "?"
                    else f"*/*/{R.OUTPUT}" )
        best, when = None, self.started - 5
        for path in under.glob( pattern ):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= when:
                best, when = path, mtime
        return best

    def adopt( self ):
        """A `--batch` launch hands its work to somebody else and comes back.
        What it left behind is a record, and the record is what to watch from
        then on -- including after this screen is closed and opened again."""
        if self.record is not None or self.child is None or self.child.poll() is None:
            return
        for record in batch.load_all( self.root ):
            if record[ "id" ] not in getattr( self, "seen_batches", set() ):
                self.record = record
                self.plan = record.get( "runs", [ ] )
                threading.Thread( target = self._pull, args = ( record, ), daemon = True ).start()
                self.message = f"following submission {record[ 'id' ]}"
                return
        self.seen_batches = { r[ "id" ] for r in batch.load_all( self.root ) }

    def _pull( self, record ):
        while True:
            try:
                batch.collect( self.root, record )
            except Exception:
                pass
            if not any( batch.alive( p ) for p in record.get( "places", [ ] ) ):
                return
            time.sleep( PULL )

    def stop( self ):
        if self.child is None or self.child.poll() is not None:
            self.message = "nothing running"
            return
        # An interrupt, not a kill: the run gets to write its result file and
        # say what it had reached, which is the whole difference between a run
        # that was stopped and one that was lost.
        self.child.send_signal( signal.SIGINT )
        self.message = "interrupted"

    # ── the pane facing whatever the cursor is on ────────────────────────────

    def pane( self, width ):
        row = self.panel().current()
        if row is None:
            return "", [ ]
        if self.panel().name == "runs" and isinstance( row.data, tuple ):
            if row.data[ 0 ] == "log":
                return "the command", wrap( list( self.log ) or
                                            [ "( nothing launched yet -- r runs, b detaches )" ],
                                            width )
            state = row.data[ 1 ]
            head = [ f"{state[ 'label' ]}   {state[ 'env' ]}   {state[ 'place' ]}" ]
            if state.get( "params" ):
                head.append( "  " + ", ".join( f"{k}={v}" for k, v in state[ "params" ].items() ) )
            head.append( f"  {_detail( state )}" )
            if state.get( "error" ):
                head.append( f"  {state[ 'error' ]}" )
            body = tail_of( state[ "output" ], self.cache ) if state.get( "output" ) else [
                "( nothing written yet )" ]
            return _labelled( state, True ), wrap( head + [ "" ] + body, width )
        if self.panel().name == "entries" and row.kind == "item":
            return row.label, wrap( _about( row.data, self.root ), width )
        if self.panel().name == "envs" and row.kind == "item":
            e = row.data
            return row.label, wrap( [ e.describe(), "",
                                      *( f"{k} = {v}" for k, v in sorted( e.tags.items() ) ) ],
                                    width )
        if self.panel().name == "history" and row.kind == "plain":
            return "history", wrap( [ row.data[ 1 ], "",
                                      "enter runs it again, ! edits it first" ], width )
        return row.label, wrap( [ row.detail ] if row.detail else [ ], width )


def _id( entry ):
    """An entry, told apart from every other one: where it is written, and what
    it is called. Two entries may share a name, so the name alone will not do."""
    return ( str( entry.file ), entry.line, entry.name )


def _split( raw ):
    return [ v.strip() for v in str( raw ).split( "," ) if v.strip() ]


def _short( path: Path, root: Path ):
    try:
        return path.relative_to( root )
    except ValueError:
        return path


MARKS = { "done": "ok", "fail": "FAIL", "skip": "skip", "running": "..", "lost": "lost" }


def _mark( state ):
    if state[ "state" ] == batch.LOST:
        return "lost"
    if state[ "state" ] != batch.DONE:
        return "running"
    return { "PASS": "done", "SKIP": "skip" }.get( state.get( "status" ), "fail" )


def _labelled( state, with_env = False ):
    """A case, told apart from the same case run differently."""
    params = ", ".join( f"{k}={v}" for k, v in ( state.get( "params" ) or { } ).items() )
    return ( f"{state[ 'label' ]}"
             + ( f"  {params}" if params else "" )
             + ( f"  [{state[ 'env' ]}]" if with_env else "" ) )


def _detail( state ):
    if state[ "state" ] != batch.DONE:
        return "running" if state[ "state" ] == batch.RUNNING else "not started"
    numbers = " ".join( f"{k}={v:g}" for k, v in ( state.get( "results" ) or { } ).items()
                        if isinstance( v, ( int, float ) ) and not isinstance( v, bool ) )
    seconds = f"{state[ 'seconds' ]:g}s" if state.get( "seconds" ) else ""
    return " ".join( filter( None, [ str( state.get( "status" ) or "?" ), seconds, numbers ] ) )


def _about( e, root ):
    out = [ f"{_short( e.file, root )}:{e.line}", f"kind: {e.kind}" ]
    if e.tags:
        out.append( "tags: " + ", ".join( e.tags ) )
    if e.resources:
        out.append( "needs: " + ", ".join( f"{k}={v}" for k, v in e.resources.items() ) )
    traits = [ k for k, v in e.traits.items() if v ]
    if traits:
        out.append( "traits: " + " ".join( traits ) )
    if e.params:
        out.append( "" )
        for name, p in e.params.items():
            out.append( f"--{name.replace( '_', '-' )}  default {p.default!r}"
                        + ( f"  choices {p.choices}" if p.choices else "" ) )
            if p.help:
                out.append( f"    {p.help}" )
    return out


# ── drawing ──────────────────────────────────────────────────────────────────

C_HEAD, C_DIM, C_OK, C_BAD, C_WARN, C_SEL = 1, 2, 3, 4, 5, 6

KEYS = [
    ( "1..6 / tab", "the list: entries, envs, tags, params, runs, history" ),
    ( "arrows n p",  "move; g G ends; pgup pgdn pages" ),
    ( "space",      "tick -- several ticks is a matrix" ),
    ( "a / A / v",  "tick all, none, invert ( only what the filter shows )" ),
    ( "enter",      "type a value, or run a line of history" ),
    ( "/",          "filter the list; esc clears it" ),
    ( "r / b",      "run / run detached ( --batch )" ),
    ( "j",          "how many at once ( -j )" ),
    ( "x",          "interrupt what is running" ),
    ( "! ",         "edit the command by hand, then run it" ),
    ( "< >",        "scroll the output pane; = sticks it back to the bottom" ),
    ( "d",          "read the project again" ),
    ( "q / Q",      "leave / stop what is running and leave" ),
]


def put( win, y, x, text, width, attr = 0 ):
    if y < 0 or width <= 0:
        return
    try:
        win.addnstr( y, x, str( text ), width, attr )
    except curses.error:
        pass                    # the bottom right cell of a terminal is a lie


# Set when something is reading the screen rather than looking at it: every
# frame is then painted in full, instead of ncurses sending only the cells that
# changed. A test that has to reconstruct a terminal to check what is on it
# would otherwise be testing its own reconstruction.
REPAINT = bool( os.environ.get( "ERRAND_TUI_REPAINT" ) )


def draw( win, s: Screen ):
    win.erase()
    if REPAINT:
        win.clearok( True )
    height, width = win.getmaxyx()
    left = max( 26, min( 52, width // 2 - 4 ) )

    running = s.child is not None and s.child.poll() is None
    state = ( "running" if running else
              ( "following" if s.record is not None else "idle" ) )
    put( win, 0, 0, f" errand  {_short( s.root, s.root.parent )}  -j {s.jobs}  [{state}]",
         width, curses.color_pair( C_HEAD ) | curses.A_BOLD )

    put( win, 1, 0, " " * width, width )
    x = 0
    for i, p in enumerate( s.panels ):
        mark = f" {p.key} {p.name} "
        attr = curses.A_REVERSE if i == s.focus else curses.color_pair( C_DIM )
        put( win, 1, x, mark, width - x, attr )
        x += len( mark )

    body_top, body_bottom = 3, height - 4
    panel = s.panel()
    title = f"{panel.name}"
    ticked = len( panel.ticked() )
    if ticked:
        title += f"  {ticked} ticked"
    if panel.filter:
        title += f"  /{panel.filter}"
    put( win, 2, 0, title.ljust( left - 1 ), left - 1, curses.color_pair( C_HEAD ) )
    name, lines = s.pane( max( 4, width - left - 2 ) )
    put( win, 2, left + 1, f"{name}", width - left - 1, curses.color_pair( C_HEAD ) )
    for y in range( 2, body_bottom + 1 ):
        put( win, y, left - 1, "|", 1, curses.color_pair( C_DIM ) )

    rows = panel.shown()
    page = body_bottom - body_top + 1
    if panel.cursor < panel.top:
        panel.top = panel.cursor
    if panel.cursor >= panel.top + page:
        panel.top = panel.cursor - page + 1
    for i in range( page ):
        index = panel.top + i
        if index >= len( rows ):
            break
        r = rows[ index ]
        y = body_top + i
        attr = curses.A_REVERSE if index == panel.cursor else 0
        if r.kind == "head":
            put( win, y, 0, r.label[ : left - 2 ], left - 2,
                 attr | curses.color_pair( C_DIM ) | curses.A_BOLD )
            continue
        box = ( f"{r.mark:<3} " if r.mark is not None else
                "[x] " if r.kind == "item" and r.checked else
                "[ ] " if r.kind == "item" else " -> " )
        colour = ( curses.color_pair( C_OK ) if r.checked or r.mark == "ok" else
                   curses.color_pair( C_BAD ) if r.mark in ( "FAIL", "lost" ) else
                   curses.color_pair( C_WARN ) if r.mark == "skip" else 0 )
        text = f"{box}{r.label}"
        put( win, y, 0, text.ljust( left - 2 )[ : left - 2 ], left - 2, attr | colour )
        if r.detail and len( text ) < left - 4:
            put( win, y, len( text ) + 1, r.detail, left - 3 - len( text ),
                 curses.color_pair( C_DIM ) )

    # The pane, stuck to the bottom unless it has been scrolled back.
    pane_height = body_bottom - body_top + 1
    total = len( lines )
    start = max( 0, total - pane_height - s.offset )
    for i in range( pane_height ):
        if start + i >= total:
            break
        line = lines[ start + i ]
        attr = ( curses.color_pair( C_BAD ) if "FAIL" in line or "Error" in line else
                 curses.color_pair( C_OK ) if "PASS" in line or "all good" in line else
                 curses.color_pair( C_WARN ) if "SKIP" in line or "warning" in line else 0 )
        put( win, body_top + i, left + 1, line, width - left - 1, attr )

    put( win, height - 3, 0, "-" * width, width, curses.color_pair( C_DIM ) )
    command = s.line() if panel.name != "history" else (
        ( panel.current().data[ 1 ] if panel.current() and panel.current().kind == "item"
          else s.line() ) )
    put( win, height - 2, 0, f"$ {command}", width, curses.A_BOLD )
    put( win, height - 1, 0,
         s.message or "space tick   r run   b detach   j jobs   / filter   ? keys   q quit",
         width, curses.color_pair( C_WARN ) if s.message else curses.color_pair( C_DIM ) )

    if s.help:
        _help( win, height, width )
    win.noutrefresh()
    curses.doupdate()


def _help( win, height, width ):
    w = min( width - 4, 66 )
    h = len( KEYS ) + 4
    y0, x0 = max( 0, ( height - h ) // 2 ), max( 0, ( width - w ) // 2 )
    for i in range( h ):
        put( win, y0 + i, x0, " " * w, w, curses.A_REVERSE )
    put( win, y0 + 1, x0 + 2, "keys", w - 4, curses.A_REVERSE | curses.A_BOLD )
    for i, ( key, what ) in enumerate( KEYS ):
        put( win, y0 + 2 + i, x0 + 2, f"{key:<12} {what}", w - 4, curses.A_REVERSE )
    put( win, y0 + h - 1, x0 + 2, "any key closes this", w - 4, curses.A_REVERSE )


def ask( win, label, initial = "" ):
    """One line of typing, at the bottom of the screen. Esc gives nothing back."""
    height, width = win.getmaxyx()
    text = str( initial )
    curses.curs_set( 1 )
    try:
        while True:
            put( win, height - 1, 0, " " * width, width )
            put( win, height - 1, 0, f"{label} {text}", width, curses.A_BOLD )
            win.move( height - 1, min( width - 1, len( label ) + 1 + len( text ) ) )
            win.refresh()
            key = win.getch()
            if key in ( 27, ):                       # esc
                return None
            if key in ( 10, 13, curses.KEY_ENTER ):
                return text
            if key in ( curses.KEY_BACKSPACE, 127, 8 ):
                text = text[ : -1 ]
            elif 32 <= key < 127:
                text += chr( key )
    finally:
        curses.curs_set( 0 )


# ── the loop ─────────────────────────────────────────────────────────────────

def loop( win, s: Screen ):
    curses.curs_set( 0 )
    curses.use_default_colors()
    for pair, colour in ( ( C_HEAD, curses.COLOR_CYAN ), ( C_DIM, curses.COLOR_WHITE ),
                          ( C_OK, curses.COLOR_GREEN ), ( C_BAD, curses.COLOR_RED ),
                          ( C_WARN, curses.COLOR_YELLOW ), ( C_SEL, curses.COLOR_BLUE ) ):
        with contextlib.suppress( curses.error ):
            curses.init_pair( pair, colour, -1 )
    win.timeout( int( DRAW * 1000 ) )

    while True:
        now = time.time()
        if s.plan and now - s.looked > LOOK:
            s.looked = now
            s.look()
            s.again( "runs" )
        if s.panel().name == "history":
            # Written by the command itself, over there in the child: this side
            # only ever reads it, so it is read again rather than remembered.
            s.again( "history" )
        draw( win, s )

        key = win.getch()
        if key == -1:
            continue
        if s.help:
            s.help = False
            continue
        s.message = ""
        panel = s.panel()

        if key in ( curses.KEY_RESIZE, ):
            continue
        if key == ord( "q" ):
            # A run started from here belongs to here: leaving would break the
            # pipe under it and kill it halfway, which is not what `q` means.
            # `--batch` is how work is meant to outlive the screen.
            if s.child is not None and s.child.poll() is None:
                s.message = ( "something is running: x interrupts it, "
                              "Q stops it and leaves, b detaches next time" )
                continue
            return 0
        if key == ord( "Q" ):
            s.stop()
            return 0
        if key == ord( "?" ):
            s.help = True
        elif key in ( curses.KEY_DOWN, ord( "n" ) ):
            panel.move( 1 )
        elif key in ( curses.KEY_UP, ord( "p" ) ):
            panel.move( -1 )
        elif key == curses.KEY_NPAGE:
            panel.move( 10 )
        elif key == curses.KEY_PPAGE:
            panel.move( -10 )
        elif key == ord( "g" ):
            panel.first()
        elif key == ord( "G" ):
            panel.cursor = max( 0, len( panel.shown() ) - 1 )
        elif key == ord( "\t" ) or key == curses.KEY_RIGHT:
            s.focus = ( s.focus + 1 ) % len( s.panels )
        elif key in ( curses.KEY_BTAB, curses.KEY_LEFT ):
            s.focus = ( s.focus - 1 ) % len( s.panels )
        elif ord( "1" ) <= key <= ord( "6" ):
            s.focus = key - ord( "1" )
        elif key == ord( " " ):
            _toggle( s, win, panel )
        elif key == ord( "a" ):
            panel.set_all( True ); _remember( s, panel )
        elif key == ord( "A" ):
            panel.set_all( False ); _remember( s, panel )
        elif key == ord( "v" ):
            panel.invert(); _remember( s, panel )
        elif key == ord( "/" ):
            got = ask( win, "filter:", panel.filter )
            panel.filter = got or ""
            panel.first()
        elif key in ( 10, 13, curses.KEY_ENTER ):
            _enter( s, win, panel )
        elif key == ord( "j" ):
            got = ask( win, "-j ( a number, or auto ):", str( s.jobs ) )
            if got:
                s.jobs = max( 1, ( os.cpu_count() or 1 ) if got.strip() == "auto"
                              else int( got ) if got.strip().isdigit() else s.jobs )
        elif key == ord( "r" ):
            s.launch( s.argv() )
        elif key == ord( "b" ):
            s.launch( s.argv() + [ "--batch" ] )
        elif key == ord( "x" ):
            s.stop()
        elif key == ord( "!" ):
            got = ask( win, "$", s.line() )
            if got:
                s.launch( _args_of( got ) )
        elif key == ord( "d" ):
            s.discover()
            s.message = "read again"
        elif key in ( ord( "<" ), ord( "," ) ):
            s.offset += 5
        elif key in ( ord( ">" ), ord( "." ) ):
            s.offset = max( 0, s.offset - 5 )
        elif key == ord( "=" ):
            s.offset = 0


def _args_of( line ):
    args = shlex.split( line )
    return args[ 1 : ] if args and args[ 0 ] in ( "errand", "python", "python3" ) else args


def _toggle( s: Screen, win, panel ):
    row = panel.current()
    if row is None or row.kind == "head":
        return
    # A row that holds a value has nothing to tick: space means the same thing
    # as enter on it, which is "say what it should be".
    if row.kind == "text":
        _enter( s, win, panel )
        return
    row.checked = not row.checked
    _remember( s, panel )


def _remember( s: Screen, panel ):
    """Read every tick back off the rows and into the screen, which is where
    ticks live -- the rows are rebuilt twice a second and would lose them."""
    s.chosen  = { _id( r.data ) for r in s._panel( "entries" ).ticked() }
    s.on_envs = { r.label for r in s._panel( "envs" ).ticked() }
    picks: dict = { }
    for p in ( s._panel( "tags" ), s._panel( "params" ) ):
        for r in p.rows:
            if r.kind == "item" and r.checked and isinstance( r.data, tuple ):
                picks.setdefault( r.data[ : 2 ], [ ] ).append( r.data[ 2 ] )
    s.picks = picks
    s.build()


def _enter( s: Screen, win, panel ):
    row = panel.current()
    if row is None or row.kind == "head":
        return
    if panel.name == "history" and row.data:
        s.launch( _args_of( row.data[ 1 ] ) )
        return
    if row.kind == "text" and win is not None:
        got = ask( win, row.label, row.detail if row.data[ 0 ] != "param" else
                   s.values.get( row.data[ 1 ], "" ) )
        if got is None:
            return
        if row.data == "t":
            s.expr_t = got.strip()
        elif row.data == "e":
            s.expr_e = got.strip()
        else:
            s.values[ row.data[ 1 ] ] = got.strip()
        s.build()
        return
    if panel.name == "runs":
        s.offset = 0


def main( root: Path, out_root: Path ):
    if not sys.stdout.isatty():
        print( "errand --tui needs a terminal", file = sys.stderr )
        return 2
    s = Screen( root, out_root )
    s.discover()
    # Whatever is being followed survives the screen: a detached run was handed
    # to somebody else, and closing a window is not a reason to stop it.
    return curses.wrapper( loop, s )
