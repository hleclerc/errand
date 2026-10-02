"""errand's own project file -- which exists mostly to say WHERE errand's project starts.

errand needs no configuration: with none at all it finds the entries below it and runs them in
the interpreter it was started with, which is exactly how this suite is meant to run. What this
file adds is the boundary. A checkout sitting inside another project ( this one lives beside
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
