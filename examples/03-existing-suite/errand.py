"""Adopting a project that already has a test suite.

Nothing below changes a single line of the existing tests. Each `provider` is
a declaration of what will be looked for and where -- every test framework
finds its tests by guessing about your layout, and writing the guess down is
what keeps it from being a surprise.
"""
from errand import configure, env, provider, Micromamba, Pytest, Catch2, Cargo

configure( src = [ "src" ] )

env( "local", [ Micromamba( "demo", python = "3.13", requirements = "requirements.txt" ) ] )
env( "old",   [ Micromamba( "demo-py310", python = "3.10", requirements = "requirements.txt" ) ],
     legacy = True )


# The existing suites. `Pytest()` collects with pytest's own rules; pass
# `dirs`/`args` to say something else. Without this file at all, errand would
# have found them anyway and SAID SO before running -- this line is how you
# stop it from guessing.

provider( Pytest( dirs = [ "tests" ] ) )

# One entry per .cpp file, because errand has to know the list of entries on
# this side of an ssh hop -- before anything is compiled -- to know what to
# rsync back afterwards. A `::name` in your pattern is handed to the binary as
# its own filter.
provider( Catch2( dir = "cpp", build = "make -C cpp" ) )

provider( Cargo( manifest = "rust/Cargo.toml" ) )
