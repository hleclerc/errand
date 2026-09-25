"""What the screen is about, with nothing of the screen in it.

Reading the project, writing a command, launching it, watching what it
produces, and finding the files it wrote. No widget, no terminal: this is the
part that can be tested without either, and the screen is a view over it.

Two rules from the screen live here, because they are not about drawing.

**It runs nothing itself.** `command()` writes an errand command line and
`launch()` starts it as an ordinary child. There is nothing the screen can do
that the shell cannot, and the history is a list of commands for that reason.

**It reads the output tree, not the pipe.** The paths are worked out before the
run starts, by `plan_of` -- the very function the batch ledger is built from --
so each case's output is a file whose name this side already knows. Which is
why one case can be read while seven others are running, and why a job
submitted yesterday reads the same as one started a second ago.
"""
from __future__ import annotations

import contextlib
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

from . import batch, cli, config, discovery, history, results as R, yamlish

PULL = 5.0                 # seconds between fetches of a remote submission
TAIL = 64 * 1024           # how much of an output file is worth reading back


class Session:
    def __init__( self, root: Path, out_root: Path ):
        self.root, self.out_root = root, out_root
        self.entries : list = [ ]
        self.broken  : list = [ ]        # ( path, the short of it, the traceback )
        self.noise   = ""                # whatever reading the project printed
        self.child   = None
        self.command_line = ""
        self.log     = deque( maxlen = 4000 )
        self.plan    : list = [ ]
        self.record  : dict | None = None      # a submission this session adopted
        self.started = 0.0
        self.states  : list = [ ]
        self.seen_batches : set = set()
        self._cache  : dict = { }

    # ── reading the project ──────────────────────────────────────────────────

    def discover( self ):
        """Config, entries, environments. Nothing here may raise, and nothing
        here may print: a file that declares work runs its module level when it
        is imported, and it is allowed to talk."""
        buf = io.StringIO()
        self.entries = [ ]
        with contextlib.redirect_stdout( buf ), contextlib.redirect_stderr( buf ):
            try:
                config.load( self.root, warn = lambda m: print( f"warning: {m}" ) )
                cli._put_src_on_path( self.root )
                self.entries, _, _ = discovery.select(
                    None, self.root, bulk_only = False, exclude = config.settings.exclude,
                    providers = config.providers )
            except Exception as err:                  # a bad config, mostly
                print( f"{type( err ).__name__}: {err}" )
        # A file that would not import costs its own row and nothing else: half
        # a project installed is an ordinary state of affairs, and an empty
        # screen is a poor way of saying so.
        self.broken = list( discovery.broken )
        self.noise  = buf.getvalue().strip()
        return self

    @property
    def envs( self ):
        return list( config.envs.values() )

    def tag_values( self ):
        """Every ( dimension, values ) an environment declares.

        `fp = "32|64"` is two values, because that is what it means: an
        environment saying it can do both is offered for both.
        """
        out: dict = { }
        for e in config.envs.values():
            for name, value in e.tags.items():
                values = out.setdefault( name, [ ] )
                for v in ( [ "yes" ] if value is True else str( value ).split( "|" ) ):
                    if v.strip() and v.strip() not in values:
                        values.append( v.strip() )
        return out

    def params_of( self, entries ):
        """The parameters those entries declare, in the order they declare them."""
        out: dict = { }
        for e in entries:
            for name, param in e.params.items():
                out.setdefault( name, param )
        return out

    def files_of( self, path: Path ):
        """A file per line in the order somebody would want them: what the run
        wrote first, then errand's own two."""
        if path is None or not path.is_dir():
            return [ ]
        mine = ( R.RESULT, R.OUTPUT )
        found = sorted( p for p in path.iterdir() if p.is_file() )
        return [ p for p in found if p.name not in mine ] + \
               [ p for p in found if p.name in mine ]

    # ── writing a command ────────────────────────────────────────────────────

    def pattern_for( self, entries ):
        """`file::case` for each, `file` when every case of it was asked for --
        shorter, and it stays true when a case is added to it tomorrow."""
        if not entries:
            return ""
        parts = [ ]
        for path in dict.fromkeys( e.file for e in entries ):
            mine  = [ e for e in entries if e.file == path ]
            whole = [ e for e in self.entries if e.file == path ]
            if len( mine ) == len( whole ):
                parts.append( path.stem )
            else:
                parts += [ f"{path.stem}::{e.name}" for e in mine ]
        return ",".join( dict.fromkeys( parts ) )

    def command( self, entries = ( ), envs = ( ), tags = None, params = None,
                 jobs = 1, batch = False ):
        """-> the argv of the errand command those choices mean.

        A comma is a matrix, and a second tick is a comma: this is where the
        one becomes the other, and it is the whole of what a dialog does.
        """
        out = [ ]
        pattern = self.pattern_for( list( entries ) )
        if pattern:
            out.append( pattern )
        if envs:
            out += [ "--env", ",".join( envs ) ]
        for name, values in sorted( ( tags or { } ).items() ):
            if values:
                out += [ f"--{name.replace( '_', '-' )}", ",".join( str( v ) for v in values ) ]
        for name, values in sorted( ( params or { } ).items() ):
            values = values if isinstance( values, ( list, tuple ) ) else [ values ]
            joined = ",".join( str( v ).strip() for v in values if str( v ).strip() )
            if joined:
                out += [ f"--{name.replace( '_', '-' )}", joined ]
        if jobs and int( jobs ) > 1:
            out += [ "-j", str( int( jobs ) ) ]
        if batch:
            out.append( "--batch" )
        return out

    @staticmethod
    def as_line( argv ):
        return " ".join( [ "errand", *( shlex.quote( str( a ) ) for a in argv ) ] )

    @staticmethod
    def args_of( line ):
        args = shlex.split( line )
        return args[ 1 : ] if args and args[ 0 ] in ( "errand", "python", "python3" ) else args

    def history( self ):
        return list( reversed( history.load( self.root ) ) )

    # ── doing it ─────────────────────────────────────────────────────────────

    @property
    def running( self ):
        return self.child is not None and self.child.poll() is None

    def launch( self, argv ):
        """Start it, and start watching where it is going to write. -> why not."""
        if self.running:
            return "something is already running"
        self.plan    = self.predict( argv )
        self.states  = [ ]
        self.record  = None
        self.started = time.time()
        self.log.clear()
        self.command_line = self.as_line( argv )
        self.seen_batches = { r[ "id" ] for r in batch.load_all( self.root ) }
        try:
            self.child = subprocess.Popen(
                [ sys.executable, "-m", "errand", *argv ], cwd = self.root,
                env = { **os.environ, "PYTHONUNBUFFERED": "1", "NO_COLOR": "1" },
                stdout = subprocess.PIPE, stderr = subprocess.STDOUT, text = True, bufsize = 1 )
        except OSError as err:
            return str( err )
        threading.Thread( target = self._drain, args = ( self.child, ), daemon = True ).start()
        return None

    def _drain( self, child ):
        for line in child.stdout:
            self.log.append( line.rstrip( "\n" ) )
        child.stdout.close()

    def stop( self ):
        if not self.running:
            return "nothing running"
        # An interrupt and not a kill: the run gets to write its result file and
        # say what it had reached, which is the difference between a run that
        # was stopped and one that was lost.
        self.child.send_signal( signal.SIGINT )
        return None

    def predict( self, argv ):
        """Where that command is going to write, worked out by the code that is
        about to write there. A screen guessing differently would watch the
        wrong files -- and would be believed."""
        noise = io.StringIO()
        try:
          with contextlib.redirect_stdout( noise ), contextlib.redirect_stderr( noise ):
            parser = cli.build_parser( config.tag_names() )
            known, _ = parser.parse_known_args( argv )
            pattern = cli.positional_of( parser, argv )
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
            parsed = parser.parse_args( argv )
            combos = cli.expand( { n: getattr( parsed, n, None ) for n in declared }, declared )
            targets = cli._targets( parsed, config.tag_names() )
            return cli.plan_of( targets, entries, combos,
                                root = self.root, out_root = self.out_root )
        except BaseException:
            # argparse says no by exiting, and a file that declares work is
            # allowed to talk while it is imported: neither may reach the screen.
            # A command that cannot be read is still a command worth running --
            # it simply gets no per-case panes, and says so by having no rows.
            return [ ]

    # ── watching ─────────────────────────────────────────────────────────────

    def look( self ):
        """What the tree says about each expected run. Nothing is asked of the
        child: a result file where one was expected IS the completion."""
        alive = self.running
        if self.record is not None:
            alive = any( batch.alive( p ) for p in self.record.get( "places", [ ] ) )
        self.states = self.states_of( self.plan,
                                      batch.RUNNING if alive else batch.LOST )
        self.adopt()
        return self.states

    def states_of( self, plan, missing = batch.PENDING ):
        """The same reading, for any plan -- which is what lets a line of
        history show what it produced the last time it was run, without this
        session having been the one to run it.

        `missing` is what a run with no result file is called, and the caller is
        the only one who can say: one WE started and can no longer find is lost,
        one nobody started is simply not run yet.
        """
        rows = [ ]
        for run in plan:
            path = batch.result_path_for( self.root, run )
            if path is not None:
                got = yamlish.read( path ) or { }
                rows.append( { **run, "state": batch.DONE, "status": got.get( "status" ),
                               "place": got.get( "place" ) or run[ "place" ],
                               "seconds": got.get( "duration_s" ), "error": got.get( "error" ),
                               "results": got.get( "results" ) or { },
                               "dir": path.parent, "output": path.parent / R.OUTPUT } )
            else:
                live = self._live_output( run )
                rows.append( { **run, "state": missing,
                               "dir": live.parent if live else None, "output": live } )
        return rows

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
        """A detached launch hands the work to somebody else and comes back.
        What it left is a record, and the record is what to watch from then on
        -- including after the screen is closed and opened again."""
        if self.record is not None or self.child is None or self.child.poll() is None:
            return None
        for record in batch.load_all( self.root ):
            if record[ "id" ] not in self.seen_batches:
                self.record = record
                self.plan = record.get( "runs", [ ] )
                threading.Thread( target = self._pull, args = ( record, ), daemon = True ).start()
                return record
        self.seen_batches = { r[ "id" ] for r in batch.load_all( self.root ) }
        return None

    def _pull( self, record ):
        while True:
            try:
                batch.collect( self.root, record )
            except Exception:
                pass
            if not any( batch.alive( p ) for p in record.get( "places", [ ] ) ):
                return
            time.sleep( PULL )

    def tail( self, path ):
        """The last of a file, re-read only when it has moved."""
        if path is None:
            return [ ]
        try:
            stat = path.stat()
        except OSError:
            return [ ]
        token = ( stat.st_mtime_ns, stat.st_size )
        got = self._cache.get( str( path ) )
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
            lines = lines[ 1 : ]               # the first line was cut in half
        self._cache[ str( path ) ] = ( token, lines )
        return lines


