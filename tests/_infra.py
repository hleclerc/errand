"""Reaching a second machine, without needing a second machine.

`ssh localhost` IS another machine as far as every part of errand that matters
is concerned: it is a real ssh, a real rsync, a real remote shell, a real
round trip through a directory that is not the project's. Only the hardware is
shared, and the hardware is not what is being tested.

So the order is: whatever `errand-envs.py` names, else localhost when it
answers, else skip saying what to do about it. A suite that exercises the ssh
path on any developer's machine is worth more than one that waits for a
cluster.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from errand import have, need, skip

# Enough to reach a freshly-installed localhost without a prompt. Accepting a
# new host key is a decision, so it is written here rather than baked into the
# Ssh layer, where it would silently weaken every real connection.
LOCALHOST_OPTIONS = [ "-o", "BatchMode=yes",
                      "-o", "ConnectTimeout=5",
                      "-o", "StrictHostKeyChecking=accept-new" ]


def _reaches( host, options ):
    if shutil.which( "ssh" ) is None or shutil.which( "rsync" ) is None:
        return False
    try:
        return subprocess.run( [ "ssh", *options, host, "true" ],
                               stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL,
                               timeout = 20 ).returncode == 0
    except ( OSError, subprocess.SubprocessError ):
        return False


def ssh_target( ):
    """-> ( host, options, root_factory ). Skips when there is nothing to reach."""
    if have( "ssh_host" ):
        host = need( "ssh_host" )
        options = need( "ssh_options" ) if have( "ssh_options" ) else [ ]
        if not _reaches( host, options ):
            skip( f"errand-envs.py names ssh_host = {host!r}, but `ssh {host} true` fails",
                  "a named host that cannot be reached is a broken setup, not a missing one" )
        root = need( "ssh_root" ) if have( "ssh_root" ) else None
        return host, options, ( lambda: root ) if root else _tmp_root

    if _reaches( "localhost", LOCALHOST_OPTIONS ):
        return "localhost", list( LOCALHOST_OPTIONS ), _tmp_root

    skip( "no machine to reach: `ssh localhost true` does not answer",
          "either enable ssh to localhost, or name one in errand-envs.py:\n"
          "    ssh_host = 'some-host'\n"
          "    ssh_root = '/home/me/scratch/errand-test'   # optional; a temp dir otherwise" )


def _tmp_root( ):
    """A directory over there that is not the project's, and is ours to delete.

    Deliberately a real path under the system temp rather than a fixed one:
    the push does `rsync --delete`, and nothing that answers to that should
    ever be somewhere a person keeps things.
    """
    return tempfile.mkdtemp( prefix = "errand-remote-", dir = _remote_tmp() )


def _remote_tmp( ):
    return os.environ.get( "TMPDIR" ) or "/tmp"


VENDOR = "_lib"

# Small, and on every registry. A container test wants an interpreter and
# nothing else: what is being tested is the layer, not the image.
BASE_IMAGE = "python:3-slim"


def _responds( argv, timeout = 30 ):
    if shutil.which( argv[ 0 ] ) is None:
        return False
    try:
        return subprocess.run( argv, stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL,
                               timeout = timeout ).returncode == 0
    except ( OSError, subprocess.SubprocessError ):
        return False


def container_engines( ):
    """Which engines are installed AND answering, here and now.

    Installed is not enough: docker without a running daemon, or without the
    caller in its group, is present and useless. The difference matters, and
    the message says which it is.
    """
    out = { }
    for name, probe in ( ( "apptainer", [ "apptainer", "--version" ] ),
                         ( "docker",    [ "docker", "info" ] ),
                         ( "podman",    [ "podman", "info" ] ) ):
        if shutil.which( name ) is None:
            out[ name ] = "absent"
        elif _responds( probe ):
            out[ name ] = "ready"
        else:
            out[ name ] = "installed but not answering"
    return out


def container_engine( only = None ):
    """The first engine that can actually run something. Skips otherwise."""
    state = container_engines()
    for name, how in state.items():
        if how == "ready" and ( only is None or name == only ):
            return name
    shown = ", ".join( f"{n}: {h}" for n, h in state.items() )
    skip( f"no container engine to run in ({shown})",
          "install one, or start its daemon -- `docker info` answering is the test.\n"
          "  nothing here needs a GPU or a private registry, only " + BASE_IMAGE )


def write_project( directory: Path, config: str, files: dict, vendor = False ):
    """A whole little project on disk, for an end-to-end run.

    `vendor` puts a copy of errand itself inside the project, under `_lib`.
    That is how the remote side gets one: the push rsyncs the project, so
    errand travels with it and the test needs nothing installed over there --
    which is the difference between a test that runs on any machine and one
    that runs on a machine somebody prepared.
    """
    directory.mkdir( parents = True, exist_ok = True )
    ( directory / "errand-project.py" ).write_text( config )
    for name, text in files.items():
        path = directory / name
        path.parent.mkdir( parents = True, exist_ok = True )
        path.write_text( text )
    if vendor:
        import errand
        source = Path( errand.__file__ ).resolve().parent
        shutil.copytree( source, directory / VENDOR / "errand",
                         ignore = shutil.ignore_patterns( "__pycache__" ) )
    return directory


def run_errand( directory: Path, *args, timeout = 600 ):
    """`errand` as a real subprocess, in `directory`. -> ( returncode, output ).

    A TOP-LEVEL invocation, on a queue of its own. Both matter: an inherited
    claim would make the run under test skip the queue entirely, and the real
    queue would make it wait for -- or deadlock against -- the claim held by
    the entry that started it.
    """
    import errand
    env = dict( os.environ )
    env.pop( "ERRAND_CLAIM", None )
    queue = directory / ".queue"
    queue.mkdir( parents = True, exist_ok = True )
    env[ "XDG_RUNTIME_DIR" ] = str( queue )
    package_root = str( Path( errand.__file__ ).resolve().parent.parent )
    env[ "PYTHONPATH" ] = os.pathsep.join(
        [ package_root, *filter( None, [ env.get( "PYTHONPATH" ) ] ) ] )
    got = subprocess.run( [ "python3", "-m", "errand", *args ], cwd = directory, env = env,
                          capture_output = True, text = True, timeout = timeout )
    return got.returncode, got.stdout + got.stderr
