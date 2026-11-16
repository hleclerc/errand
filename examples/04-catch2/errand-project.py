"""A Catch2 suite built with CMake.

Nothing in the suite knows about errand. This file says three things: where the
sources are, how YOU build them, and where the binaries land.
"""
import errand

# `build` runs during the preparation, once for the whole command, in the place
# the tests will run -- before any of them starts. `{build_dir}` is this
# environment's own directory, `build/<env>/`: two environments never share a
# binary. `binary` is where each source's executable lands, `{stem}` its name.
errand.runners.replace( errand.Catch2(
    dir     = "tests",
    build   = [ "cmake -S . -B {build_dir} -DCMAKE_BUILD_TYPE=Release",
                "cmake --build {build_dir} --parallel" ],
    binary  = "{build_dir}/{stem}",
) )

# What a bare `errand run` runs.
errand.default_run = [ "tests/**::*" ]
