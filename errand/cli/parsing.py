"""The parser and the verbs; where errand's options end and the target, then the target's own
arguments, begin.
"""
from __future__ import annotations

import argparse
from pathlib import Path


KINDS = { "test": "test", "bench": "bench", "experiment": "experiment", "exp": "experiment" }


# ── entry point ──────────────────────────────────────────────────────────────

# What each verb does, in the order the help lists them, and which of the
# options are its own. The rest of the options -- choosing environments, where
# the project and its output are -- are everybody's, and may stand before the
# verb or after it.
VERBS = {
    "run"   : ( "run a file, a command or entries, in one or several environments",
                [ "runner", "kind", "entry_tags", "jobs", "no_queue", "no_setup", "batch", "keep_out",
                  "out", "pull", "exclusive", "cpus", "ram", "gpus", "ranks", "time", "mem", "label", "quiet", "log",
                  "at" ] ),
    "list"  : ( "what a target designates, with its parameters",
                [ "runner", "kind", "entry_tags", "no_setup" ] ),
    "shell" : ( "an interactive shell in an environment", [ "pull", "no_setup" ] ),
    "envs"  : ( "the declared environments, and the state they are in", [ ] ),
    "setup" : ( "build or update environments now, and nothing else", [ "force", "dry_run" ] ),
    "init"  : ( "write a starting errand-envs.py, and suggest runners for what is here", [ "force" ] ),
    "tui"   : ( "the screen: tick what to run, watch each case as it talks", [ ] ),
    "queue" : ( "what this machine has, and what is holding it", [ ] ),
    "wait"  : ( "wait until nothing holds the machine", [ ] ),
    "status": ( "how the launched ( --batch ) work is going", [ ] ),
    "watch" : ( "the same, live", [ ] ),
    "forget": ( "drop a submission from the list: errand forget ID, or every one that is over: errand forget finished", [ ] ),
    "attach": ( "follow again what a command left running ( a lost connection ), and bring it back", [ ] ),
    "vm"    : ( "the virtual machines kept warm between commands: errand vm stop", [ ] ),
    "agents": ( "what is kept between commands: errand agents [stop [NAME]]", [ "force" ] ),
}
COMMON = [ "env", "env_tags", "root", "help", "version", "verbose" ]


def build_parser( tag_names = ( ) ):
    # No abbreviations. Parameter flags are named by whoever wrote the entry,
    # so any of them may one day be a prefix of a built-in one -- `--n=2,3` was
    # read as `--no-setup=2,3`, which is not a mistake anybody would have
    # thought to look for. An exact match, or nothing.
    p = argparse.ArgumentParser( prog = "errand", add_help = False, allow_abbrev = False )
    p.add_argument( "pattern", nargs = "?", help = "what to run: a file, a command, or path::entry ( globs on both sides ), comma-separated" )

    # everybody's
    p.add_argument( "--env", default = None, help = "environment(s) by name, comma-separated" )
    p.add_argument( "-t", "--env-tags", default = None, help = "choose environments by tag expression" )
    p.add_argument( "--root", default = None, help = "project root (default: found from the cwd)" )
    p.add_argument( "-h", "--help", action = "store_true", help = "this help; after a verb, that verb's" )
    p.add_argument( "-V", "--version", action = "store_true", help = "which errand this is" )
    p.add_argument( "-v", "--verbose", action = "store_true",
                    help = "say every command errand starts, here and over there ( on stderr )" )

    # run, list
    p.add_argument( "-r", "--runner", default = None,
                    help = "the runner that takes every target, by name ( errand.runners )" )
    p.add_argument( "-k", "--kind", action = "append", default = [ ],
                    help = "test, bench, experiment (repeatable)" )
    p.add_argument( "-e", "--entry-tags", default = None, help = "filter entries by tag expression" )
    p.add_argument( "-j", "--jobs", default = "1",
                    help = "how many entries at once: a number, or `auto`" )
    p.add_argument( "--batch", action = "store_true", help = "launch it and give the shell back" )
    p.add_argument( "-o", dest = "keep_out", action = "store_true",
                    help = "an output directory for each run, brought back: runs/… ( $ERRAND_OUT_DIR )" )
    p.add_argument( "--out", default = None, metavar = "PATTERN",
                    help = "the same, under another tree, or as a pattern: "
                           "\"results/{env}/{when}\" ( {path} {name} {when} {place} {env} {params} )" )
    p.add_argument( "--at", default = None,
                    help = argparse.SUPPRESS )   # internal: run exactly the entry at FILE:LINE
    # internal: which phase this process is, when a command is run in two

    # run, shell
    p.add_argument( "--no-queue", action = "store_true",
                    help = "do not wait for the machine to be free" )
    p.add_argument( "--no-setup", action = "store_true", help = "skip the freshness check" )
    p.add_argument( "--pull", action = "append", default = [ ], metavar = "DIR",
                    help = "on another machine: bring this directory ( relative to the project root ) back afterwards; may be repeated" )

    # run: what it asks of the machine
    p.add_argument( "-x", "--exclusive", dest = "exclusive", action = "store_true",
                    help = "the machine to itself ( a benchmark )" )
    p.add_argument( "--cpus", dest = "cpus", default = None, help = "cores it needs" )
    p.add_argument( "--ram", dest = "ram", default = None, help = "memory it needs, e.g. 8G" )
    p.add_argument( "--gpus", dest = "gpus", default = None, help = "cards it needs" )
    p.add_argument( "--ranks", dest = "ranks", default = None,
                    help = "MPI processes: the launcher of the place starts that many ( an entry's `ranks =` )" )
    p.add_argument( "--time", dest = "time", default = None,
                    help = "how long it may take, for a batch system ( slurm's way: 30, 2:00:00, 1-12 )" )
    p.add_argument( "-m", "--mem", dest = "mem", default = None,
                    help = "memory ceiling of a command ( systemd-run, where there is one )" )
    p.add_argument( "-n", "--label", dest = "label", default = None, help = "its name in the queue" )
    p.add_argument( "-q", dest = "quiet", action = "store_true", help = "no banners" )
    p.add_argument( "-l", "--log", dest = "log", default = None, help = "its output goes there too" )

    # setup, init
    p.add_argument( "--force", action = "store_true",
                    help = "setup: from scratch; init: replace what is there; agents stop: even with something running" )
    p.add_argument( "--dry-run", action = "store_true", help = "say what setup would do, and do nothing" )

    for name in tag_names:
        p.add_argument( f"--{name.replace( '_', '-' )}", dest = f"tag_{name}", default = None,
                        help = f"environments whose {name} tag matches (comma = matrix)" )
    return p


