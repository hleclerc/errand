"""A run asks for what it needs ( ADR 0014 ): the environment, the command line, `errand.require`."""
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from errand import test
from errand import queue as Q, yamlish

from _infra import run_errand, write_project


@contextlib.contextmanager
def private_queue( capacity = None ):
    """A queue of our own, looking like a top-level run, on a machine of `capacity` when given."""
    names = ( "XDG_RUNTIME_DIR", Q.CLAIM, Q.CLAIM_FILE, "ERRAND_NO_QUEUE", "CUDA_VISIBLE_DEVICES",
              "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES", *Q.ALLOCATION_VARS, Q.ALLOCATION )
    before = { k: os.environ.get( k ) for k in names }
    with tempfile.TemporaryDirectory() as tmp:
        for k in names:
            os.environ.pop( k, None )
        os.environ[ "XDG_RUNTIME_DIR" ] = tmp
        Q._capacity = dict( capacity ) if capacity else None
        try:
            yield Path( tmp )
        finally:
            Q._capacity = None
            for k, old in before.items():
                if old is None:
                    os.environ.pop( k, None )
                else:
                    os.environ[ k ] = old


CARDS = { "cpus": 8.0, "ram": 16000.0, "gpus": 2.0, "card_ram": [ 16000.0, 16000.0 ] }


def waiting_for( needs, others, exclusive = False ):
    return Q._fits( Q.normalize( needs ), exclusive, others )[ 0 ]


def given( needs, others ):
    return Q._fits( Q.normalize( needs ), False, others )[ 1 ]


# ── a card's memory ──────────────────────────────────────────────────────────

if test( "gpu_ram is a size or a share, and memory on a card is a card" ):
    assert Q.normalize( { "gpu_ram": "40G" } ) == { "gpu_ram": 40960.0, "gpus": 1.0 }
    assert Q.normalize( { "gpu_ram": "75%", "gpus": 2 } ) == { "gpu_ram": "75%", "gpus": 2.0 }
    assert Q.normalize( { "gpus": 1, "exclusive": True } ) == { "gpus": 1.0 }
    try:
        Q.normalize( { "gpu_ram": "150%" } )
        raise AssertionError( "a share over 100 % must not read" )
    except ValueError:
        pass


if test( "a card's memory is counted per card: 30 % and 30 % share one, 75 % and 75 % do not" ):
    with private_queue( { **CARDS, "gpus": 1.0, "card_ram": [ 16000.0 ] } ):
        thirty = { "devices": [ 0 ], "card_ram": [ 4800.0 ] }
        assert waiting_for( { "gpus": 1, "gpu_ram": "30%" }, [ thirty ] ) is None
        assert waiting_for( { "gpus": 1, "gpu_ram": "75%" }, [ { "devices": [ 0 ], "card_ram": [ 12000.0 ] } ] ) is not None
        # without gpu_ram, a card is taken whole: not one somebody has a share of
        assert waiting_for( { "gpus": 1 }, [ thirty ] ) is not None
        # and a share does not fit on a card held whole
        assert waiting_for( { "gpu_ram": "10%" }, [ { "devices": [ 0 ] } ] ) is not None


if test( "cards are given by what they have left" ):
    with private_queue( CARDS ):
        # card 0 holds 30 %, card 1 nothing: the next share goes to card 1
        assert given( { "gpu_ram": "30%" }, [ { "devices": [ 0 ], "card_ram": [ 4800.0 ] } ] ) == [ 1 ]
        assert given( { "gpu_ram": "30%" }, [ { "devices": [ 1 ], "card_ram": [ 9000.0 ] },
                                              { "devices": [ 0 ], "card_ram": [ 4800.0 ] } ] ) == [ 0 ]


if test( "a card asked on a machine with none: nothing to wait for" ):
    with private_queue( { "cpus": 8.0, "ram": 16000.0, "gpus": 0.0 } ):
        assert Q._fits( Q.normalize( { "gpus": 1, "gpu_ram": "75%" } ), False, [ { "cpus": 1 } ] ) == ( None, [ ] )


