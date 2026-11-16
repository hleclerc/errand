"""Environments kept current by themselves.

A layer says what it needs -- an interpreter version, a channel list, a
requirements file, a recipe, a pip list. Before running anything, what it says
is compared against what was last built into it, and the difference is made up.
Creating an environment, installing into it and rebuilding an image are one
operation seen at three moments, which is why there is one command for all
three and why it mostly runs by itself.

The record of what was built lives with what was built: in the `errand-outputs/builds/records/`
of the machine that holds it, one per artefact ( ADR 0004 ). It is state about that
place, not a result, and it describes both ends of the build -- the fingerprint
of what it was built from, the stamp of what came out.
"""
from __future__ import annotations

import getpass
import hashlib
import re
import shlex
import socket
import time
from pathlib import Path

from . import layers as L, yamlish



OK, STALE, MISSING, UNKNOWN, ADOPTED = "ok", "stale", "not built", "unknown", "adopted"
UNREACHABLE = "unreachable"     # a `Missing` layer: says what is lacking ( `errand envs` shows it in the stack )
FOUND = "found"     # there, and nothing known about it: what is adopted

# Between the parts of what a machine answers: a remote shell started with `-i`
# may well say something of its own first.
MARK = "@errand-record@"


def builds( root: Path ) -> str:
    """Where the records are, from the root of the machine that holds them."""
    from . import config
    return f"{config.builds_rel( root )}/records"


def slug( layer ) -> str:
    """A file name for that artefact: readable, and hashed over its full identity."""
    name = re.sub( r"[^\w.+-]+", "-", layer.describe() ).strip( "-" )
    whole = getattr( layer, "identity", layer.describe )()
    return f"{name}-{hashlib.sha256( whole.encode() ).hexdigest()[ : 8 ]}"


def wanted( env, ctx ) -> dict:
    """The fingerprint each layer of `env` says it should have."""
    out = { }
    for i, layer in env.layers():
        if hasattr( layer, "spec" ):
            out[ f"{i}:{layer.describe()}" ] = L.fingerprint( *layer.spec( ctx ) )
    return out


def _windows_here( there ) -> bool:
    """This machine, a Windows: what would be a line of `sh` is done here, in Python."""
    return L.WINDOWS and not there.host.remote


def look( root: Path, layer, there ) -> tuple:
    """( record, stamp ) of `layer`, asked of the machine it lives on, in one go."""
    if _windows_here( there ):
        record = there.host.root / builds( root ) / f"{slug( layer )}.yaml"
        text = record.read_text() if record.is_file() else ""
        stamp = layer.stamp_shell( there ) if hasattr( layer, "stamp_shell" ) else "true"
        try:
            said = there.host.shell( stamp, capture = True ).stdout if stamp != "true" else ""
        except ( L.NeedsAShell, OSError ):
            said = ""
        return yamlish.load( text ) if text.strip() else { }, ( said or "" ).strip()
    path = shlex.quote( f"{builds( root )}/{slug( layer )}.yaml" )
    stamp = layer.stamp_shell( there ) if hasattr( layer, "stamp_shell" ) else "true"
    answer = there.host.shell( f"echo {MARK}; cat {path} 2>/dev/null; echo {MARK}; ( {stamp} ) 2>/dev/null; echo {MARK}",
                               capture = True )
    parts = ( getattr( answer, "stdout", None ) or "" ).split( MARK )
    if len( parts ) < 4:
        return { }, ""
    return yamlish.load( parts[ 1 ].strip() + "\n" ) if parts[ 1 ].strip() else { }, parts[ 2 ].strip()


def write( root: Path, layer, there, record: dict ):
    if _windows_here( there ):
        target = there.host.root / builds( root ) / f"{slug( layer )}.yaml"
        target.parent.mkdir( parents = True, exist_ok = True )
        target.write_text( yamlish.dump( record ) )
        return
    path = f"{builds( root )}/{slug( layer )}.yaml"
    there.host.shell( f"mkdir -p {shlex.quote( builds( root ) )} && cat > {shlex.quote( path )}",
                      quiet = True, input = yamlish.dump( record ) )


