"""errand itself, on a machine it was not installed on.

Over `Ssh`, the command that crosses is errand: `python -m errand run ...`, which
then runs the work in the environment asked for. Two things must therefore be
true over there before anything else can be, and neither is the environment's
business:

* **errand is importable.** Its sources travel: `ship` sends the package, one tar on stdin, to
  `~/.cache/errand/src/<version>-<content key>/errand/`, one copy per content of the sources, and the
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
found or made is what the job running errand on a node uses. `ERRAND_CACHE_DIR`,
set in the account's shell profile on a machine, puts it elsewhere on that
machine: a home with little room. It is the machine's, not a project's -- the
agents there serve every project -- so it is read over there, through the same
interactive shell every remote command goes through, never sent from here.
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
BASE = ".cache/errand"                          # relative to $HOME, unless ERRAND_CACHE_DIR says otherwise
ENV = "ERRAND_CACHE_DIR"
# The same, as the shell over there computes it: quoted, ready to be followed by `/<sub>`.
SH_BASE = '"${ERRAND_CACHE_DIR:-$HOME/.cache/errand}"'


def local_cache( ) -> Path:
    """errand's per-user directory on this machine."""
    import os
    return Path( os.environ.get( ENV ) or Path.home() / BASE ).expanduser()

PACKAGE = Path( __file__ ).resolve().parent


def is_errand( argv ) -> bool:
    """`python -m errand ...`: a command that is errand itself."""
    from .layers import INTERPRETERS
    import sys
    return ( len( argv ) >= 3 and ( Path( str( argv[ 0 ] ) ).name in INTERPRETERS or str( argv[ 0 ] ) == sys.executable )
             and str( argv[ 1 ] ) == "-m" and str( argv[ 2 ] ).split( "." )[ 0 ] == "errand" )


def key() -> str:
    """One copy over there per content of the sources: an edit here is a new directory there, never
    one rewritten under an agent or a run that started from it. Two checkouts that hold the same
    sources share one copy; two that do not never overwrite each other."""
    from . import __version__
    return f"{__version__}-{sources_key()}"


def _shipped( ):
    """The files of the package that travel: no caches, no `.sources`."""
    for p in sorted( PACKAGE.rglob( "*" ) ):
        rel = p.relative_to( PACKAGE )
        if "__pycache__" in rel.parts or rel.name == ".sources" or p.is_dir():
            continue
        yield p, rel


_sources = None


def sources_key( fresh = False ) -> str:
    """What errand's sources ARE, not where they are: an agent started from other
    sources is another agent ( ADR 0005, staleness ). `fresh`: what they are now,
    for a process that may have outlived them."""
    global _sources
    if _sources is None or fresh:
        h = hashlib.sha1()
        for p, rel in _shipped():                # what is shipped, all of it: not only the `.py`
            h.update( rel.as_posix().encode() + b"\0" + p.read_bytes() )
        if not fresh or _sources is None:
            _sources = h.hexdigest()[ : 12 ]
        return h.hexdigest()[ : 12 ]
    return _sources


def src_rel() -> str:
    """Where the copy of these sources is, relative to errand's per-user directory."""
    return f"src/{key()}"


def ship( host: str, options = ( ), agent = True ) -> str:
    """The package, to `<cache>/<src_rel>/errand/` on `host`: -> `<cache>`, errand's per-user
    directory over there ( `ERRAND_CACHE_DIR`, else `~/.cache/errand` ).

    Skipped when what is there says it is these sources already ( `.sources` ), which costs one
    line. Otherwise one tar crosses, on the stdin of that same kind of line, and is unpacked
    beside the copy before it takes its place ( ADR 0006 ): nothing but sh and tar is needed over there, and a
    copy is whole or not there. New sources mean a new agent ( `sources_key` ), whose start ships
    them: there is no agent of these sources yet to sync them through."""
    from .layers import _remote
    sub = shlex.quote( src_rel() )
    key = sources_key()
    # `.sources` is written last, once every file is there; a copy without `_boot.py` is not one either.
    got = _remote( host, options, f'b={SH_BASE}; mkdir -p "$b"/{sub} && echo "ERRAND_CACHE=$b" && '
                                  # touched: a copy in use is not one to prune ( `prune_sources` )
                                  f'{{ [ -f "$b"/{sub}/errand/_boot.py ] && touch "$b"/{sub}/errand/.sources && '
                                  f'cat "$b"/{sub}/errand/.sources 2>/dev/null; true; }}',
                   agent = agent, interactive = True )
    from .layers.gateways import unreachable
    stop = unreachable( host, got )
    if stop is not None:
        raise stop
    cache = _said( "ERRAND_CACHE", got.stdout )
    if got.returncode or not cache:
        raise subprocess.CalledProcessError( got.returncode or 1, "mkdir", got.stdout, got.stderr )
    dest = f"{cache}/{src_rel()}"
    if key not in ( got.stdout or "" ).split():
        line = f"sh -c {shlex.quote( UNPACK )} sh {shlex.quote( dest + '/errand' )} {key}"
        done = _remote( host, options, line, agent = agent, input = package_tar() )
        if done.returncode:
            raise subprocess.CalledProcessError( done.returncode, "unpack errand's sources", done.stdout, done.stderr )
    return cache