if test( "a card whose size is unknown is taken whole" ):
    with private_queue( { **CARDS, "card_ram": [ ] } ):
        assert given( { "gpu_ram": "30%" }, [ ] ) == [ 0 ]
        assert given( { "gpu_ram": "30%" }, [ { "devices": [ 0 ] } ] ) == [ 1 ]
        assert waiting_for( { "gpu_ram": "30%" }, [ { "devices": [ 0 ] }, { "devices": [ 1 ] } ] ) is not None


if test( "a claim says what it takes on each card" ):
    with private_queue( CARDS ):
        with Q.claim( { "gpus": 1, "gpu_ram": "25%" }, label = "a" ) as a, \
             Q.claim( { "gpus": 1, "gpu_ram": "25%" }, label = "b" ) as b:
            assert a.devices != b.devices, "two shares go to two cards while both are free"
            assert yamlish.read( a.path )[ "card_ram" ] == [ 4000.0 ]
            assert any( "gpu_ram=25%" in line for line in Q.describe() ), Q.describe()


# ── a claim that grows ───────────────────────────────────────────────────────

if test( "require grows the claim, keeps its cards, and says what it asked" ):
    with private_queue( CARDS ):
        with Q.claim( { "cpus": 1 }, label = "run" ) as granted:
            assert Q.grow( granted.path, { "gpus": 1, "gpu_ram": "50%" } ) == [ 0 ]
            row = yamlish.read( granted.path )
            assert row[ "gpus" ] == 1 and row[ "gpu_ram" ] == "50%" and row[ "card_ram" ] == [ 8000.0 ], row
            assert row[ "cpus" ] == 1, "what it held is still held"
            assert row[ "required" ] == { "gpus": 1.0, "gpu_ram": "50%" }, row
            # asking for no more than it holds returns at once, with the same card
            t = time.monotonic()
            assert Q.grow( granted.path, { "gpu_ram": "30%" } ) == [ 0 ]
            assert time.monotonic() - t < 1
            assert yamlish.read( granted.path )[ "gpu_ram" ] == "50%"


if test( "a share and a size are compared on the card: a claim never shrinks" ):
    big = 11264.0
    assert Q.merged( { "gpus": 1, "gpu_ram": "75%" }, { "gpu_ram": 4096.0 }, big )[ "gpu_ram" ] == "75%"
    assert Q.merged( { "gpus": 1, "gpu_ram": "75%" }, { "gpu_ram": 10240.0 }, big )[ "gpu_ram" ] == 10240.0
    assert Q.merged( { "gpus": 1, "gpu_ram": 4096.0 }, { "gpu_ram": "50%" }, big )[ "gpu_ram" ] == "50%"
    # no size to read the share with: what is held stays
    assert Q.merged( { "gpus": 1, "gpu_ram": "75%" }, { "gpu_ram": 10240.0 } )[ "gpu_ram" ] == "75%"


if test( "extra adds: quantities, shares on each card, a share and a size on the card" ):
    assert Q.added( { "cpus": 2, "ram": 1024 }, { "cpus": 1, "ram": 512 } ) == { "cpus": 3.0, "ram": 1536.0 }
    assert Q.added( { "gpus": 1, "gpu_ram": "30%" }, { "gpu_ram": "20%" } ) == { "gpus": 1.0, "gpu_ram": "50%" }
    assert Q.added( { "gpus": 1, "gpu_ram": "80%" }, { "gpu_ram": "40%" } )[ "gpu_ram" ] == "100%"
    assert Q.added( { "gpus": 1, "gpu_ram": "50%" }, { "gpu_ram": 1024.0 }, 10240.0 )[ "gpu_ram" ] == 6144.0
    # cards held whole stay whole
    assert Q.added( { "gpus": 1 }, { "gpu_ram": "20%" } ) == { "gpus": 1.0 }


