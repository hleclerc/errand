"""Several entries at once: one process each.

The isolation between entries IS the module reload, and a reload only isolates
within one interpreter -- so running two at a time means two interpreters. A
serial run stays in this process, where it is faster and its output arrives
live; `-j` is what asks for the other shape.
"""
import os
import re
import tempfile
import time
from pathlib import Path

from errand import test
from errand import yamlish
from errand.cli import job_count

from _infra import run_errand, write_project


CHATTY = '''
import time
from errand import test

if test( "first" ):
    for i in range( 3 ):
        print( f"first {i}" )
        time.sleep( 0.2 )

if test( "second" ):
    for i in range( 3 ):
        print( f"second {i}" )
        time.sleep( 0.2 )
'''

MIXED = '''
from errand import test, skip

if test( "passes" ):
    assert True

if test( "fails" ):
    assert 1 == 2, "one is not two"

if test( "skips" ):
    skip( "nothing to do today" )
'''

PARAMETRIZED = '''
from errand import bench, Param

if p := bench( "measured", exclusive = False, n = Param( 1 ), label = Param( "plain" ) ):
    p.results[ "n" ] = p.n
    p.results[ "label" ] = p.label
'''


if test( "-j reads the way a person writes it" ):
    assert job_count( None ) == 1 and job_count( "1" ) == 1
    assert job_count( "4" ) == 4
    assert job_count( "auto" ) == max( 1, os.cpu_count() or 1 )
    try:
        job_count( "many" )
    except ValueError as err:
        assert "auto" in str( err )
    else:
        assert False, "a typo must not silently mean one"


if test( "the same results, whichever shape it ran in", tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "bench_p.py": PARAMETRIZED } )

        code, _ = run_errand( project, "-k", "bench", "--n=1,2,3" )
        assert code == 0
        serial = { str( p.relative_to( project ) ): yamlish.read( p )[ "results" ]
                   for p in sorted( ( project / "runs" ).rglob( "result.yaml" ) ) }

        code, _ = run_errand( project, "-k", "bench", "--n=1,2,3", "-j", "3" )
        assert code == 0
        parallel = { str( p.relative_to( project ) ): yamlish.read( p )[ "results" ]
                     for p in sorted( ( project / "runs" ).rglob( "result.yaml" ) ) }

        assert serial == parallel, ( serial, parallel )
        assert len( serial ) == 3


if test( "an entry's output arrives whole, not interleaved", tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "test_chatty.py": CHATTY } )
        code, output = run_errand( project, "-j", "2" )
        assert code == 0, output

        # Both entries print three lines each, slowly, at the same time. If the
        # parent wrote them as they came, they would be shuffled -- and worse,
        # unattributable, since neither line says whose it is.
        lines = [ l for l in output.splitlines() if re.match( r"^(first|second) \d$", l ) ]
        assert lines == [ "first 0", "first 1", "first 2",
                          "second 0", "second 1", "second 2" ] or \
               lines == [ "second 0", "second 1", "second 2",
                          "first 0", "first 1", "first 2" ], lines


if test( "what happened in a child is what the parent reports", tags = [ "slow" ] ):
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "test_mixed.py": MIXED } )
        code, output = run_errand( project, "-j", "3" )

        assert code == 1, output                      # a failure anywhere is a failure
        assert "FAILED fails" in output, output
        assert "1 skipped" in output and "nothing to do today" in output, output
        # ...and the reason survived the trip, rather than becoming "exit 1"
        assert "one is not two" in output, output


if test( "a value with a space survives the trip to the child", tags = [ "slow" ] ):
    # Parameters are handed over through the environment rather than as flags:
    # a comma on a command line means a matrix, and quoting is a second way to
    # be wrong.
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "bench_p.py": PARAMETRIZED } )
        code, output = run_errand( project, "-k", "bench", "--label", "two words", "-j", "2" )
        assert code == 0, output
        got = [ yamlish.read( p )[ "results" ]
                for p in ( project / "runs" ).rglob( "result.yaml" ) ]
        assert got and all( g[ "label" ] == "two words" for g in got ), got


if test( "exclusive still means exclusive when several are running", tags = [ "slow" ] ):
    # The queue is what enforces it, and it works between processes, which is
    # exactly what -j creates.
    WORK = '''
import time
from errand import bench

if p := bench( "alone one" ):
    time.sleep( 1.5 )
    p.results[ "at" ] = time.time()

if p := bench( "alone two" ):
    time.sleep( 1.5 )
    p.results[ "at" ] = time.time()
'''
    with tempfile.TemporaryDirectory() as tmp:
        project = write_project( Path( tmp ) / "proj", "", { "bench_alone.py": WORK } )
        started = time.perf_counter()
        code, output = run_errand( project, "-k", "bench", "-j", "2" )
        elapsed = time.perf_counter() - started
        assert code == 0, output
        assert elapsed > 2.5, f"two exclusive benchmarks overlapped ({elapsed:.1f}s)\n{output}"