def made( layer, stamp: str ) -> float | None:
    """When that artefact was last written, as far as its stamp says."""
    try:
        return layer.made( stamp ) if hasattr( layer, "made" ) else float( stamp.split()[ 0 ] )
    except ( ValueError, IndexError ):
        return None


def newer_input( layer, ctx, stamp: str ) -> str | None:
    """The file of the declaration newer than the artefact, if there is one.

    Only asked of what errand knows nothing about: dates are wrong about a
    `git checkout` and blind to what is not a file, so as soon as there is a
    fingerprint to compare, it is what decides.
    """
    when = made( layer, stamp )
    if when is None:
        return None
    files = [ p for p in layer.spec( ctx ) if isinstance( p, Path ) and p.exists() ]
    newest = max( files, key = lambda p: p.stat().st_mtime, default = None )
    # in whole seconds: that is what a stamp holds
    return newest.name if newest is not None and int( newest.stat().st_mtime ) > when else None


def verdict( want: str, record: dict, stamp: str ) -> str:
    """What the record says of an artefact that is there: ok, adopted, stale or found.

    A changed declaration comes first, stamp or no stamp: it is a difference
    from a record errand itself wrote. A stamp that changed alone means the
    record no longer describes what is there, so nothing is known about it.
    """
    built = record.get( "built" ) or { }
    if not built:
        return FOUND
    if built.get( "fingerprint" ) != want:
        return STALE
    if built.get( "stamp" ) and stamp and built[ "stamp" ] != stamp:
        return FOUND
    return ADOPTED if built.get( "origin" ) == "adopted" else OK


def retried( layer, record: dict ) -> bool:
    """Did the last attempt leave something to make up for? Not when it was built
    aside: what failed then touched nothing, and being stale is its own reason."""
    return bool( record.get( "last_attempt" ) ) and not getattr( layer, "aside", False )


def status( root: Path, env, ctx ) -> str:
    """ok / adopted / stale / not built / unknown / unreachable -- what `errand envs` prints."""
    if len( env.places() ) > 1:
        said = [ status( root, one, ctx ) for one in env.places() ]
        return next( ( s for s in said if s != OK ), OK )
    if env.missing is not None:
        return UNREACHABLE
    want = wanted( env, ctx )
    if not want:
        return UNKNOWN if env.wraps_anything() else OK
    if env.ssh or getattr( env.vm, "is_box", False ):
        return UNKNOWN           # only the other machine can say
    for _, layer in env.layers():
        if hasattr( layer, "probe" ) and not layer.probe( ctx ):
            return MISSING
    states = [ ]
    for i, layer in env.layers():
        if not hasattr( layer, "spec" ):
            continue
        record, stamp = look( root, layer, ctx )
        state = verdict( want[ f"{i}:{layer.describe()}" ], record, stamp )
        failed = record.get( "last_attempt" )
        if failed and ( state in ( STALE, FOUND ) or retried( layer, record ) ):
            return f"{STALE} ( last build failed, {failed.get( 'date' )} )"
        # Nothing recorded and everything present: it is somebody else's doing,
        # and it will be adopted rather than rebuilt -- so calling it `stale`
        # would be announcing work that is not going to happen.
        if state == FOUND:
            state = STALE if getattr( layer, "aside", False ) and newer_input( layer, ctx, stamp ) else OK
        states.append( state )
    return next( ( s for s in ( STALE, ADOPTED ) if s in states ), OK )