# ── opening what a run produced ──────────────────────────────────────────────

def opener( ):
    """The command this operating system opens a file with. None when there is
    none -- over ssh with no display there is nothing to open a picture in, and
    pretending otherwise would hang or lie."""
    if sys.platform == "darwin":
        return [ "open" ]
    if os.name == "nt":
        return [ "cmd", "/c", "start", "" ]
    import shutil
    if shutil.which( "xdg-open" ) and ( os.environ.get( "DISPLAY" )
                                        or os.environ.get( "WAYLAND_DISPLAY" ) ):
        return [ "xdg-open" ]
    return None


def open_file( path: Path ):
    """Hand a file to the desktop. -> why not, or None.

    Detached, with its output thrown away: an image viewer writing warnings to
    the terminal it was started from would land in the middle of the screen.
    """
    argv = opener()
    if argv is None:
        return "no way to open a file here ( no xdg-open, or no display )"
    try:
        subprocess.Popen( [ *argv, str( path ) ], stdout = subprocess.DEVNULL,
                          stderr = subprocess.DEVNULL, start_new_session = True )
    except OSError as err:
        return str( err )
    return None


# ── how a run reads ──────────────────────────────────────────────────────────

MARKS = { "done": "ok", "fail": "FAIL", "skip": "skip", "running": "..",
          "lost": "lost", "pending": "-" }


