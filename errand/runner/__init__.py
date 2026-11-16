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

A runner knows three things about a kind of file: whether it is the one to run
it, how to get ready, and how to run it:

    suitability( path ) -> how well this runner fits the file ( a `Level` )
    prepare( entries )  -> once, before any of them runs ( a build )
    run( entry, ctx )   -> Outcome

A file is one run of the runner's tool ( ADR 0011 ): `x.py::test_y` is handed to
pytest, `x.cpp::add*` to the Catch2 binary, `::name` to `cargo test`, and the
tool does the selecting. Only errand's own entries are cut up by errand.

`errand.runners` is a dict, name -> runner, filled with the ones that come with
errand; a project adds its own instances under names of its own, which `-r`
then picks, or `replace`s a built-in one by a configured one of the same kind.

The runners for existing suites -- pytest, Catch2, cargo -- leave everything
that makes the tool itself to the tool: its collection rules, its filters
( `-m "not slow"`, `~[slow]` ), its report, read back into the run's record.

The package's surface for the rest of errand: what each file defines, re-exported. A file
here is one runner, or what they share ( `base` ) and the dict that holds them ( `registry` ).
"""
from __future__ import annotations

from .base import _read, ERRAND, FALLBACK, FRAMEWORK, LANGUAGE, junit_outcome, Level, MARKER, NONE, Outcome, RunContext, Runner, selector_of
from .own import Errand
from .pytest import Pytest
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
    'junit_outcome',
    'RunContext',
    'Runner',
    'selector_of',
    'Errand',
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