KEEP_SOURCES_DAYS = 14     # a copy nothing names any more stays that long after its last use: a job
                           # waiting in a queue starts from the copy it was submitted with


def _key_of_copy( d: Path ) -> str:
    """The sources key a copy holds: what its `.sources` says, else the end of its name."""
    try:
        return ( d / "errand" / ".sources" ).read_text().strip() or d.name.rsplit( "-", 1 )[ -1 ]
    except OSError:
        return d.name.rsplit( "-", 1 )[ -1 ]


def keys_in_use( base: Path ) -> set:
    """The sources keys an agent or a hub of this machine was started from ( `env-<key>-…`, `host-<key>…`,
    `hub-<key>` ): while its directory is there -- it serves, or holds a session somebody may come back
    for -- the copy it starts from is needed."""
    names = [ d.name for d in ( base / "agents" ).iterdir() ] if ( base / "agents" ).is_dir() else [ ]
    names += [ d.name for d in base.glob( "hub-*" ) ]
    return { n.split( "-" )[ 1 ] for n in names if n.split( "-" )[ 0 ] in ( "env", "host", "hub" ) and "-" in n }


def prune_sources( base: Path, keep = ( ), days = KEEP_SOURCES_DAYS, now = None ) -> list:
    """The copies of errand's sources in `base/src` that nothing needs any more, removed: no agent or hub
    started from them ( `keys_in_use` ), not `keep`, and not used for `days` ( `ship` touches `.sources`
    each time it finds a copy whole ). What a shipping left half done goes after an hour.
    -> the directories removed."""
    import shutil
    import time
    now = time.time() if now is None else now
    src = base / "src"
    if not src.is_dir():
        return [ ]
    used = keys_in_use( base ) | set( keep )
    gone = [ ]
    for d in src.iterdir():
        try:
            if not d.is_dir() or d.is_symlink():
                continue
            name = d.name
            if ".part" in name or ".old." in name:
                stale = now - d.stat().st_mtime > 3600
            else:
                if _key_of_copy( d ) in used:
                    continue
                stamp = d / "errand" / ".sources"
                last = max( p.stat().st_mtime for p in ( d, stamp ) if p.exists() )
                stale = now - last > days * 86400
        except OSError:
            continue
        if stale:
            shutil.rmtree( d, ignore_errors = True )
            gone.append( d )
    return gone


def _said( name, out ):
    found = re.findall( rf"^{name}=(.+)$", out or "", re.M )
    return found[ -1 ].strip() if found else None


# POSIX sh: `pick_python` looks for a Python errand runs on, `make_python` makes one; both set
# `$py`. What they do is said on stderr, prefixed `errand:`.
FUNCTIONS = r"""
base=""" + SH_BASE + r"""
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
    """The file a shipped errand is started from, relative to errand's per-user directory over there."""
    return f"{src_rel()}/errand/_boot.py"


def prepare( ssh, inner, there, echo = print ) -> str:
    """What must be over there before errand can start there: -> errand's per-user directory there."""
    from . import layers as L
    cache = ship( ssh.host, ssh.options )
    if not L.chooses_python( inner ) and L.batch_of( inner ) is not None:
        find( there, ssh.python, echo )
    return cache


def command( cmd, inner, cache: str, preferred: str = "python3", boot: str | None = None ):
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
        return L.Command( [ "python", boot or f"{cache}/{boot_rel()}", *rest ], cmd.env )
    where = shlex.quote( boot ) if boot else f'"$base"/{shlex.quote( boot_rel() )}'
    then = f'exec "$py" {where} "$@"\n'
    return L.Command( [ "sh", "-c", _script( then, preferred ), "sh", *rest ], cmd.env )


