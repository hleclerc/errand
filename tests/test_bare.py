"""errand runs on the Python it finds, with next to nothing installed -- so its own tree has to be readable that way.

Reading is importing, and a test file that imports numpy, pytest or yaml at its top is a file that
costs its own row on a machine without them ( see `discovery.broken` ). Everything the suite needs
beyond the standard library is reached from INSIDE an entry, where a missing module is a skip and
not an unreadable file.
"""
import subprocess
import sys
from pathlib import Path

from errand import test

ROOT = Path( __file__ ).resolve().parent.parent

READ = """
import sys
from pathlib import Path
sys.path.insert( 0, {root!r} )
from errand import config, discovery
root = Path( {root!r} )
config.load( root )
entries, _, _ = discovery.select( None, root, exclude = config.settings.exclude, providers = config.providers )
for path, why, _ in discovery.broken:
    print( "BROKEN", path.relative_to( root ), why )
print( "READ", len( entries ) )
"""


if test( "every file of this project is readable by a bare interpreter" ):
    # -S: no site-packages, which is what a machine with almost nothing on it looks like.
    done = subprocess.run( [ sys.executable, "-S", "-c", READ.format( root = str( ROOT ) ) ],
                           capture_output = True, text = True, timeout = 300 )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "BROKEN" not in done.stdout, done.stdout
    assert "READ" in done.stdout, done.stdout + done.stderr


if test( "no file of this project imports a third-party module at its top" ):
    import ast
    stdlib = set( sys.stdlib_module_names ) | { "errand", "_demo", "_infra", "_tty" }
    own = { p.stem for p in ROOT.rglob( "*.py" ) } | { p.name for p in ROOT.rglob( "*" ) if p.is_dir() }
    found = [ ]
    # What a provider runs with its own runner is not read by errand: the pytest suite of example 03
    # imports pytest, as any pytest suite does.
    foreign = ROOT / "examples" / "03-existing-suite" / "tests"
    for path in sorted( ROOT.rglob( "*.py" ) ):
        if foreign in path.parents:
            continue
        if any( part in ( ".git", "node_modules", "__pycache__", "build", "dist", "runs", "_lib" )
                or part.startswith( ".venv" ) for part in path.parts ):
            continue
        for node in ast.parse( path.read_text() ).body:          # top level only
            names = ( [ a.name for a in node.names ] if isinstance( node, ast.Import )
                      else [ node.module or "" ] if isinstance( node, ast.ImportFrom ) and not node.level
                      else [ ] )
            for name in names:
                top = name.split( "." )[ 0 ]
                if top and top not in stdlib and top not in own:
                    found.append( f"{path.relative_to( ROOT )}: {name}" )
    assert not found, "third-party imports at the top of a file:\n  " + "\n  ".join( found )