def mark_of( state ):
    if state[ "state" ] == batch.DONE:
        return { "PASS": "done", "SKIP": "skip" }.get( state.get( "status" ), "fail" )
    return { batch.LOST: "lost", batch.PENDING: "pending" }.get( state[ "state" ], "running" )


def labelled( state, with_env = False ):
    """A case, told apart from the same case run differently."""
    params = ", ".join( f"{k}={v}" for k, v in ( state.get( "params" ) or { } ).items() )
    return ( f"{state[ 'label' ]}"
             + ( f"  {params}" if params else "" )
             + ( f"  [{state[ 'env' ]}]" if with_env else "" ) )


WAITING = { batch.RUNNING: "running", batch.LOST: "no result came back",
            batch.PENDING: "not run" }


def detail_of( state ):
    if state[ "state" ] != batch.DONE:
        return WAITING.get( state[ "state" ], "?" )
    numbers = " ".join( f"{k}={v:g}" for k, v in ( state.get( "results" ) or { } ).items()
                        if isinstance( v, ( int, float ) ) and not isinstance( v, bool ) )
    seconds = f"{state[ 'seconds' ]:g}s" if state.get( "seconds" ) else ""
    return " ".join( filter( None, [ str( state.get( "status" ) or "?" ), seconds, numbers ] ) )