def _inside( env, ctx ):
    """-> layer -> the context to build it in when it is after a scheduler held warm, else None.
    The allocation is reached ( held, if it is not ) only once one such layer is looked at."""
    from .cli import alive
    stack = env.stack_for( "run" )
    sched = alive.scheduler( stack )
    after = { id( l ) for l in stack[ stack.index( sched ) + 1 : ] } if sched is not None else set()
    made = { }

    def inside( layer ):
        if id( layer ) not in after:
            return None
        if "ctx" not in made:
            from types import SimpleNamespace
            from . import bootstrap
            ssh = env.ssh
            there = ssh.remote_root( ctx ) if ssh is not None else ctx.root
            cache = bootstrap.ship( ssh.host, ssh.options ) if ssh is not None else None
            made[ "ctx" ] = alive.Allocation( env, ctx.tags, SimpleNamespace(
                root = ctx.root, ssh = ssh, there = L.remote_path( there ) if ssh else Path( there ), cache = cache ) ).inside()
        return made[ "ctx" ]

    return inside


def ensure( root: Path, env, ctx, *, force = False, echo = print, dry_run = False, asked = False ) -> int:
    """Build or update whatever `env` declares and does not have.

    **What is already there was built by somebody, and is adopted rather than
    rebuilt.** The first time errand meets an environment there is no record of
    what it was built from, so every layer looks out of date -- and acting on
    that reading would mean recreating, on somebody's first command, an
    environment that has been working for months. So: present and never seen
    before is recorded as such, and only a declaration that has CHANGED since a
    record errand itself wrote is a reason to touch it. `errand setup --force` is
    how you say the other thing.

    The one exception is what is built aside, which a build cannot harm: found
    older than its own recipe, it is rebuilt. An adoption is a guess, and a wrong
    one has cost a whole release built in an image missing a pin.

    A layer that builds on somebody's own machine ( `setup_only`: a `WindowsBox` ) is built only when asked, by
    `errand setup` ( `asked` ): any other command stops, and says so.

    An environment that prepares on another machine is set up machine by machine ( `Env.places` ).
    """
    if len( env.places() ) > 1:
        return max( ensure( root, one, ctx, force = force, echo = echo, dry_run = dry_run, asked = asked )
                    for one in env.places() )
    # Asked of, and built on, the machine the environment lives on: a layer
    # must not answer with what it finds here ( a root prefix, a binary ).
    there = ctx
    if env.ssh is not None:
        place = env.ssh.place( ctx )
        there = L.Context( root = place.root, tags = ctx.tags, remote = True, host = place,
                           origin = ctx.origin )
    inside = _inside( env, ctx )
    lacking = lacks( env, ctx, there, inside )
    if lacking:
        for line in lacking:
            echo( f"  {env.name}: {line}" )
        return 1
    jobs, adopted = [ ], [ ]
    for _, layer in env.layers():
        if not isinstance( layer, L.Artefact ):
            continue
        # After a scheduler held warm, a layer is built where it is used: in the allocation.
        at = inside( layer ) or there
        want = L.fingerprint( *layer.spec( ctx ) ) if hasattr( layer, "spec" ) else None
        present = _present( layer, at )
        record, stamp = look( root, layer, at )
        state = verdict( want, record, stamp )
        build = force or not present or state == STALE or retried( layer, record )
        if state == FOUND and not build:
            older = newer_input( layer, ctx, stamp )
            if older and getattr( layer, "aside", False ):
                echo( f"  {layer.describe()}: older than {older}, and errand has no record of it" )
                build = True
            elif older:
                echo( f"  {layer.describe()}: older than {older}: adopted as it is ( errand setup --force to rebuild )" )
        steps = layer.build( at ) if build else [ ]
        if steps:
            jobs.append( ( layer, want, steps, record, stamp, present, at ) )
        elif state == FOUND or ( build and state == STALE ):
            adopted.append( ( layer, want, stamp, at ) )    # nothing to do, or nothing it could do

    if not dry_run:
        for layer, want, stamp, at in adopted:
            write( root, layer, at, { "built": _built( want, stamp, "adopted" ) } )
    if not jobs:
        return 0
    held = [ layer for layer, *_ in jobs if getattr( layer, "setup_only", False ) ]
    if held and not asked and not dry_run:
        for layer in held:
            echo( f"  {env.name}: {layer.describe()} is not set up for this declaration: "
                  f"errand setup --env {env.name} ( it installs on that machine )" )
        return 1

    why = "rebuilding" if force else "bringing up to date"
    echo( f"  {why} {env.name}" )
    if not dry_run and env.ssh is not None:
        # A recipe, a requirements file, a project to install in editable mode:
        # all of them are files HERE, and the build happens THERE. Pushing
        # first is what makes `errand setup` over ssh mean the same thing as
        # `errand setup` at home.
        echo( f"    {L.transfer( env.ssh.transfer )} push -> {env.ssh.host}:{env.ssh.remote_root( ctx )}" )
        L.push( ctx.root, env.ssh.host, env.ssh.remote_root( ctx ), env.ssh.options, echo = echo,
                transfer_by = env.ssh.transfer )
    if dry_run:
        for layer, _, steps, *_ in jobs:
            for step in steps:
                echo( f"    would run: {step}" )
        return 0

    for layer, want, steps, record, stamp, present, there in jobs:
        log = f"{builds( root )}/{slug( layer )}.log"
        if _windows_here( there ):
            ( there.host.root / log ).parent.mkdir( parents = True, exist_ok = True )
            ( there.host.root / log ).write_text( "" )
        else:
            there.host.shell( f"mkdir -p {shlex.quote( builds( root ) )} && : > {shlex.quote( log )}", quiet = True )
        for step in steps:
            echo( f"    $ {step}" )
            # A step is a shell line, or -- when it takes more than one line and
            # decisions between them -- something to call, which runs its lines
            # through `there.host` itself and says how it went.
            if callable( step ):
                code = step( echo )
            elif _windows_here( there ):
                code = _tee_here( there.host, step, there.host.root / log )
            else:
                code = there.host.shell( _logged( step, log ), tty = True ).returncode
            if code != 0:
                if hasattr( layer, "abandon" ):
                    there.host.shell( layer.abandon( there ), quiet = True )
                write( root, layer, there, { **record, "last_attempt": { "fingerprint": want, "date": _now(),
                                                                         "step": str( step ), "code": code } } )
                echo( f"    failed while preparing {layer.describe()} ( output: {log} )" )
                if present:
                    echo( f"    {_existing( layer, stamp )}: --no-setup uses it as it is" )
                return 1
        write( root, layer, there, { "built": _built( want, look( root, layer, there )[ 1 ], "built" ) } )
    return 0