if test( "require( extra = True ) adds to what the run was started with, and the calls add up" ):
    with private_queue( CARDS ):
        with Q.claim( { "ram": "4G", "gpus": 1, "gpu_ram": "30%" }, label = "run" ) as granted:
            Q.grow( granted.path, { "ram": "2G" }, extra = True )
            assert yamlish.read( granted.path )[ "ram" ] == 6144
            Q.grow( granted.path, { "ram": "1G" }, extra = True )
            assert yamlish.read( granted.path )[ "ram" ] == 7168
            # at least 5G in all: already held
            Q.grow( granted.path, { "ram": "5G" } )
            assert yamlish.read( granted.path )[ "ram" ] == 7168
            # more memory on the card it holds, not one more card
            assert Q.grow( granted.path, { "gpu_ram": "20%" }, extra = True ) == [ 0 ]
            row = yamlish.read( granted.path )
            assert row[ "gpus" ] == 1 and row[ "gpu_ram" ] == "50%", row
            assert row[ "wanted" ] == { "ram": 7168.0, "gpus": 1.0, "gpu_ram": "50%" }, row


if test( "claimed up front from what was remembered, an extra call is not added twice" ):
    with private_queue( CARDS ):
        # the total the code came to last time, claimed up front; the run is told 4G
        with Q.claim( { "ram": "7G" }, base = { "ram": "4G" }, label = "run" ) as granted:
            t = time.monotonic()
            Q.grow( granted.path, { "ram": "3G" }, extra = True )
            assert time.monotonic() - t < 1
            row = yamlish.read( granted.path )
            assert row[ "ram" ] == 7168 and row[ "wanted" ] == { "ram": 7168.0 }, row


if test( "a growing claim waits for room, and what arrives after waits behind it" ):
    with private_queue( { **CARDS, "cpus": 4.0 } ):
        order = [ ]
        with Q.claim( { "cpus": 2 }, label = "other" ) as other:
            with Q.claim( { "cpus": 2 }, label = "run" ) as run:
                grower = threading.Thread( target = lambda: ( Q.grow( run.path, { "cpus": 4 } ), order.append( "grown" ) ) )
                grower.start()
                while not any( w.get( "grows" ) for w in Q.waiting_exclusive() ):
                    time.sleep( 0.05 )

                def late( ):
                    with Q.claim( { "cpus": 1 }, label = "late" ):
                        order.append( "late" )

                newcomer = threading.Thread( target = late )
                newcomer.start()
                time.sleep( 0.5 )
                assert order == [ ], order
                Q.release( other.path )         # the room it waits for
                grower.join( 10 )
                assert order == [ "grown" ], "the growing claim goes first"
                assert yamlish.read( run.path )[ "cpus" ] == 4
            newcomer.join( 10 )
        assert order == [ "grown", "late" ], order


if test( "two claims that grow and wait for each other: the younger is stopped, to run again" ):
    from errand import Rerun
    with private_queue( CARDS ):
        with Q.claim( { "gpus": 1 }, label = "older" ) as older:
            time.sleep( 0.01 )
            with Q.claim( { "gpus": 1 }, label = "younger" ) as younger:
                got = { }

                def grow( name, granted ):
                    try:
                        got[ name ] = Q.grow( granted.path, { "gpus": 2 } )
                    except Rerun as r:
                        got[ name ] = r
                        Q.release( granted.path )       # what errand does once the run has stopped

                a = threading.Thread( target = grow, args = ( "older", older ) )
                b = threading.Thread( target = grow, args = ( "younger", younger ) )
                a.start(); time.sleep( 0.3 ); b.start()
                a.join( 15 ); b.join( 15 )
                assert isinstance( got.get( "younger" ), Rerun ), got
                assert sorted( got.get( "older" ) ) == [ 0, 1 ], got


