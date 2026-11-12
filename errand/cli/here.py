"""Running entries in this process: what each asks of the machine, the claim, the run, the report.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import traceback

from .. import config, discovery, entries as E, local, mpi, queue, results as R, runner as P
from .style import bad, capture, dim, GREEN, head, RED, RESET, YELLOW
from .project import _src_paths, _with_env, build_dir_for, TAGS
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
    allocation has to be the largest of them -- and exclusive if any one of
    them is.
    """
    out = { }
    for e in entries:
        # what the command line asks ( `--cpus`, `--ranks` ) wins, as it does in the queue; with ranks,
        # per rank: a batch system asks for so many tasks of so much each
        asked_here = { **e.resources, **( asked or { } ) }
        ranks = float( asked_here.pop( "ranks", None ) or 1 )
        for key, value in [ *queue.normalize( asked_here ).items(), *( [ ( "ranks", ranks ) ] if ranks > 1 else [ ] ) ]:
            out[ key ] = max( out.get( key, 0.0 ), value )
        if e.traits[ "exclusive" ]:
            out[ "exclusive" ] = True
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
        self.resources = { k: get( k ) for k in ( "cpus", "ram", "gpus", "ranks" ) if get( k ) }
        self.exclusive = bool( get( "exclusive" ) )
        self.label     = get( "label" )
        self.log       = get( "log" )
        self.quiet     = bool( get( "quiet" ) )
        self.visible   = bool( get( "keep_out" ) or get( "out" ) )
        self.wrap      = _ceiling( get( "mem" ) )

    @staticmethod
    def flags( known ) -> list:
        """The same, as the flags a child of `-j` is started with."""
        out = [ ]
        for dest, flag in ( ( "keep_out", "-o" ), ( "exclusive", "-x" ), ( "quiet", "-q" ) ):
            if getattr( known, dest, False ):
                out.append( flag )
        for dest, flag in ( ( "out", "--out" ), ( "cpus", "--cpus" ), ( "ram", "--ram" ),
                            ( "gpus", "--gpus" ), ( "ranks", "--ranks" ), ( "mem", "--mem" ), ( "label", "--label" ) ):
            if getattr( known, dest, None ):
                out += [ flag, str( getattr( known, dest ) ) ]
        return out


def _stack_of( env_name, tags ) -> list:
    """The layers of the environment this process runs in, as far as it knows them."""
    env = config.envs.get( env_name )
    return env.stack_for( "run", tags ) if env is not None else [ ]


def _ranks_wrap( e, ask, env_name, tags ) -> list:
    """`--ranks N` on a plain file: the file is started under the MPI launcher."""
    n = mpi.ranks_of( e.resources, ask.resources )
    if n <= 1 or not ( e.runner is not None and e.runner.whole_files ) or mpi.inside():
        return [ ]
    start = mpi.launcher( _stack_of( env_name, tags ), n )
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
    E.set_tags( tags )
    selectors = selectors or { }
    ask = ask or Ask()
    quiet = quiet or ask.quiet
    where = R.place( env_name )
    if not quiet:
        print( head( f"\n{'=' * 10} {len( entries )} entr{'y' if len( entries ) == 1 else 'ies'}"
                     f"  {env_name}  {where} {'=' * 10}" ), flush = True )

    for e in entries:
        try:
            resolved = E.resolve_params( e.params, overrides )
        except ValueError as err:
            print( bad( f"  {e.name}: {err}" ) )
            report.failed.append( ( e, str( err ) ) )
            continue

        shown = shown_params( resolved, overrides )
        leaf, entry_root = R.dirs_for( out_root, e, shown, where, root )
        R.clear( leaf )
        R.point_latest_at( leaf )

        site = f"{e.file.name}:{e.line}" if e.line else e.file.name
        if shown:
            told = ", ".join( f"{k}={v!r}" for k, v in shown.items() )
            print( dim( f"  {e.name} ({site}) -- {told}" ), flush = True )

        E.begin_run( e, resolved, leaf )
        status, error, hint = "PASS", None, None
        # The claim is taken OUTSIDE the timing: waiting for the machine is not
        # part of how long the work takes, and recording it as if it were would
        # make a benchmark's numbers depend on who else was busy.
        with queue.claim( { **e.resources, **ask.resources },
                          exclusive = e.traits[ "exclusive" ] or ask.exclusive,
                          label = ask.label or f"{e.file.name}::{e.name}", enabled = queued,
                          echo = lambda m: print( dim( m ), flush = True ) ) as granted:
            # Being told WHICH card is the whole point of asking for one: two
            # entries that both picked the first would share it and neither
            # would measure anything.
            # Everything this entry starts inherits the claim: an errand it
            # runs must not queue for a machine its own parent is holding.
            handed = { **granted.env(), **granted.handed_down() } if granted else { }
            with _with_env( handed ):
                if granted and granted.devices and granted.path:
                    print( dim( f"  gpu {','.join( str( d ) for d in granted.devices )}" ),
                           flush = True )
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
                                selector = selectors.get( e.name ),
                                build_dir = build_dir_for( root, env_name ),
                                args = target_argv( e, resolved, overrides ),
                                wrap = ask.wrap + _ranks_wrap( e, ask, env_name, tags ) ) )
                            status, error = got.status, got.error
                            E.results.update( got.results )
                            if got.output:
                                print( got.output, end = "" )
                    except local.Skipped as s:
                        status, error, hint = "SKIP", s.reason, s.hint
                    except BaseException as exc:         # SystemExit included
                        status, error = "FAIL", f"{type( exc ).__name__}: {exc}"
                        traceback.print_exc()
                duration = time.perf_counter() - started
        E.end_run()

        if status == "PASS":
            print( f"{GREEN}PASS{RESET} {e.name} {dim( f'({site})' )}", flush = True )
            if e.traits[ "stable_path" ]:
                # What it produced IS the point, so name the files and the path
                # to open rather than leave it to be reconstructed.
                written = sorted( f.name for f in leaf.iterdir()
                                  if f.name not in ( R.RESULT, R.OUTPUT ) )
                print( dim( f"  {_short( leaf.parent / R.LATEST, root )}/" ) )
                for name in written:
                    print( dim( f"    {name}" ) )
        elif status == "SKIP":
            print( f"{YELLOW}SKIP{RESET} {e.name} {dim( f'({site})' )} - {error}", flush = True )
            report.skipped.append( ( e, error, hint ) )
        else:
            print( f"{RED}FAIL{RESET} {e.name} {dim( f'({site})' )} - {error}", flush = True )
            report.failed.append( ( e, error ) )

        R.write_result(
            leaf, entry = e, root = root, env_name = env_name, where = where, tags = tags,
            status = status, error = error, duration_s = duration, ram = R.ram_mb(),
            params = shown, results = dict( E.results ), output_text = buf.getvalue(),
            version = version,
        )
        R.refresh( entry_root )

    return report
