# Cargo

```python
Cargo( manifest = None, args = ( ), release = False, target_dir = "{build_dir}/target", zones = None )
```

One run **per test target**; its file is the target's source root ( `src/lib.rs`,
`tests/foo.rs` ), and its crate the nearest `Cargo.toml` above it, or `manifest` when given.
`cargo metadata` knows the targets without compiling any of them, so collecting is cheap.

```python
# errand-project.py
errand.runners.replace( errand.Cargo( manifest = "rust/Cargo.toml" ) )
```

Naming a single test still works: the `::name` part becomes the filter `cargo test` takes after
`--`.

There is no `build` to declare: the runner compiles every test target during the **preparation**,
with `cargo test --no-run`, once per crate, in the place the tests run. The run phase only runs
what was built. Cargo builds into this environment's own directory, `build/<env>/target`
( `CARGO_TARGET_DIR` ), in both phases, so two environments never share a binary.
`target_dir = None` leaves it to cargo ( `target/` ).

| | |
|---|---|
| `manifest` | the `Cargo.toml`, relative to the project root. Default: the nearest one above each file |
| `args` | extra arguments to `cargo test`, before `--` |
| `zones` | where its tool writes outside the run's directory: `{ "/htmlcov": "back" }`. See [What a tool writes elsewhere](./#what-a-tool-writes-elsewhere) |
| `release` | build and test with `--release` |
| `target_dir` | where cargo builds. `{build_dir}` is `build/<env>/` |

What is written after the target goes after `--`: `errand run src/lib.rs::many --ignored` is
`cargo test --lib -- many --ignored`. The record holds cargo's summary:
`results: { passed: 3, failed: 0, ignored: 1 }`.

## Example

[`examples/05-cargo`](https://github.com/hleclerc/errand/tree/main/examples/05-cargo) is a crate with
unit tests in `src/lib.rs` and an integration test in `tests/coverage.rs`, two test targets:

```
  build ( cargo ): cargo test --no-run --manifest-path Cargo.toml
  built in 0.3 s

========== 2 entries  default  … ==========
PASS intervals (lib.rs)
PASS coverage (coverage.rs)
```