if test( "three claims that grow to the whole machine: the younger two make way, the oldest goes" ):
    from errand import Rerun
    with private_queue( { "cpus": 8.0, "ram": 16000.0, "gpus": 0.0 } ):
        claims = [ ]
        with contextlib.ExitStack() as stack:
            for name in ( "a", "b", "c" ):
                claims.append( stack.enter_context( Q.claim( { "cpus": 1 }, label = name ) ) )
                time.sleep( 0.01 )
            got = { }

            def grow( name, granted ):
                try:
                    got[ name ] = Q.grow( granted.path, { }, exclusive = True )
                except Rerun as r:
                    got[ name ] = r
                    Q.release( granted.path )

            threads = [ threading.Thread( target = grow, args = ( n, c ) ) for n, c in zip( "abc", claims ) ]
            for t in threads:
                t.start()
                time.sleep( 0.2 )
            for t in threads:
                t.join( 15 )
            assert got.get( "a" ) == [ ], got
            assert isinstance( got.get( "b" ), Rerun ) and isinstance( got.get( "c" ), Rerun ), got


# ── errand.require ───────────────────────────────────────────────────────────

if test( "outside errand, require does nothing and returns at once" ):
    import errand
    with private_queue():
        before = dict( os.environ )
        assert errand.require( gpus = 1, gpu_ram = "75%" ) == [ ]
        assert dict( os.environ ) == before


if test( "in a run, require sets the cards in its own process" ):
    import errand
    with private_queue( CARDS ):
        with Q.claim( { }, label = "run" ) as granted:
            os.environ.update( granted.handed_down() )
            assert os.environ[ Q.CLAIM_FILE ] == str( granted.path )
            assert errand.require( gpus = 1 ) == [ 0 ]
            assert os.environ[ "CUDA_VISIBLE_DEVICES" ] == "0" and os.environ[ "ROCR_VISIBLE_DEVICES" ] == "0"


if test( "`errand require` prints what to set, and nothing outside errand" ):
    with private_queue( CARDS ) as tmp:
        env = { **os.environ, "PYTHONPATH": os.pathsep.join( sys.path ) }
        r = subprocess.run( [ sys.executable, "-m", "errand", "require", "--gpus", "1" ], capture_output = True,
                            text = True, cwd = tmp, env = env )
        assert r.returncode == 0 and r.stdout == "", r.stdout + r.stderr
        with Q.claim( { "cpus": 1 }, label = "run" ) as granted:
            # the queue over there reads its own machine: a claim for cpus only is all this can check
            r = subprocess.run( [ sys.executable, "-m", "errand", "require", "--cpus", "1" ], capture_output = True,
                                text = True, cwd = tmp, env = { **env, Q.CLAIM_FILE: str( granted.path ) } )
            assert r.returncode == 0, r.stdout + r.stderr
            assert yamlish.read( granted.path )[ "required" ] == { "cpus": 1.0 }


if test( "the shell's require sets what errand require prints" ):
    from errand import steps
    fake = Path( tempfile.mkdtemp() ) / "python"
    fake.write_text( "#!/bin/sh\necho CUDA_VISIBLE_DEVICES=3\necho ERRAND_CLAIM=3\n" )
    fake.chmod( 0o755 )
    out = subprocess.run( [ "sh", "-c", 'eval "$ERRAND_STEPS_SH"; require --gpus 1; echo "[$CUDA_VISIBLE_DEVICES]"' ],
                          capture_output = True, text = True,
                          env = { **os.environ, steps.SH_ENV: steps.SHELL_STEPS, Q.CLAIM_FILE: "/x",
                                  "ERRAND_PYTHON": str( fake ), "ERRAND_SRC": "/nowhere" } )
    assert out.stdout.strip() == "[3]", out.stdout + out.stderr
    # outside errand: nothing at all
    out = subprocess.run( [ "sh", "-c", 'eval "$ERRAND_STEPS_SH"; require --gpus 1; echo "[${CUDA_VISIBLE_DEVICES-unset}]"' ],
                          capture_output = True, text = True,
                          env = { k: v for k, v in { **os.environ, steps.SH_ENV: steps.SHELL_STEPS }.items()
                                  if k not in ( Q.CLAIM_FILE, "CUDA_VISIBLE_DEVICES" ) } )
    assert out.stdout.strip() == "[unset]", out.stdout + out.stderr


# ── the environment, the command line, what is remembered ────────────────────