# What errand started on Windows runs here itself: the rest needs a POSIX machine, which an `Ssh` leads to.
ON_WINDOWS_HERE = ( "Vars", "Venv", "Uv", "Missing", "Preload" )


def lacks( env, ctx, there, inside = None ) -> list:
    """What the layers of `env` require ( `requires` ) and do not find where they run: one shell line per place, asked
    before anything is built. -> [ "on build-box: apptainer, not found ( apptainer:… )" ]."""
    if L.WINDOWS and not there.host.remote:
        posix = [ l for _, l in env.layers()
                  if not isinstance( l, L.Gateway ) and type( l ).__name__ not in ON_WINDOWS_HERE ]
        stack = [ l for _, l in env.layers() ]
        if posix and not ( stack and isinstance( stack[ 0 ], L.Gateway ) ):
            return [ f"here: {l.describe()} needs a POSIX machine, and this is Windows: put an Ssh to one before it"
                     for l in posix ]
    by_place = { }
    overlays = [ ]          # ( place, layer ): what a command is run through before the layers after it
    for _, layer in env.layers():
        at = ( inside( layer ) if inside else None ) or there
        requires = getattr( layer, "requires", None )     # a layer may be anything with the methods it uses
        # Asked as the command will be: through the overlays before it there ( a `Module( "singularity" )`
        # puts `singularity` on the PATH of what comes after it ).
        through = [ o for where, o in overlays if where is at ]
        for test, what in ( requires( at ) if requires else ( ) ):
            if through:
                test = L.compose( through, L.Command( [ "sh", "-c", test ] ), at ).shell()
            by_place.setdefault( id( at ), ( at, [ ] ) )[ 1 ].append( ( test, what, layer ) )
        if isinstance( layer, L.Overlay ):
            overlays.append( ( at, layer ) )
    out = [ ]
    for at, checks in by_place.values():
        if _windows_here( at ):
            import shutil
            place = "here"
            for test, what, layer in checks:
                words = shlex.split( test )
                found = shutil.which( words[ 2 ] ) is not None if words[ : 2 ] == [ "command", "-v" ] and len( words ) == 3 else None
                if found is None:
                    try:
                        found = at.host.shell( test, quiet = True ).returncode == 0
                    except L.NeedsAShell:
                        found = True          # cannot be asked here: the build says it, if it is so
                if not found:
                    out.append( f"{place}: {what} ( {layer.describe()} )" )
            continue
        # One group: a host that says `cd <root> && <line>` ( the allocation's ) must not read a root not
        # pushed yet as every check failing.
        line = "{ " + "; ".join( f"{{ {test} ; }} >/dev/null 2>&1 || echo errand-lacks-{i}" for i, ( test, _, _ ) in enumerate( checks ) ) + "; }"
        got = at.host.shell( line, capture = True )
        failed = { int( w[ len( "errand-lacks-" ): ] ) for w in ( got.stdout or "" ).split() if w.startswith( "errand-lacks-" ) }
        place = "here" if not at.host.remote else f"on {at.host.describe()}"
        out += [ f"{place}: {what} ( {layer.describe()} )" for i, ( _, what, layer ) in enumerate( checks ) if i in failed ]
    return out


