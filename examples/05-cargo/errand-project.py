"""A cargo crate.

`cargo metadata` lists the test targets without compiling anything: `src/lib.rs`
is one, `tests/coverage.rs` another. Each is one run of `cargo test`.

The tests are compiled during the preparation ( `cargo test --no-run` ), once,
in the place they will run, into this environment's own target directory,
`build/<env>/target`. The run phase only runs what was built.
"""
import errand

errand.runners.replace( errand.Cargo( ) )

errand.default_run = [ "**::*" ]
