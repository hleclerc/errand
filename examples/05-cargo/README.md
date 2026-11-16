# 05 — a cargo crate

An ordinary crate, with unit tests in `src/lib.rs` and an integration test in `tests/coverage.rs`.
Nothing in it knows about errand; `errand-project.py` only puts the cargo runner in place.

```
Cargo.toml          an ordinary crate, no dependencies
src/lib.rs          the library and its unit tests: one test target
tests/coverage.rs   an integration test: another test target
errand-project.py   errand.runners.replace( errand.Cargo( ) ), and a default_run
```

It needs `cargo`.

## Try it

```bash
cd examples/05-cargo

errand run                                  # default_run: compile, then every test target
errand run src/lib.rs::touching             # one target, filtered: cargo test --lib -- touching
errand run src/lib.rs::many --ignored       # what follows the target goes after `--`
```

## Two phases: compile, then run

```
  build ( cargo ): cargo test --no-run --manifest-path Cargo.toml
  built in 0.3 s

========== 2 entries  default  … ==========
PASS intervals (lib.rs)
PASS coverage (coverage.rs)
```

- **`cargo test --no-run` runs during the preparation**, once per crate, in the place the tests
  run: every test target is compiled before any of them starts. The run phase finds the binaries
  built, and only runs them.
- **The target directory is the environment's own**, `build/<env>/target` ( `CARGO_TARGET_DIR` ),
  in both phases: two environments with two toolchains never share a binary, and your own
  `target/` is left alone. `Cargo( target_dir = None )` gives it back to cargo.
- **What to recompile is cargo's business.** A second run compiles nothing.

## A test target is one run

`cargo metadata` lists the test targets without compiling anything: `src/lib.rs` and
`tests/coverage.rs` here. Each is one run of `cargo test`, and what follows `::` is the filter
`cargo test` takes after `--`. The record holds cargo's summary:

```yaml
status: PASS
results: { passed: 3, failed: 0, ignored: 1 }
```

Nothing changed in the crate: `cargo test` still works on its own.