if test( "Env( needs = … ): checked when declared, under the command line" ):
    from errand import config, needs as N
    try:
        config.Env( [ ], needs = { "gpu": 1 } )
        raise AssertionError( "an unknown need must not pass" )
    except ValueError:
        pass
    try:
        config.Env( [ ], needs = { "gpu_ram": "lots" } )
        raise AssertionError( "a size that does not read must not pass" )
    except ValueError:
        pass
    config.envs[ "_needs_test" ] = config.Env( [ ], needs = { "gpus": 1, "gpu_ram": "75%", "ram": "16G", "exclusive": True } )
    try:
        got, exclusive, _ = N.asked( "_needs_test", { }, { "ram": "20G" }, False )
        assert got == { "gpus": 1.0, "gpu_ram": "75%", "ram": 20480.0 } and exclusive, got
    finally:
        del config.envs[ "_needs_test" ]


if test( "what a run required is remembered by machine, environment and target, and forgotten when it stops" ):
    from errand import config, needs as N
    with tempfile.TemporaryDirectory() as root:
        N.remember( root, "gpu", "a.py::x", { "wanted": { "gpus": 1.0, "gpu_ram": "75%" } } )
        assert N.remembered( root, "gpu", "a.py::x" ) == { "gpus": 1.0, "gpu_ram": "75%" }
        assert N.remembered( root, "cpu", "a.py::x" ) == { }
        data = json.loads( ( config.state( Path( root ) ) / N.FILE ).read_text() )
        assert list( data ) == [ Q.host() ], data
        got, _, mem = N.asked( "gpu", { }, { "cpus": 2 }, False, root = root, target = "a.py::x" )
        assert got == { "cpus": 2.0 } and not mem, "off by default: nothing claimed from memory"
        config.settings.remember_needs = True
        try:
            got, _, mem = N.asked( "gpu", { }, { "cpus": 2 }, False, root = root, target = "a.py::x" )
        finally:
            config.settings.remember_needs = False
        assert got == { "cpus": 2.0, "gpus": 1.0, "gpu_ram": "75%" } and mem, got
        N.remember( root, "gpu", "a.py::x", { } )
        assert N.remembered( root, "gpu", "a.py::x" ) == { }


if test( "--cpus, --ram and -x reach the claim, and the claim's path reaches the run" ):
    SHOW = "import os; print( 'CLAIM', open( os.environ[ 'ERRAND_CLAIM_FILE' ] ).read().replace( chr( 10 ), ' ' ) )"
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "p", "", { } )
        rc, out = run_errand( project, "run", "--cpus", "1", "--ram", "1G", sys.executable, "-c", SHOW )
        assert rc == 0, out
        line = next( l for l in out.splitlines() if l.startswith( "CLAIM" ) )
        assert "cpus: 1" in line and "ram: 1024" in line and "exclusive: false" in line, line
        rc, out = run_errand( project, "run", "-x", sys.executable, "-c", SHOW )
        assert "exclusive: true" in next( l for l in out.splitlines() if l.startswith( "CLAIM" ) ), out


if test( "the environment's needs reach the claim, under the command line" ):
    SHOW = "import os; print( 'CLAIM', open( os.environ[ 'ERRAND_CLAIM_FILE' ] ).read().replace( chr( 10 ), ' ' ) )"
    config = 'import errand\nerrand.envs[ "here" ] = errand.Env( [ ], needs = { "cpus": 1, "ram": "2G" } )\nerrand.default_env = "here"\n'
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "p", config, { } )
        rc, out = run_errand( project, "run", "--ram", "1G", sys.executable, "-c", SHOW )
        assert rc == 0, out
        line = next( l for l in out.splitlines() if l.startswith( "CLAIM" ) )
        assert "cpus: 1" in line and "ram: 1024" in line, line


if test( "what a run required is not remembered unless the project says so", tags = [ "slow" ] ):
    WORK = 'import errand\n\nif p := errand.test( "needs" ):\n    errand.require( cpus = 1 )\n'
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "p", "", { "test_needs.py": WORK } )
        for _ in range( 2 ):
            rc, out = run_errand( project, "run", "test_needs.py::*" )
            assert rc == 0 and "claimed up front" not in out, out
        assert not ( project / "errand-outputs" / "state" / "needs.json" ).exists()
        result = next( ( project / "errand-outputs" ).rglob( "result.yaml" ) )
        assert "required" in result.read_text(), "the record says it all the same"


