"""errand itself, on a machine it was not installed on.

Over `Ssh`, the command that crosses is errand: `python -m errand run ...`, which
then runs the work in the environment asked for. Two things must therefore be
true over there before anything else can be, and neither is the environment's
business:

* **errand is importable.** Its sources travel: `ship` rsyncs the package to
  `~/.cache/errand/src/<key>/errand/`, one copy per checkout here, and the
  command becomes `python <copy>/errand/_boot.py ...`. Nothing is installed,
  and the errand that answers is the one that asked -- no version skew.

* **a Python errand can run on exists.** Where a layer chooses the interpreter
  ( a venv, a micromamba environment, a container ) it is that one, as always.
  Where none does -- `Ssh` followed by `Vars`, `Module`, `Nix`, `Slurm` -- the
  command looks for one where it starts, AFTER the layers: a `Module` or a `Nix`
  shell puts its own python on the PATH, and the entries errand imports run in
  errand's own interpreter, so that is the one it must be. It tries the `python`
  the `Ssh` layer names, then a copy made earlier, then `python3`, `python3.14`
  ... down to the oldest errand runs on. Found none, it makes one for errand
  alone, in `~/.cache/errand/python`: with `uv` when the machine has it, else
  micromamba, mamba or conda, else with a `uv` it fetches from astral.sh into
  `~/.cache/errand/uv` ( never on the PATH, never in a shell profile ). The
  Python uv downloads goes under `~/.cache/errand/uv-python` too: everything
  errand made for itself is in one directory, and removing it undoes it all.

  Under a scheduler the command starts on a compute node, which may have no
  network to fetch anything with: the same search is then made once on the
  machine `Ssh` reaches before submitting, so what has to be made is made
  there.

`~/.cache/errand` is in the home directory on purpose: on a cluster it is the
directory the login node and the compute nodes share, so what the login node
found or made is what the job running errand on a node uses.
"""
from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
from pathlib import Path

# The oldest Python errand runs on. pyproject's `requires-python` says the same.
MIN = ( 3, 8 )
# What a Python made for errand is.
MADE = "3.12"
BASE = ".cache/errand"                          # relative to $HOME over there

PACKAGE = Path( __file__ ).resolve().parent


def is_errand( argv ) -> bool:
    """`python -m errand ...`: a command that is errand itself."""
    from .layers import INTERPRETERS
    import sys
    return ( len( argv ) >= 3 and ( Path( str( argv[ 0 ] ) ).name in INTERPRETERS or str( argv[ 0 ] ) == sys.executable )
             and str( argv[ 1 ] ) == "-m" and str( argv[ 2 ] ).split( "." )[ 0 ] == "errand" )


def key() -> str:
    """One copy over there per checkout here: two checkouts of different
    versions reaching the same machine must not overwrite each other."""
    from . import __version__
    digest = hashlib.sha1( str( PACKAGE ).encode() ).hexdigest()[ : 8 ]
    return f"{__version__}-{digest}"


_sources = None


def sources_key( fresh = False ) -> str:
    """What errand's sources ARE, not where they are: an agent started from other
    sources is another agent ( ADR 0005, staleness ). `fresh`: what they are now,
    for a process that may have outlived them."""
    global _sources
    if _sources is None or fresh:
        h = hashlib.sha1()
        for p in sorted( PACKAGE.rglob( "*.py" ) ):
            h.update( str( p.relative_to( PACKAGE ) ).encode() + b"\0" + p.read_bytes() )
        if not fresh or _sources is None:
            _sources = h.hexdigest()[ : 12 ]
        return h.hexdigest()[ : 12 ]
    return _sources


def src_rel() -> str:
    return f"{BASE}/src/{key()}"


def ship( host: str, options = ( ), agent = True ) -> str:
    """The package, to `~/<src_rel>/errand/` on `host`: -> $HOME over there.

    Skipped when what is there says it is these sources already ( `.sources` ),
    which costs one line through the agent rather than an rsync."""
    from .layers import _remote, _rsh
    dest = src_rel()
    key = sources_key()
    got = _remote( host, options, f'mkdir -p {shlex.quote( dest )} && echo "ERRAND_HOME=$HOME" && '
                                  f'cat {shlex.quote( dest )}/errand/.sources 2>/dev/null; true', agent = agent )
    if got.returncode:
        raise subprocess.CalledProcessError( got.returncode, "mkdir", got.stdout, got.stderr )
    if key not in ( got.stdout or "" ).split():
        subprocess.run( [ "rsync", "-a", "--delete", *_rsh( options, host, agent ), "--exclude=__pycache__",
                          "--exclude=.sources", f"{PACKAGE}/", f"{host}:{dest}/errand/" ],
                        check = True, stdin = subprocess.DEVNULL )
        _remote( host, options, f"echo {key} > {shlex.quote( dest )}/errand/.sources", agent = agent )
    return _said( "ERRAND_HOME", got.stdout )


def _said( name, out ):
    found = re.findall( rf"^{name}=(.+)$", out or "", re.M )
    return found[ -1 ].strip() if found else None


