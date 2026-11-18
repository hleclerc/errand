"""Running entries in this process: what each asks of the machine, the claim, the run, the report.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

from .. import config, discovery, entries as E, local, mpi, needs, queue, results as R, runner as P, steps, streams
from .style import bad, capture, dim, GREEN, head, RED, RESET, YELLOW
from .project import _src_paths, _with_env, build_dir_for, tools_for, TAGS
from .parsing import shown_params, target_argv
from .help import _short


# ── running, here ────────────────────────────────────────────────────────────

class Report:
    def __init__( self ):
        self.failed  = [ ]
        self.skipped = [ ]
        self.broken  = [ ]      # files that declare work and would not import


def aggregate_needs( entries, asked = None ):
    """What one command carries, as one machine's worth of asking.

    A dispatched command runs SEVERAL entries in one allocation, so the
    allocation has to be the largest of them -- and exclusive when the command
    says so ( `-x`, `asked[ "exclusive" ]` ).
    """
    asked = dict( asked or { } )
    out = { "exclusive": True } if asked.pop( "exclusive", False ) else { }
    for e in entries:
        # what the command line asks ( `--cpus`, `--ranks` ) wins, as it does in the queue; with ranks,
        # per rank: a batch system asks for so many tasks of so much each
        asked_here = { **e.resources, **( asked or { } ) }
        ranks = float( asked_here.pop( "ranks", None ) or 1 )
        for key, value in [ *queue.normalize( asked_here ).items(), *( [ ( "ranks", ranks ) ] if ranks > 1 else [ ] ) ]:
            # a card's memory is the queue's to count once there ( ADR 0014 ): carried, never added up
            out[ key ] = value if key == "gpu_ram" else max( out.get( key, 0.0 ), value )
    return out


def _handed_to_the_run( root, tags ) -> dict:
    """What a run started by a runner sees of the place: its tags, and the
    project's own sources first on the path -- the same sources the work of
    this project would see, rather than somebody else's checkout of them."""
    path = os.pathsep.join( _src_paths( root ) + [ os.environ.get( "PYTHONPATH", "" ) ] )
    return { TAGS: ",".join( f"{k}={v}" for k, v in sorted( tags.items() ) ),
             "PYTHONPATH": path.rstrip( os.pathsep ) }


class Ask:
    """What the command line asks of the machine for every run ( `-x`,
    `--cpus`… ), on top of what each entry asks for itself, and how to say it."""

    def __init__( self, known = None ):
        get = lambda k: getattr( known, k, None ) if known is not None else None
        self.resources = { k: get( k ) for k in ( "cpus", "ram", "gpus", "gpu_ram", "ranks" ) if get( k ) }
        self.exclusive = bool( get( "exclusive" ) )
        self.label     = get( "label" )
        self.log       = get( "log" )
        self.quiet     = bool( get( "quiet" ) )
        self.visible   = bool( get( "keep_out" ) or get( "out" ) )
        self.wrap      = _ceiling( get( "mem" ) )
        # `-j N` handed to the tool of a single run ( `Runner.jobs` ): set by `run_here`.
        self.jobs      = 1

    @staticmethod
    def flags( known ) -> list:
        """The same, as the flags a child of `-j` is started with."""
        out = [ ]
        for dest, flag in ( ( "keep_out", "-o" ), ( "exclusive", "-x" ), ( "quiet", "-q" ) ):
            if getattr( known, dest, False ):
                out.append( flag )
        for dest, flag in ( ( "out", "--out" ), ( "cpus", "--cpus" ), ( "ram", "--ram" ),
                            ( "gpus", "--gpus" ), ( "gpu_ram", "--gpu-ram" ), ( "ranks", "--ranks" ), ( "mem", "--mem" ), ( "label", "--label" ) ):
            if getattr( known, dest, None ):
                out += [ flag, str( getattr( known, dest ) ) ]
        return out


def _stack_of( env_name, tags ) -> list:
    """The layers of the environment this process runs in, as far as it knows them."""
    env = config.envs.get( env_name )
    return env.stack_for( "run" ) if env is not None else [ ]


def _ranks_wrap( e, ask, env_name, tags ) -> list:
    """`--ranks N` on a plain file: the file is started under the MPI launcher."""
    n = mpi.ranks_of( e.resources, ask.resources )
    if n <= 1 or not ( e.runner is not None and e.runner.whole_files ) or mpi.inside():
        return [ ]
    start = mpi.launcher( _stack_of( env_name, tags ), n, { "env": env_name, "tags": tags } )
    if start is None:
        raise local.Skipped( f"needs an MPI launcher for {n} ranks",
                             "install one in the environment ( micromamba install -c conda-forge mpich mpi4py ), "
                             "or name it: errand.Mpi( \"mpirun\" ) in its stack" )
    return start


def _ceiling( mem ) -> list:
    """`-m 8G`: a command held under that much memory, where systemd can do it.
    Without a user bus ( ssh, cron ) the scope cannot be made, and the command
    runs without its ceiling rather than not at all."""
    if not mem:
        return [ ]
    scope = [ "systemd-run", "--user", "--scope", "-q", "-p", f"MemoryMax={mem}" ]
    if shutil.which( "systemd-run" ) and subprocess.run( scope + [ "true" ], capture_output = True ).returncode == 0:
        return scope
    return [ ]