if test( "what a run required is claimed up front the next time", tags = [ "slow" ] ):
    WORK = 'import errand\n\nif p := errand.test( "needs" ):\n    errand.require( cpus = 1 )\n'
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "p", "import errand\nerrand.configure( remember_needs = True )\n",
                                 { "test_needs.py": WORK } )
        rc, out = run_errand( project, "run", "test_needs.py::*" )
        assert rc == 0, out
        assert "claimed up front" not in out, out
        state = json.loads( ( project / "errand-outputs" / "state" / "needs.json" ).read_text() )
        assert state[ Q.host() ][ "default" ][ "test_needs.py::needs" ] == { "cpus": 1.0 }, state
        result = next( ( project / "errand-outputs" ).rglob( "result.yaml" ) )
        assert "required" in result.read_text(), result.read_text()
        rc, out = run_errand( project, "run", "test_needs.py::*" )
        assert rc == 0 and "claimed up front, as it required last time: cpus=1" in out, out


if test( "two runs that grow into each other: the younger runs again, with its needs up front", tags = [ "slow" ] ):
    total = Q.capacity()[ "cpus" ]
    half = max( 1, int( total ) // 2 )
    WORK = ( 'import errand, time\n\nif p := errand.test( "{name}" ):\n    time.sleep( {wait} )\n'
             f'    errand.require( cpus = {int( total )} )\n    time.sleep( 0.5 )\n' )
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "p", "", {
            "test_a.py": WORK.format( name = "a", wait = 1.0 ), "test_b.py": WORK.format( name = "b", wait = 1.5 ) } )
        import errand
        env = { k: v for k, v in os.environ.items() if k not in ( Q.CLAIM, Q.CLAIM_FILE, "ERRAND_IN_ENV", "ERRAND_TAGS" ) }
        ( project / ".queue" ).mkdir()
        env.update( XDG_RUNTIME_DIR = str( project / ".queue" ),
                    PYTHONPATH = str( Path( errand.__file__ ).resolve().parent.parent ) )
        both = [ subprocess.Popen( [ sys.executable, "-m", "errand", "run", "--cpus", str( half ), f"test_{n}.py::*" ],
                                   cwd = project, env = env, stdout = subprocess.PIPE, stderr = subprocess.STDOUT, text = True )
                 for n in "ab" ]
        outs = [ p.communicate( timeout = 120 )[ 0 ] for p in both ]
        assert all( p.returncode == 0 for p in both ), outs
        # which of the two claimed first is up to the machine: exactly one is the younger
        again = [ o for o in outs if "run again" in o ]
        assert len( again ) == 1 and "stopped by errand.require" in again[ 0 ], outs


# ── C++: errand/require.hpp ──────────────────────────────────────────────────

REQUIRE_CPP = r"""
#include <errand/require.hpp>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>

int main() {
    errand::Needs needs;
    needs.cpus = 1;
    needs.ram  = "1G";
    try {
        auto got = errand::require( needs );
        std::cout << "CARDS " << got.size() << std::endl;
    } catch ( const errand::Rerun & ) {
        std::cout << "RERUN" << std::endl;
        return 75;
    }
    if ( const char *claim = std::getenv( "ERRAND_CLAIM_FILE" ) ) {
        std::ifstream f( claim );
        std::stringstream ss;
        ss << f.rdbuf();
        std::string text = ss.str();
        for ( char &c : text ) if ( c == '\n' ) c = ' ';
        std::cout << "CLAIM " << text << std::endl;
    }
}
"""


def compiler( ):
    import shutil
    from errand import skip
    for cxx in ( "c++", "g++", "clang++" ):
        if shutil.which( cxx ):
            return cxx
    skip( "no C++ compiler" )


