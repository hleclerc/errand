"""errand's own entries: the files that declare work with `errand.test`, `bench`, `experiment`.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from .base import _read, ERRAND, MARKER, NONE, Runner


class Errand( Runner ):
    """Files that declare entries with errand's own guard ( `if test( … ):` ).

    Collected and run by the core itself -- by importing the file, then
    re-importing it once per entry -- so this runner only says which files are
    its own. It is in the list like the others so that it can be seen, ranked,
    and taken out.
    """

    name = "errand"
    level = ERRAND
    in_process = True

    # The project's own files mention errand by nature, and re-executing one as
    # if it declared work would register everything it declares a second time.
    NOT_WORK = "errand-*.py"

    def suitability( self, path ):
        if path.suffix != ".py" or fnmatch.fnmatchcase( path.name, self.NOT_WORK ):
            return NONE
        here = Path( __file__ ).resolve().parent.parent   # errand's own sources import errand
        if here in Path( os.path.realpath( path ) ).parents:
            return NONE
        return ERRAND if MARKER.search( _read( path ) ) else NONE