def run_entries( entries, modules, *, root, out_root, overrides, env_name, tags,
                 version, report, queued = True, quiet = False, selectors = None, ask = None ):
    selectors = selectors or { }
    ask = ask or Ask()
    quiet = quiet or ask.quiet
    if not quiet:
        print( head( f"\n{'=' * 10} {len( entries )} entr{'y' if len( entries ) == 1 else 'ies'}"
                     f"  {env_name}  {R.place( env_name )} {'=' * 10}" ), flush = True )
    for e in entries:
        # The claim is taken OUTSIDE the timing: waiting for the machine is not
        # part of how long the work takes, and recording it as if it were would
        # make a benchmark's numbers depend on who else was busy. What it asks:
        # the environment's needs, the command line, what it required last time
        # ( ADR 0014 ).
        status, error, hint = needs.run_claimed(
            e, env_name = env_name, ask = ask, root = root, queued = queued,
            echo = lambda m: print( dim( m ), flush = True ),
            run = lambda handed, devices, e = e: run_case(
                e, modules, root = root, out_root = out_root, overrides = overrides, env_name = env_name,
                tags = tags, version = version, selectors = selectors, ask = ask, handed = handed,
                devices = devices ) )
        tally( report, e, status, error, hint )
    return report


def _kept( names ):
    """Put back these variables as they were, whatever the block did to them."""
    import contextlib

    @contextlib.contextmanager
    def kept():
        before = { k: os.environ.get( k ) for k in names }
        try:
            yield
        finally:
            for k, old in before.items():
                if old is None:
                    os.environ.pop( k, None )
                else:
                    os.environ[ k ] = old
    return kept()


def _required( handed ) -> dict | None:
    """What the run's `errand.require` calls came to, in all, as its claim says ( ADR 0014 ), for its
    record."""
    path = handed.get( queue.CLAIM_FILE )
    if not path:
        return None
    from .. import yamlish
    row = yamlish.read( Path( path ) ) if Path( path ).exists() else None
    row = row or { }
    got = { **( row.get( "wanted" ) or { } ), **( { "exclusive": True } if row.get( "required_exclusive" ) else { } ) }
    return got or None


def _followed( journal, marks, root = None ):
    """The case's line at the bottom of the terminal, or said as marks by a session, or nothing."""
    import contextlib
    from . import footer
    if marks:
        return footer.Followed( journal, footer.mark, want = footer.want, view = footer.view, root = root )
    if footer.Footer.usable():
        return footer.Followed( journal, footer.Footer().show )
    return contextlib.nullcontext()


def tally( report, e, status, error, hint ):
    if status == "SKIP":
        report.skipped.append( ( e, error, hint ) )
    elif status != "PASS":
        report.failed.append( ( e, error ) )