def build_require( directory: Path ) -> Path:
    from errand.runner.base import INCLUDE
    source, binary = directory / "req.cpp", directory / "req"
    source.write_text( REQUIRE_CPP )
    got = subprocess.run( [ compiler(), "-std=c++17", "-Wall", "-I", str( INCLUDE ), str( source ), "-o", str( binary ) ],
                          capture_output = True, text = True )
    assert got.returncode == 0, got.stderr
    return binary


if test( "errand::require grows the claim of a C++ run, and does nothing outside errand", tags = [ "cpp" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "p", "", { } )
        binary = build_require( project )
        alone = subprocess.run( [ str( binary ) ], capture_output = True, text = True,
                                env = { k: v for k, v in os.environ.items() if k != Q.CLAIM_FILE } )
        assert alone.returncode == 0 and alone.stdout.strip() == "CARDS 0", alone.stdout + alone.stderr
        rc, out = run_errand( project, "run", str( binary ) )
        assert rc == 0, out
        line = next( l for l in out.splitlines() if l.startswith( "CLAIM" ) )
        assert "required: { ram: 1024.0, cpus: 1.0 }" in line or "required: { cpus: 1.0, ram: 1024.0 }" in line, line


if test( "errand::require throws Rerun when errand stops it to run again", tags = [ "cpp" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        binary = build_require( Path( tmp ) )
        fake = Path( tmp ) / "python"
        fake.write_text( "#!/bin/sh\nexit 75\n" )
        fake.chmod( 0o755 )
        got = subprocess.run( [ str( binary ) ], capture_output = True, text = True,
                              env = { **os.environ, Q.CLAIM_FILE: "/x", "ERRAND_PYTHON": str( fake ) } )
        assert got.returncode == 75 and "RERUN" in got.stdout, got.stdout + got.stderr


if test( "{errand_include} in a build line is where the header is" ):
    from errand.runner import Catch2
    from errand.runner.base import INCLUDE, RunContext
    assert ( INCLUDE / "errand" / "require.hpp" ).is_file()
    ctx = RunContext( root = Path( "/" ), out_dir = Path( "/" ), params = { }, env = { } )
    line = Catch2( build = "c++ -I{errand_include} x.cpp" ).build_lines( [ ], ctx )[ 0 ]
    assert line == f"c++ -I{INCLUDE} x.cpp", line


CATCH_REQUIRE = r"""
#include <catch2/catch_test_macros.hpp>
#include <errand/require.hpp>
#include <cstdlib>

TEST_CASE( "asks for a core" ) {
    errand::Needs needs;
    needs.cpus = 1;
    errand::require( needs );
    REQUIRE( std::getenv( "ERRAND_CLAIM_FILE" ) != nullptr );
}
"""


if test( "a Catch2 suite finds the header through {errand_include}", tags = [ "cpp", "slow" ] ):
    from errand import skip
    prefixes = [ p for p in ( os.environ.get( "CONDA_PREFIX" ), "/usr", "/usr/local", "/opt/homebrew" ) if p ]
    prefix = next( ( p for p in prefixes if Path( p, "include", "catch2", "catch_test_macros.hpp" ).exists() ), None )
    if prefix is None:
        skip( "catch2 headers are not installed" )
    with tempfile.TemporaryDirectory() as tmp:
        build = ( f"{compiler()} -std=c++17 -I{{errand_include}} -I{prefix}/include cpp/test_req.cpp "
                  f"-L{prefix}/lib -lCatch2Main -lCatch2 -o cpp/test_req" )
        config = ( "import errand\nerrand.configure( exclude = [ '_lib' ] )\n"
                   f"errand.runners.replace( errand.Catch2( dir = 'cpp', build = {build!r} ) )\n" )
        project = write_project( Path( tmp ) / "p", config, { "cpp/test_req.cpp": CATCH_REQUIRE } )
        rc, out = run_errand( project, "run", "**::*", timeout = 900 )
        assert rc == 0 and "PASS test_req.cpp" in out, out
        result = yamlish.read( next( ( project / "errand-outputs" / "runs" ).rglob( "result.yaml" ) ) )
        assert result.get( "required" ) == { "cpus": 1.0 }, result
