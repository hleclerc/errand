"""A little project, for the tests that need one.

Here rather than in one of the test files because **a file that declares work
must not be imported by another one**: importing it registers its entries a
second time, under a plain module name, and the runner then has two of
everything and cannot reload one of them. This file declares none, so both
suites can share it.
"""
from pathlib import Path

from _infra import write_project

CONFIG = '''
import errand

errand.envs[ "plain" ] = errand.Env( [ errand.Vars( { "DEMO": "1" } ) ], fp = "32|64" )
errand.envs[ "other" ] = errand.Env( [ errand.Vars( { "DEMO": "2" } ) ], fp = "64" )
'''

WORK = '''
from errand import test, bench, Param

if test( "quick" ):
    print( "hello from quick" )

if p := bench( "slow", n = Param( 1 ),
               method = Param( "cg", choices = [ "cg", "direct" ] ) ):
    print( f"{p.n} turns of {p.method}" )
    p.results[ "seconds" ] = 0.1 * p.n
'''


def a_project( tmp, files = None ):
    return write_project( Path( tmp ) / "proj", CONFIG, files or { "test_demo.py": WORK } )
