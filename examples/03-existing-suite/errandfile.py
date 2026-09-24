"""Adopting a project that already has a test suite.

Nothing below changes a single line of the existing tests. Each `provider` is
a declaration of what will be looked for and where -- every test framework
finds its tests by guessing about your layout, and writing the guess down is
what keeps it from being a surprise.
"""
from errand import configure, provider, Pytest, Catch2, Cargo

configure( src = [ "src" ] )

# No environments here: this example is about adopting suites, and declaring
# one would have running it build a micromamba environment on your machine.
# Environments are example 02.


# The existing suites. `Pytest()` collects with pytest's own rules; pass
# `dirs`/`args` to say something else. Without this file at all, errand would
# have found them anyway and SAID SO before running -- this line is how you
# stop it from guessing.

provider( Pytest( dirs = [ "tests" ] ) )

# errand compiles nothing itself. `build` is whatever YOU already build with,
# run once before any entry of this provider ( not once per file, and not once
# per parallel process ); `binary` says where the result lands, defaulting to
# `<dir>/<stem>` -- which is where this Makefile puts it.
#
#   provider( Catch2( dir = "cpp", build = "cmake --build build",
#                     binary = "build/{stem}" ) )
#
# One entry per .cpp file, because errand has to know the list of entries on
# this side of an ssh hop -- before anything is compiled -- to know what to
# rsync back afterwards. A `::name` in your pattern is handed to the binary as
# its own filter.
provider( Catch2( dir = "cpp", build = "make -C cpp" ) )

# `cargo metadata` knows the targets without compiling any of them, so there is
# nothing to declare: one entry per test target.
provider( Cargo( manifest = "rust/Cargo.toml" ) )
