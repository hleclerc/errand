"""The screen: its panes, its two pages, what is ticked, folded and opened.
"""
from __future__ import annotations

from ..session import Session
from .panes import Pane
from .dialog import Dialog
from .lists import Lists
from .actions import Actions


class Screen( Lists, Actions ):
    def __init__( self, session: Session ):
        self.session = session
        self.cases   = Pane( "cases", "cases" )
        self.about   = Pane( "about", "about" )
        self.about.plain = True
        self.runs    = Pane( "runs", "runs" )
        self.files   = Pane( "files", "files" )
        self.look    = Pane( "look", "preview" )
        self.look.plain = True
        # Two pages, because they answer two questions: WHAT DO I RUN, and
        # WHAT CAME OF IT. Putting both on one screen made each of them half a
        # screen wide, and there are more cases than a half screen holds.
        self.pages   = { "cases": [ self.cases, self.about ],
                         "runs" : [ self.runs, self.files, self.look ] }
        self.tabs    : list = [ ]      # where the page names are, for clicking
        self.page    = "cases"
        self.active  = 0
        self.ticked  : set = set()     # cases, by ( file, line, name )
        self.folded  : set = set()     # files whose cases are hidden
        self.opened  : set = set()     # commands whose runs are shown
        # One search per page, because they are two lists: the one you keep on
        # `cases` is not lost by going to look at `runs`.
        self.queries = { "cases": "", "runs": "" }
        self.dialog  : Dialog | None = None
        self.message = ""
        self.past    : dict = { }      # command -> ( plan, states )
        self.looked  = 0.0
        self.dirty   = False           # a key changed what the lists hold
        self.help    = False

    # ── what a key does ──────────────────────────────────────────────────────

    @property
    def panes( self ):
        return self.pages[ self.page ]

    def pane( self ):
        self.active = min( self.active, len( self.panes ) - 1 )
        return self.panes[ self.active ]

    @property
    def query( self ):
        return self.queries[ self.page ]
