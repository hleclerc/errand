# Cargo

```python
Cargo( manifest = None, args = ( ), release = False )
```

One entry **per test target**; its file is the target's source root ( `src/lib.rs`,
`tests/foo.rs` ), and its crate the nearest `Cargo.toml` above it, or `manifest` when given.
`cargo metadata` knows the targets without compiling any of them, so collecting is cheap.

```python
# errand-project.py
errand.runners.replace( errand.Cargo( manifest = "rust/Cargo.toml" ) )
```

Naming a single test still works: the `::name` part becomes the filter `cargo test` takes after
`--`. Each entry is tagged `cargo` and with its target's kind ( `lib`, `test`, … ), for `-e`.

`cargo test` builds what it runs, so there is no `build` to declare.