def run_case( e, modules, *, root, out_root, overrides, env_name, tags, version, selectors, ask,
              handed, devices = None, marks = False ):
    """One entry with one set of values, once the machine is granted: run it, say how it went,
    and write its record. -> ( status, error, hint ). `marks`: a session's, whose steps are said as
    marks to the side that drives it ( ADR 0010 )."""
    E.set_tags( tags )
    where = R.place( env_name )
    try:
        resolved = E.resolve_params( e.params, overrides )
    except ValueError as err:
        print( bad( f"  {e.name}: {err}" ) )
        return "FAIL", str( err ), None

    shown = shown_params( resolved, overrides )
    leaf, entry_root = R.dirs_for( out_root, e, shown, where, root )
    R.clear( leaf )
    R.point_latest_at( leaf )
    from ..agents import seen
    seen.note( leaf, root, f"{e.file.name}::{e.name}" + "".join( f" {k}={v}" for k, v in shown.items() ), env_name )
    # Where the case says its steps ( ADR 0010 ), and the shell functions that say them.
    journal = leaf / steps.FILE
    handed = { **handed, steps.ENV: str( journal ), steps.SH_ENV: steps.SHELL_STEPS,
               # what the shell's `download` calls ( ADR 0013 ): this errand, with this Python
               "ERRAND_PYTHON": sys.executable, "ERRAND_SRC": str( Path( __file__ ).resolve().parents[ 2 ] ) }
    if marks:
        # Followed by the side that drives it: a download with no route asks it ( ADR 0013 ).
        from ..downloads import RELAY
        handed[ RELAY ] = "1"

    site =f"{e.file.name}:{e.line}" if e.line else e.file.name
    if shown:
        told = ", ".join( f"{k}={v!r}" for k, v in shown.items() )
        print( dim( f"  {e.name} ({site}) -- {told}" ), flush = True )

    E.begin_run( e, resolved, leaf )
    status, error, hint = "PASS", None, None
    exit_code = None                  # a process's that ended the run otherwise than well: its stderr is said
    provenance = R.git_commit( root )
    crashed = R.crash_record( entry = e, root = root, env_name = env_name, where = where, tags = tags,
                              params = shown, version = version, provenance = provenance )
    # `errand.require` sets the cards in this process when the run is in it: put back as they were.
    with _with_env( handed ), _kept( E._DEVICE_VARS + ( queue.CLAIM, ) ), _followed( journal, marks, root ), \
            streams.raw( leaf, crashed ):
        if devices:
            print( dim( f"  gpu {','.join( str( d ) for d in devices )}" ), flush = True )
        started = time.perf_counter()
        with capture( leaf / R.OUTPUT, ask.log ) as buf:
            try:
                ranks = mpi.ranks_of( e.resources, ask.resources )
                if ranks > 1 and not mpi.inside() and ( e.runner is None or not e.runner.whole_files ):
                    # One process per rank, each running this body: errand
                    # stays here and reads what they wrote.
                    if e.runner is not None:
                        raise RuntimeError( f"{e.runner.name} entries cannot run on several ranks" )
                    status, error, hint, got = mpi.run(
                        e, n = ranks, stack = _stack_of( env_name, tags ), root = root, leaf = leaf,
                        resolved = resolved, argv = target_argv( e, resolved, overrides ),
                        place = { "env": env_name, "tags": tags },
                        env = { **handed, **_handed_to_the_run( root, tags ),
                                **( { P.OUT_DIR: str( leaf ) } if ask.visible else { } ) } )
                    E.results.update( got )
                elif e.runner is None:
                    if e.module not in modules:
                        # It was registered while ANOTHER file imported
                        # this one: there are now two of every entry it
                        # declares, and this copy belongs to an import
                        # errand did not make and cannot repeat.
                        raise RuntimeError(
                            f"{e.file.name} was imported by another file rather than "
                            f"read on its own, so everything it declares is declared "
                            f"twice.\n  a file that declares work is not a module to "
                            f"import from -- move what is shared into one that declares "
                            f"none ( a name starting with `_` is the usual sign )" )
                    # The target's arguments are its `sys.argv`, as
                    # they would be for `python file.py args…`.
                    kept_argv = sys.argv
                    sys.argv = [ str( e.file ), *target_argv( e, resolved, overrides ) ]
                    try:
                        discovery.import_file( modules[ e.module ], root )
                    finally:
                        sys.argv = kept_argv
                else:
                    # Somebody else's suite: it runs itself, and only
                    # says what came of it. Everything around the run
                    # is the same as for anything here.
                    # A directory is handed over only when one was
                    # asked for: the private record is errand's.
                    got = e.runner.run( e, P.RunContext(
                        root = root, out_dir = leaf, params = resolved,
                        env = { **handed, **_handed_to_the_run( root, tags ),
                                **( { P.OUT_DIR: str( leaf ) } if ask.visible else { } ) },
                        selector = getattr( e, "selector", None ) or selectors.get( e.name ),
                        build_dir = build_dir_for( root, env_name ),
                        tools = tools_for( env_name ), jobs = ask.jobs,
                        args = target_argv( e, resolved, overrides ),
                        wrap = ask.wrap + _ranks_wrap( e, ask, env_name, tags ) ) )
                    status, error = got.status, got.error
                    exit_code = getattr( got, "exit", None )
                    E.results.update( got.results )
                    if got.output:
                        print( got.output, end = "" )
            except local.Skipped as s:
                status, error, hint = "SKIP", s.reason, s.hint
            except KeyboardInterrupt:
                # Ctrl-C stops the run: it is not this entry failing, and nothing runs after it.
                raise
            except E.Rerun as r:
                status, error = "FAIL", f"stopped by errand.require: {r}"     # and run again ( ADR 0014 )
            except BaseException as exc:         # SystemExit included
                status, error = "FAIL", f"{type( exc ).__name__}: {exc}"
                if isinstance( exc, SystemExit ) and isinstance( exc.code, int ) and exc.code:
                    exit_code = exc.code
                traceback.print_exc()
        duration = time.perf_counter() - started
        steps.flush()
    E.end_run()
    if status == "FAIL" and exit_code:
        # Ended by its exit status or a signal: what it said last on stderr is what says why.
        error = streams.with_tail( error, streams.tail( leaf / R.STDERR ) )

    if status == "PASS":
        print( f"{GREEN}PASS{RESET} {e.name} {dim( f'({site})' )}", flush = True )
    elif status == "SKIP":
        print( f"{YELLOW}SKIP{RESET} {e.name} {dim( f'({site})' )} - {error}", flush = True )
    else:
        print( f"{RED}FAIL{RESET} {e.name} {dim( f'({site})' )} - {error}", flush = True )

    R.write_result(
        leaf, entry = e, root = root, env_name = env_name, where = where, tags = tags,
        status = status, error = error, duration_s = duration, ram = R.ram_mb(),
        params = shown, results = dict( E.results ), output_text = buf.getvalue(),
        version = version, provenance = provenance,
        required = _required( handed ),
    )
    R.refresh( entry_root )
    return status, error, hint