def package_tar( ) -> bytes:
    """errand's sources, gzipped: what `ship` sends. No caches, no `.sources`."""
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open( fileobj = buf, mode = "w:gz", compresslevel = 6 ) as t:
        names = [ ]
        for p, rel in _shipped():
            t.add( str( p ), arcname = rel.as_posix() )
            names.append( rel.as_posix() )
        # Last: what the copy must hold, for the side that unpacks it to check before saying it is whole.
        listing = ( "\n".join( names ) + "\n" ).encode()
        info = tarfile.TarInfo( MANIFEST )
        info.size = len( listing )
        t.addfile( info, io.BytesIO( listing ) )
    return buf.getvalue()


MANIFEST = ".manifest"


# The same, where there is no `sh` but always a Python ( a Windows guest, whose agent runs on one ): `$1`
# the copy, `$2` the sources key. Nothing is unpacked when the copy says it is these sources already.
UNPACK_PY = r"""
import os, shutil, sys, tarfile, uuid
d, key = sys.argv[ 1 ], sys.argv[ 2 ]

def whole( p ):
    try:
        with open( os.path.join( p, ".sources" ) ) as f:
            return f.read().strip() == key and os.path.isfile( os.path.join( p, "_boot.py" ) )
    except OSError:
        return False

if whole( d ):
    os.utime( os.path.join( d, ".sources" ) )     # in use: not one to prune
else:
    part, old = d + ".part." + uuid.uuid4().hex[ : 8 ], d + ".old." + uuid.uuid4().hex[ : 8 ]
    try:
        kw = { "filter": "data" } if hasattr( tarfile, "data_filter" ) else { }
        with tarfile.open( fileobj = sys.stdin.buffer, mode = "r|gz" ) as t:
            t.extractall( part, **kw )
        try:
            with open( os.path.join( part, ".manifest" ) ) as f:
                names = [ n for n in f.read().split( "\n" ) if n ]
        except OSError:
            sys.exit( "errand: the sources arrived cut short" )
        missing = [ n for n in names if not os.path.isfile( os.path.join( part, n ) ) ]
        if missing:
            sys.exit( "errand: the sources arrived without " + missing[ 0 ] )
        with open( os.path.join( part, ".sources" ), "w" ) as f:
            f.write( key + "\n" )
        if not whole( d ):                     # else another shipping of the same sources finished first
            if os.path.exists( d ):
                os.rename( d, old )
            os.rename( part, d )
            shutil.rmtree( old, ignore_errors = True )
    finally:
        shutil.rmtree( part, ignore_errors = True )
"""


def unpack_py_line( python: str, dest: str, key: str ) -> str:
    """One command line, for cmd.exe as for `sh`: `UNPACK_PY` by `python`, the tar on its stdin. The script
    crosses in base64, which neither shell reads anything into."""
    import base64
    code = base64.b64encode( UNPACK_PY.encode() ).decode()
    return f'{python} -c "import base64;exec(base64.b64decode(\'{code}\'))" "{dest}" {key}'


# Over there, from stdin: unpacked beside the copy, in a directory of this shipping's own, then put in
# its place. Python when there is one ( any errand runs on ), `tar` otherwise. `$1` the copy, `$2` the
# sources key.
#
# A copy is said to be whole ( `.sources` ) only once every file the tar lists ( `.manifest`, its last
# member ) is there: a stream cut short -- a network drop -- fails before, and so does a part another
# shipping started at the same moment, which has a directory of its own and never touches this one.
# Two shippings of the same sources: the first to finish wins, the other leaves.
UNPACK = r"""
d="$1"; set -e
part="$d.part.$$"; old="$d.old.$$"
trap 'rm -rf "$part"' EXIT
rm -rf "$part"; mkdir -p "$part"
if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import os, sys, tarfile
kw = { "filter": "data" } if hasattr( tarfile, "data_filter" ) else { }
with tarfile.open( fileobj = sys.stdin.buffer, mode = "r|gz" ) as t:
    t.extractall( sys.argv[ 1 ], **kw )' "$part"
else
    tar xzf - -C "$part"
fi
[ -f "$part/.manifest" ] || { echo "errand: the sources arrived cut short" >&2; exit 1; }
while IFS= read -r f; do
    [ -f "$part/$f" ] || { echo "errand: the sources arrived without $f" >&2; exit 1; }
done < "$part/.manifest"
echo "$2" > "$part/.sources"
if [ -f "$d/_boot.py" ] && [ "$(cat "$d/.sources" 2>/dev/null)" = "$2" ]; then
    exit 0                                   # another shipping of the same sources finished first
fi
[ -e "$d" ] && mv "$d" "$old"
mv "$part" "$d"
rm -rf "$old"
"""