def _takes_value( parser ):
    out = { }
    for action in parser._actions:
        for option in action.option_strings:
            out[ option ] = action.nargs != 0
    return out


def split_verb( parser, argv ):
    """-> ( the verb, argv without it ), or ( None, argv ).

    The verb is the first word that is not an option or an option's value, so
    the options everybody shares may stand on either side of it:
    `errand --env gpu run …` and `errand run --env gpu …` are the same command.
    """
    takes_value = _takes_value( parser )
    i = 0
    while i < len( argv ):
        token = argv[ i ]
        if token.startswith( "-" ) and token != "-":
            name = token.split( "=", 1 )[ 0 ]
            if "=" not in token and takes_value.get( name, False ):
                i += 1
            i += 1
            continue
        return token, argv[ : i ] + argv[ i + 1 : ]
    return None, list( argv )


def misplaced( parser, known, verb ):
    """Options given that belong to another verb. -> a message, or None.

    Said rather than ignored: `errand shell --batch -- make` would otherwise
    run the command right there and come back as if it had been launched."""
    allowed = set( COMMON ) | set( VERBS[ verb ][ 1 ] )
    for action in parser._actions:
        dest = action.dest
        if dest in allowed or dest == "pattern" or dest.startswith( "tag_" ):
            continue
        if getattr( known, dest, action.default ) != action.default:
            owners = [ v for v, ( _, own ) in VERBS.items() if dest in own ]
            return ( f"{action.option_strings[ 0 ]} is not an option of `errand {verb}`"
                     + ( f" ( it belongs to {', '.join( owners )} )" if owners else "" ) )
    return None


