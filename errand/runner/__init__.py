"""What runs a target: the runners.

What a target means is read from the command line alone, never guessed from the
project's layout:

* `x::y` -- globs allowed on both sides -- goes to an **entry runner**: errand's
  own entries, pytest, Catch2, cargo. Which one takes a file is asked of each
  ( `suitability` ), and the one that fits it best takes it; two at the same,
  highest level is an error naming them, never a coin toss. `-r NAME` picks one
  and asks nothing.
* anything else goes to a **file runner**: a `.py` to `python`, the
  interpreter of the place; anything else to `executable`, run as it is -- a
  file, or a command found on the place's own `PATH` ( `make`, `cmake`,
  `pytest` ).

An entry runner knows three things about a kind of file: whether it is the one
to run it, what entries the file holds, and how to run one:

    suitability( path ) -> how well this runner fits the file ( a `Level` )
    collect( specs )    -> [ Entry ], over the files this runner was given
    prepare( entries )  -> once, before any of them runs ( a build )
    run( entry, ctx )   -> Outcome

`errand.runners` is a dict, name -> runner, filled with the ones that come with
errand; a project adds its own instances under names of its own, which `-r`
then picks, or `replace`s a built-in one by a configured one of the same kind.

The runners for existing suites -- pytest, Catch2, cargo -- each keep everything
that makes it itself: its own collection rules, its own assertions, its own
idea of what a test is. Their vocabulary is translated rather than replaced: a
`@pytest.mark.slow` is an entry tag, so `-e '!slow'` filters it with the same
expression language `-t` uses on environments; a Catch2 `[tag]` likewise; and a
framework's own benchmark numbers land in `result.yaml` beside everyone else's.

The package's surface for the rest of errand: what each file defines, re-exported. A file
here is one runner, or what they share ( `base` ) and the dict that holds them ( `registry` ).
"""
from __future__ import annotations

from .base import _read, ERRAND, FALLBACK, FRAMEWORK, LANGUAGE, Level, MARKER, NONE, Outcome, RunContext, Runner, selector_of
from .own import Errand
from .pytest import COLLECT_TO, Pytest
from .catch2 import Catch2
from .cargo import Cargo
from .files import Executable, INTERPRETERS, OUT_DIR, Python, SKIP_CODE
from .registry import defaults, Runners


__all__ = [
    'Level',
    'NONE',
    'FALLBACK',
    'LANGUAGE',
    'FRAMEWORK',
    'ERRAND',
    'MARKER',
    '_read',
    'Outcome',
    'RunContext',
    'Runner',
    'selector_of',
    'Errand',
    'COLLECT_TO',
    'Pytest',
    'Catch2',
    'Cargo',
    'INTERPRETERS',
    'OUT_DIR',
    'SKIP_CODE',
    'Python',
    'Executable',
    'Runners',
    'defaults',
]
