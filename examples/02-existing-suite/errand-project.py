"""Adopting a project that already has a test suite.

Nothing below changes a single line of the existing tests. `errand.runners`
already holds a runner for each of these suites, looking where they usually
are; each line below replaces one with a declaration of what will be looked
for and where -- every test framework finds its tests by guessing about your
layout, and writing the guess down is what keeps it from being a surprise.
"""
import errand

errand.configure( src = [ "src" ] )

# No environments here: this example is about adopting suites, and declaring
# one would have running it build a micromamba environment on your machine.
# Environments are example 02.


# The existing suites. `errand.Pytest()` collects with pytest's own rules; pass
# `dirs`/`args` to say something else. Without this file at all, errand would
# have found them anyway and SAID SO before running -- this line is how you
# stop it from guessing. `replace`, not `append`: two pytest runners would both
# claim every test file, and errand refuses to choose between them.

errand.runners.replace( errand.Pytest( dirs = [ "tests" ] ) )

# errand run compiles nothing itself. `build` is whatever YOU already build with,
# run once before any entry of this runner ( not once per file, and not once
# per parallel process ); `binary` says where the result lands, defaulting to
# beside the source -- which is where this Makefile puts it.
#
#   errand.runners.replace( errand.Catch2( dir = "cpp", build = "cmake --build build",
#                     binary = "build/{stem}" ) )
#
# One entry per test case: the build runs during the preparation, where the
# cases will run, and the binary is then asked for its own cases.
errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )

# `cargo metadata` knows the targets without compiling any of them, so there is
# nothing to declare: one entry per test target.
errand.runners.replace( errand.Cargo( manifest = "rust/Cargo.toml" ) )
