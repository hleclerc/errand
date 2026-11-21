"""For the tests that describe the runs done through each machine's `history`: those runs, as this machine's record
( ADR 0025, `agents.registry` ) would hold them -- the runs' tab reads the record, not the histories."""


class _Record:
    """what the runs' tab asks of the record ( `registry.Registry` ), from the machines' histories as they are now"""

    def __init__( self, machines ):
        self.machines, self.runs, self.roots = machines, { }, [ ]

    @property
    def version( self ):
        return repr( [ ( m.name, ( m.history or { } ).get( "runs" ) ) for m in self.machines ] )

    def refresh( self, *_, **__ ):
        return False

    def forget( self, leaves ):
        gone = set( leaves )
        for m in self.machines:
            if isinstance( m.history, dict ):
                m.history = { **m.history, "runs": [ r for r in m.history.get( "runs", [ ] ) if r.get( "leaf" ) not in gone ] }

    def records( self ):
        from errand.tui import rows as R
        out = [ ]
        for m in self.machines:
            m._host = m.name
            for r in ( m.history or { } ).get( "runs", [ ] ):
                rel = R.rel_of( r.get( "leaf" ) )
                out.append( { **r, "host": m.name, **( { "rel": rel } if rel else { } ) } )
        return out


def recorded( machines ):
    """from now on, the record of this process is the runs of these machines' histories"""
    from errand.agents import registry as G
    G._shared[ str( G._cache() ) ] = _Record( list( machines ) )
    return machines


def from_histories():
    """every `rows.build` of this test file reads the runs from the histories of the machines it is given -- of this
    file only: the files of a suite share one process, and the others' builds read the record they made"""
    import sys
    from pathlib import Path
    from errand import entries as E
    from errand.tui import rows as R
    mine = Path( sys._getframe( 1 ).f_globals[ "__file__" ] ).resolve()
    if not getattr( R.build, "_histories", None ):
        build = R.build

        def histories( machines, **kw ):
            here = getattr( E.target, "file", None )
            if here is None or Path( here ).resolve() in histories._histories:
                recorded( machines )
            return build( machines, **kw )
        histories._histories = set()
        R.build = histories
    R.build._histories.add( mine )
