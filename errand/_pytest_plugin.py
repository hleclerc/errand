"""A pytest plugin that writes down what pytest collected, and nothing else.

Loaded with `-p errand._pytest_plugin` for a `--collect-only` run. Asking
pytest what its tests are, rather than reimplementing its rules, is what keeps
errand from quietly disagreeing with the tool it wraps -- and its marks are
what become entry tags.
"""
import json
import os


def pytest_collection_finish( session ):
    where = os.environ.get( "ERRAND_COLLECT_TO" )
    if not where:
        return
    items = [ ]
    for item in session.items:
        items.append( {
            "id"   : item.nodeid,
            "file" : str( item.path ) if hasattr( item, "path" ) else str( item.fspath ),
            "name" : item.name,
            "marks": sorted( { m.name for m in item.iter_markers() } ),
        } )
    with open( where, "w" ) as handle:
        json.dump( items, handle )
