"""A little project to point a session at, and the care that goes with it.

Here rather than in one of the test files because **a file that declares work
must not be imported by another one**: importing it registers its entries a
second time, under a plain module name, and the runner then has two of
everything and cannot reload one of them. This file declares none, so both
suites can share it.
"""
from pathlib import Path

from errand import config

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

if p := bench( "slow", exclusive = False, n = Param( 1 ),
               method = Param( "cg", choices = [ "cg", "direct" ] ) ):
    print( f"{p.n} turns of {p.method}" )
    p.results[ "seconds" ] = 0.1 * p.n
'''

# It imports something that is not there. An example nobody set up, half a
# project installed: an ordinary state of affairs, and the reason for all this.
UNREADABLE = '''
from errand import test
import a_module_that_is_not_installed
'''


def a_project( tmp, files = None ):
    return write_project( Path( tmp ) / "proj", CONFIG, files or { "test_demo.py": WORK } )


def a_session( project ):
    """A session on a project, without the config of the suite running this one.

    `discover` loads a project's config into module-level state, which is the
    state THIS suite is running under; `put_back` restores it.
    """
    from errand import session as S
    kept = ( config.settings, dict( config.envs ), list( config.providers ) )
    return S.Session( project, project / "runs" ).discover(), kept


def put_back( kept ):
    config.settings = kept[ 0 ]
    config.envs.clear(); config.envs.update( kept[ 1 ] )
    config.providers[ : ] = kept[ 2 ]


def named( session, name ):
    return next( e for e in session.entries if e.name == name )
