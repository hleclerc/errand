"""`--help`, and what is suggested when a target matched nothing.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from .. import config, discovery
from .style import dim
from .parsing import COMMON, VERBS


def print_help( parser, verb = None ):
    def options( dests ):
        for action in parser._actions:
            if action.dest in dests and action.help != argparse.SUPPRESS:
                flags = ", ".join( action.option_strings )
                if action.nargs != 0:
                    flags += f" {action.metavar or action.dest.upper()}"
                print( f"  {flags:28s} {action.help}" )

    if verb is None:
        print( "usage: errand [options] <verb> [arguments]\n" )
        print( "Run your work in any environment -- built and kept current from what it declares,\n"
               "here, in a container, on another machine -- with your files synced there and back.\n" )
        print( "verbs:" )
        for name, ( what, _ ) in VERBS.items():
            print( f"  {name:8s} {what}" )
        print( "\noptions, before or after the verb:" )
        options( COMMON )
        tags = [ a for a in parser._actions if a.dest.startswith( "tag_" ) ]
        if tags:
            print( f"  {' '.join( a.option_strings[ 0 ] for a in tags )}   environments by tag value" )
        print( dim( "\n  errand <verb> --help   what that verb takes" ) )
        return

    what, own = VERBS[ verb ]
    usage = { "run"   : "errand run [options] [target [what the target takes…]]",
              "list"  : "errand list [options] [target [what the target takes…]]",
              "shell" : "errand shell [--env NAME]",
              "setup" : "errand setup [--env NAME] [--force] [--dry-run]",
              "forget": "errand forget ID",
              "vm"    : "errand vm stop" }.get( verb, f"errand {verb}" )
    print( f"usage: {usage}\n\n{what}" )
    if own:
        print( "\noptions:" )
        options( own )
    print( "\noptions everybody takes:" )
    options( COMMON )
    if verb == "run":
        print( dim( "\n  x.py and x run as they are ( a .py by the place's python ); x::y goes to the entry runners" ) )
        runners = ", ".join( config.runners ) if config.runners else ""
        if runners:
            print( dim( f"  runners: {runners}" ) )


def _short( path: Path, root: Path ):
    try:
        return path.relative_to( root )
    except ValueError:
        return path


def _suggest( root ):
    files = discovery.candidates( root )
    if files:
        print( dim( "\n  files that declare work:" ) )
        for p in files:
            print( dim( f"    {os.path.relpath( p )}" ) )