# POSIX sh: `pick_python` looks for a Python errand runs on, `make_python` makes one; both set
# `$py`. What they do is said on stderr, prefixed `errand:`.
FUNCTIONS = r"""
base="$HOME/""" + BASE + r""""
say() { echo "errand: $*" >&2; }
ok() { "$1" -c "import sys; sys.exit( sys.version_info < ( $major, $minor ) )" >/dev/null 2>&1; }
pick_python() {
    for c in "$want" "$base/python/bin/python" python3 python3.14 python3.13 python3.12 python3.11 \
             python3.10 python3.9 python3.8 python; do
        p=$( command -v "$c" 2>/dev/null ) || continue
        ok "$p" && { py="$p"; return 0; }
    done
    return 1
}
make_python() {
    # One maker at a time: two runs starting together must not build in the same directory.
    mkdir -p "$base" || return 1
    lock="$base/python.lock"; waited=0
    until mkdir "$lock" 2>/dev/null; do
        [ $waited -ge 900 ] && { say "$lock is held for 15 min: remove it if nothing is building"; return 1; }
        sleep 2; waited=$(( waited + 2 ))
    done
    trap 'rmdir "$lock" 2>/dev/null' EXIT
    if ! ok "$base/python/bin/python"; then
        say "no python >= $major.$minor here: making one for errand alone, in $base/python"
        rm -rf "$base/python"
        uv=$( command -v uv 2>/dev/null )
        for c in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" "$base/uv/uv"; do
            [ -z "$uv" ] && [ -x "$c" ] && uv="$c"
        done
        if [ -n "$uv" ]; then
            UV_PYTHON_INSTALL_DIR="$base/uv-python" "$uv" venv -q --python "$made" "$base/python" >&2
        elif conda=$( command -v micromamba || command -v mamba || command -v conda ); then
            "$conda" create -y -q -p "$base/python" -c conda-forge "python=$made" >&2
        else
            say "neither uv nor micromamba nor conda: fetching uv into $base/uv"
            if command -v curl >/dev/null 2>&1; then
                curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$base/uv" sh >&2
            elif command -v wget >/dev/null 2>&1; then
                wget -qO- https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$base/uv" sh >&2
            else
                say "no curl nor wget either: install python >= $major.$minor, or name one with Ssh( python = ... )"
            fi
            [ -x "$base/uv/uv" ] && UV_PYTHON_INSTALL_DIR="$base/uv-python" "$base/uv/uv" venv -q --python "$made" "$base/python" >&2
        fi
    fi
    rmdir "$lock" 2>/dev/null; trap - EXIT
    ok "$base/python/bin/python" || { say "making a python in $base/python failed"; rm -rf "$base/python"; return 1; }
    py="$base/python/bin/python"
}
"""


def _script( then: str, preferred: str, minimum = MIN, made = MADE ) -> str:
    q = shlex.quote
    return ( f"want={q( preferred )}; major={minimum[ 0 ]}; minor={minimum[ 1 ]}; made={q( made )}\n"
             + FUNCTIONS + "pick_python || make_python || exit 1\n" + then )


def find_line( preferred: str = "python3", minimum = MIN, made = MADE ) -> str:
    """The shell line that finds -- or makes -- a Python for errand, and says
    `ERRAND_PYTHON=<path>` on stdout."""
    return " ".join( shlex.quote( a ) for a in
                     ( "sh", "-c", _script( 'echo "ERRAND_PYTHON=$py"\n', preferred, minimum, made ) ) )


def find( host, preferred = "python3", echo = print ) -> str:
    """Over `host` ( a `layers.Over` ), the Python errand runs on.

    Raises RuntimeError with what the other side said when there is none to be had."""
    got = host.shell( find_line( preferred ), capture = True )
    for line in ( got.stderr or "" ).splitlines():
        if line.startswith( "errand:" ):
            echo( f"  {line}" )
    python = _said( "ERRAND_PYTHON", got.stdout )
    if got.returncode or python is None:
        tail = "\n".join( ( got.stderr or "" ).strip().splitlines()[ -6 : ] )
        raise RuntimeError( f"no Python >= {MIN[ 0 ]}.{MIN[ 1 ]} for errand on {host.describe()}"
                            + ( f":\n{tail}" if tail else "" ) )
    return python


def boot_rel() -> str:
    """The file a shipped errand is started from, relative to $HOME over there."""
    return f"{src_rel()}/errand/_boot.py"


def prepare( ssh, inner, there, echo = print ) -> str:
    """What must be over there before errand can start there: -> $HOME over there."""
    from . import layers as L
    home = ship( ssh.host, ssh.options )
    if not L.chooses_python( inner ) and L.batch_of( inner ) is not None:
        find( there, ssh.python, echo )
    return home


def command( cmd, inner, home: str, preferred: str = "python3", boot: str | None = None ):
    """`cmd`, errand itself ( `python -m errand…`, or one of its modules ), as it must cross to
    start over there.

    A layer that chooses the interpreter replaces `python` as it always did; the
    file it is handed is the shipped copy -- or `boot`, a copy that is already
    where the command starts ( this machine's ). With none, the command finds its
    Python where it starts. A Docker or Podman container keeps `-m errand`: the
    home directory the copy lives in is not inside it."""
    from . import layers as L
    argv = list( cmd.argv )
    if not is_errand( argv ):
        return cmd
    if any( isinstance( l, L.Docker ) for l in inner ):
        return L.Command( L.under( argv, preferred ), cmd.env )
    module = str( argv[ 2 ] )
    rest = ( [ ] if module == "errand" else [ "-m", module ] ) + [ str( a ) for a in argv[ 3 : ] ]
    if L.chooses_python( inner ):
        return L.Command( [ "python", boot or f"{home}/{boot_rel()}", *rest ], cmd.env )
    where = shlex.quote( boot ) if boot else f'"$HOME"/{shlex.quote( boot_rel() )}'
    then = f'exec "$py" {where} "$@"\n'
    return L.Command( [ "sh", "-c", _script( then, preferred ), "sh", *rest ], cmd.env )