def split_target( parser, rest ):
    """-> ( errand's options, the target or None, the target's arguments ).

    The target is the first word that is not one of errand's options or an
    option's value. Before it, every option must be errand's: a parameter
    written there is a mistake worth hearing about, since it belongs to the
    target -- and after it, nothing is errand's, `--env` included.

    Several FILES are several targets: `errand run tests/test_*.py`, the glob
    left to the shell, hands errand one word per file, which is the same as
    `tests/test_a.py,tests/test_b.py`. The files that follow a file target and
    have its suffix are targets too, up to the first word that is not one;
    such a file meant as an argument goes after a `--`.

    So are several ENTRY patterns: `errand run a.py::x b.py::y` is `a.py::x,b.py::y`
    -- the words that follow an entry pattern and are entry patterns too
    ( `path::name`, the path a file or a glob ).
    """
    takes = _takes_value( parser )
    i = 0
    while i < len( rest ):
        token = rest[ i ]
        if token.startswith( "-" ) and token != "-":
            name = token.split( "=", 1 )[ 0 ]
            if name not in takes and not token.startswith( "--" ) and token[ : 2 ] in takes:
                i += 1                               # `-j4`: a short option and its value, attached
                continue
            if name not in takes:
                raise ValueError(
                    f"{name} is not an option of errand -- what the target takes goes after it: "
                    f"`errand run <target> {token}` ( `.` is everything under here )" )
            if "=" not in token and takes[ name ]:
                i += 1
            i += 1
            continue
        if not Path( token ).is_file():
            j = i + 1
            if _is_entry_pattern( token ):
                while j < len( rest ) and _is_entry_pattern( rest[ j ] ):
                    j += 1
            return rest[ : i ], ",".join( rest[ i : j ] ), rest[ j : ]   # a pattern: its commas separate targets
        j = i + 1
        while j < len( rest ) and _same_kind_of_file( rest[ j ], token ):
            j += 1
        # files: a comma in a name is only a comma
        return rest[ : i ], ",".join( t.replace( ",", "\\," ) for t in rest[ i : j ] ), rest[ j : ]
    return list( rest ), None, [ ]


def _is_entry_pattern( word ):
    """`path::name`, the path an existing file or a glob: an entry target, not an argument that happens to hold `::`"""
    path, sep, name = word.partition( "::" )
    return bool( sep ) and bool( path ) and not word.startswith( "-" ) and (
        Path( path ).is_file() or any( c in path for c in "*?[" ) )


def _same_kind_of_file( word, first ):
    """Whether `word`, after the target `first`, is one more target: an existing
    file of the same suffix. Not for files without one: `./convert data` is a
    program and its input."""
    suffix = Path( first ).suffix
    return ( not word.startswith( "-" ) and suffix and Path( word ).suffix == suffix
             and Path( word ).is_file() )


def own_part( parser, argv, lenient = False ):
    """The part of a command line that is errand's: up to the target, or the
    `--` of a shell. Leniently, before the project's tag options are known, an
    unknown option is taken to have a value."""
    verb, rest = split_verb( parser, argv )
    if "--" in rest:
        rest = rest[ : rest.index( "--" ) ]
    if verb not in ( "run", "list" ):
        return rest
    if not lenient:
        return split_target( parser, rest )[ 0 ]
    takes = _takes_value( parser )
    i = 0
    while i < len( rest ):
        token = rest[ i ]
        if not token.startswith( "-" ) or token == "-":
            return rest[ : i ]
        if "=" not in token and takes.get( token, True ):
            i += 1
        i += 1
    return rest


ARGS = "args"       # the target's own arguments, in the parameters of a run


def split_args( after, declared ):
    """The target's arguments -> ( { declared parameter: raw value }, [ the rest ] ).

    A declared parameter is read wherever it is ( `--n=5`, `--n 5` ); anything
    else is the target's own business and passes through as it was written --
    after a `--`, everything does.
    """
    values, raw = { }, [ ]
    i = 0
    while i < len( after ):
        token = after[ i ]
        if token == "--":
            raw += after[ i : ]
            break
        if token.startswith( "--" ) and len( token ) > 2:
            name, eq, value = token[ 2 : ].partition( "=" )
            key = name.replace( "-", "_" )
            if key in declared:
                if not eq:
                    if i + 1 >= len( after ):
                        raise ValueError( f"--{name} needs a value" )
                    value = after[ i + 1 ]
                    i += 1
                values[ key ] = value
                i += 1
                continue
        raw.append( token )
        i += 1
    return values, raw


def shown_params( resolved, values ) -> dict:
    """What tells two runs of one case apart: the parameters, and the target's
    own arguments when there were any -- `--size 4096` and `--size 8192` are
    two runs, and must be two directories."""
    raw = values.get( ARGS ) or [ ]
    return { **resolved, ARGS: " ".join( raw ) } if raw else dict( resolved )


def target_argv( e, resolved, values ) -> list:
    """The arguments a run of `e` is handed: its declared parameters as they
    were resolved for it, then the rest as written."""
    declared = [ f"--{n.replace( '_', '-' )}={v}" for n, v in resolved.items() ]
    return declared + list( values.get( ARGS ) or [ ] )
