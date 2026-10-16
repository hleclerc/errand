"""errand's own project file -- which says WHERE errand's project starts, and what its suite is.

What this file adds first is the boundary. A checkout sitting inside another project ( this one lives beside
`loom`, `sdot` and `otrec` in a bigger repository ) would otherwise be read as part of it: the
root is the nearest directory above that HAS one of these, and without this file that is the
directory above.

That boundary works both ways, and both are the rule doing its job:

* run from here, `errand` is this project and stops at its edges;
* run from the repository above, this directory is another project and is not walked into.
"""
import errand

errand.configure(
    out = "runs",
    # The suite makes little projects in temporary directories; nothing here is vendored, and
    # `examples/` is example code that is MEANT to be found -- it is how the examples are tested.
    exclude = [ "dist", "build", ".venv-release" ],
)

# What a bare `errand run` ( `make test` ) runs: the suite, written with errand itself.
errand.default_run = [ "tests/**::*" ]