def _built( want, stamp, origin ) -> dict:
    return { "fingerprint": want, "stamp": stamp, "origin": origin, "date": _now(),
             "by": f"{getpass.getuser()}@{socket.gethostname()}" }


def _now() -> str:
    return time.strftime( "%Y-%m-%d %H:%M:%S" )


def _existing( layer, stamp: str ) -> str:
    when = made( layer, stamp )
    date = f", from {time.strftime( '%Y-%m-%d', time.localtime( when ) )}," if when else ""
    return ( f"the existing one{date} is untouched" if getattr( layer, "aside", False )
             else f"the existing one{date} may be half updated" )


def _tee_here( host, step: str, log: Path ) -> int:
    """`step` run here, its output shown and kept in `log`, as `_logged` does through a shell."""
    import subprocess, sys
    proc = subprocess.Popen( L.windows_argv( step ), cwd = str( host.root ), stdout = subprocess.PIPE,
                             stderr = subprocess.STDOUT )
    with open( log, "ab" ) as kept:
        for chunk in iter( lambda: proc.stdout.read1( 65536 ), b"" ):
            sys.stdout.buffer.write( chunk )
            sys.stdout.flush()
            kept.write( chunk )
    return proc.wait()


def _logged( step: str, log: str ) -> str:
    """`step`, its output also going to `log`, and its exit code kept: the shell
    of the other machine is whatever it is, so no `pipefail`."""
    q, code = shlex.quote( log ), shlex.quote( f"{log}.code" )
    return ( f"{{ ( {step} ); echo $? > {code}; }} 2>&1 | tee -a {q}; "
             f"exit \"$( cat {code} 2>/dev/null || echo 1; rm -f {code} )\"" )


def _present( layer, ctx ) -> bool:
    """Is that layer THERE -- asked of the machine it would be built on.

    A remote environment's image does not live here, and answering "is it
    there" against this filesystem is answering about the wrong machine: an
    image built on the cluster last week would be rebuilt on every command,
    and one sitting here would never be built over there at all. So a layer
    may offer a `probe_shell`, a command whose exit code is the answer, and
    over ssh that is what is asked -- there, in the remote root.
    """
    if not hasattr( layer, "probe" ):
        return True
    if not ctx.host.remote:
        return layer.probe( ctx )
    if not hasattr( layer, "probe_shell" ):
        return False          # cannot ask: better to build than to assume
    return ctx.host.shell( layer.probe_shell( ctx ), quiet = True ).returncode == 0
