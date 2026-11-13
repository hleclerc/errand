"""The command line. One file per part:

    main       parse, and hand the verb to whoever does it
    parsing    the parser, the verbs, where errand's options end and the target's begin
    help       `--help`, and what is suggested when nothing matched
    style      colours, and capturing what a run prints
    project    the project's root, its source paths, its environments and tags
    grid       parameters with several values: the matrix of runs
    here       running entries in this process
    parallel   running them in several ( `-j` )
    inside     one environment, from inside it: the plan, preparing, running
    there      one environment, from outside it: handing the command over
    batches    `--batch`, `status`, `watch`
    listing    `envs`, `queue`, `list`, what could not be read
    verbs      the verbs that are one call
"""
from __future__ import annotations

from .main import main
from .parsing import ARGS, build_parser, KINDS, split_args, split_target, split_verb
from .grid import alternatives, describe_grid, expand, separator_for
from .plans import plan_of, plan_path, planned, read_plan
from .project import _put_src_on_path, _targets, child_env_for, IN_ENV, output_tree
from .here import aggregate_needs
from .parallel import job_count


__all__ = [
    'main',
    'split_target',
    'alternatives',
    'expand',
    'split_args',
    'build_parser',
    'KINDS',
    'ARGS',
    'split_verb',
    'planned',
    'plan_of',
    'output_tree',
    'describe_grid',
    'separator_for',
    '_targets',
    '_put_src_on_path',
    'IN_ENV',
    'aggregate_needs',
    'job_count',
    'child_env_for',
    'plan_path',
    'read_plan',
]
