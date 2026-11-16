"""Tools named per environment, and `-j` handed to the tool of a single run ( ADR 0011 )."""
import sys
import tempfile
from pathlib import Path

import errand
from errand import test, runner as P

from _infra import run_errand, write_project


def ctx( **tools ):
    return P.RunContext( root = Path( "." ), out_dir = Path( "." ), tools = tools )


if test( "a tool is the environment's name for it, else the place's own" ):
    r = P.Python()
    assert r.tool( "python", ctx() ) == [ sys.executable ], "the interpreter errand runs on there"
    assert r.tool( "python", ctx( python = "python3.12 -X dev" ) ) == [ "python3.12", "-X", "dev" ]
    assert r.tool( "cargo", ctx( cargo = [ "/opt/rust/bin/cargo" ] ) ) == [ "/opt/rust/bin/cargo" ]
    assert r.tool( "nothing-here-xyz", ctx() ) == [ "nothing-here-xyz" ], "the name itself, for the error"
    assert r.command( "a.py", ctx( python = "py3" ) ) == [ "py3", "a.py" ]


if test( "a first word the environment names is run as it names it" ):
    r = P.Executable()
    assert r.command( "python3", ctx( python = "mypy-python" ) ) == [ "mypy-python" ]
    assert r.command( "cmake", ctx( cmake = "/opt/cmake/bin/cmake" ) ) == [ "/opt/cmake/bin/cmake" ]
    assert r.command( "make", ctx() ) == [ "make" ]


if test( "a build line writes {tool} for what the environment names, and nothing else changes" ):
    runner = P.Catch2( build = [ "{cmake} -S . -B {build_dir}", "sh -c 'echo ${CC} {a,b}'" ] )
    c = P.RunContext( root = Path( "." ), out_dir = Path( "." ), build_dir = Path( "b" ),
                      tools = { "cmake": "cmake3" } )
    assert runner.build_lines( [ ], c ) == [ "cmake3 -S . -B b", "sh -c 'echo ${CC} {a,b}'" ]


if test( "an environment's tools are commands" ):
    assert errand.Env( [ ], tools = { "python": "python3" } ).tools == { "python": "python3" }
    try:
        errand.Env( [ ], tools = { "python": 3 } )
        raise AssertionError( "a number was taken for a command" )
    except ValueError as err:
        assert "tools[ 'python' ]" in str( err ), err


PROJECT = '''
import errand
from errand import runner as P

class Jobs( P.Runner ):
    """Says how many workers it was handed."""
    name, level, takes_selector, jobs = "jobs", P.FRAMEWORK, True, True

    def suitability( self, path ):
        return P.FRAMEWORK if path.suffix == ".job" else P.NONE

    def run( self, entry, ctx ):
        return P.Outcome( status = "PASS", output = f"workers={ctx.jobs}\\n" )

class Alone( Jobs ):
    name, jobs = "alone", False

    def suitability( self, path ):
        return P.FRAMEWORK if path.suffix == ".one" else P.NONE

errand.runners[ "jobs" ] = Jobs( )
errand.runners[ "alone" ] = Alone( )
'''


if test( "-j N on a single run is its tool's parallelism, when its runner says how" ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", PROJECT,
                                 { "a.job": "", "b.job": "", "c.one": "" } )
        code, output = run_errand( project, "run", "--no-queue", "-j", "3", "a.job::*" )
        assert code == 0 and "workers=3" in output, output
        # several runs: they are what runs at the same time, each on one worker
        code, output = run_errand( project, "run", "--no-queue", "-j", "3", "*.job::*" )
        assert code == 0 and "workers=1" in output and "workers=3" not in output, output
        # a runner that takes none: said, not passed on
        code, output = run_errand( project, "run", "--no-queue", "-j", "3", "c.one::*" )
        assert code == 0 and "takes no parallelism of its own" in output and "workers=1" in output, output


if test( "cargo takes `-j` as --test-threads, after `--`, with the filter" ):
    import json

    class Seen( P.Cargo ):
        def shell( self, argv, ctx, **kw ):
            self.argv = [ str( a ) for a in argv ]
            class Done:
                returncode, stdout, stderr = 0, "test result: ok. 1 passed; 0 failed; 0 ignored", ""
            return Done()

    with tempfile.TemporaryDirectory() as tmp:
        r = Seen( target_dir = None )
        e = r.entry( name = "demo", file = Path( "src/lib.rs" ),
                     key = json.dumps( { "name": "demo", "kind": "lib", "manifest": "Cargo.toml" } ) )
        c = P.RunContext( root = Path( tmp ), out_dir = Path( tmp ), selector = "adds", jobs = 4,
                          tools = { "cargo": "cargo +nightly" } )
        assert r.run( e, c ).status == "PASS"
        assert r.argv == [ "cargo", "+nightly", "test", "--manifest-path", "Cargo.toml", "--lib",
                           "--", "adds", "--test-threads", "4" ], r.argv
