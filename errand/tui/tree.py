"""Files and the cases in them, as a tree, and how a path or a size is shown.
"""
from __future__ import annotations

from pathlib import Path


def short( path, root ):
    try:
        return str( Path( path ).relative_to( root ) )
    except ValueError:
        return str( path )


def size_of( path ):
    try:
        n = float( path.stat().st_size )
    except OSError:
        return "-"
    for unit in ( "B", "kB", "MB", "GB" ):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _id( entry ):
    """An entry told apart from every other: two may share a name."""
    return ( str( entry.file ), entry.line, entry.name )


def _parts( path, root ):
    """Where a file sits, one directory at a time. A file outside the project
    keeps its whole name and lands at the top: it is not part of the layout."""
    try:
        return Path( path ).relative_to( root ).parts
    except ValueError:
        return ( str( path ), )


class _Node:
    """One directory, or one file with its cases -- the project as it is laid
    out on disk, which is the only tree nobody has to be taught."""

    __slots__ = ( "path", "children", "entries" )

    def __init__( self, path ):
        self.path     = Path( path )
        self.children : dict = { }
        self.entries  : list = [ ]

    def put( self, parts, path, entries ):
        node, here = self, self.path
        for part in parts:
            here = here / part
            node = node.children.setdefault( part, _Node( here ) )
        node.path    = Path( path )
        node.entries = entries

    def count( self ):
        return len( self.entries ) + sum( c.count() for c in self.children.values() )

    def sorted( self ):
        """Directories first, then files, each in alphabetical order: the order
        a listing has, so the eye already knows it."""
        return sorted( self.children.items(), key = lambda kv: ( bool( kv[ 1 ].entries ),
                                                                 kv[ 0 ] ) )
