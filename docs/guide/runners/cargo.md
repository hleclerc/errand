# Cargo

```python
Cargo( manifest = None, args = ( ), release = False )
```

One entry **per test target**; its file is the target's source root ( `src/lib.rs`,
`tests/foo.rs` ), and its crate the nearest `Cargo.toml` above it, or `manifest` when given.
`cargo metadata` knows the targets without compiling any of them,
which is what makes collecting cheap. Naming a single
test still works: the `::name` part becomes the filter `cargo test` takes after `--`.

`cargo test` builds what it runs, so there is no `build` to declare.
