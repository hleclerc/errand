# Catch2

```python
Catch2( dir = None, pattern = "test_*.cpp", build = None,
        binary = None, args = ( ) )
```

One entry **per test case**. `build` runs during the preparation, in the place the cases will run,
and the binary is then asked for its cases ( `--list-tests --reporter xml`, or
`--list-test-names-only` for Catch2 v2 ). A build that fails, or a binary that cannot list itself,
costs its files' rows and nothing else.

```python
# errand-project.py
errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )
# or
errand.runners.replace( errand.Catch2( dir = "cpp", build = "cmake --build build", binary = "build/{stem}" ) )
```

| | |
|---|---|
| `dir` | the directory its sources must be under. Default: anywhere |
| `pattern` | which of them are suites. Default `test_*.cpp`; a source must also mention catch |
| `build` | the command **you** already build with. Runs once before any entry of this runner |
| `binary` | where a source's executable lands. `{stem}` is the source's name, `{dir}` its directory. Default: beside it, without the extension |
| `{build_dir}` | in `build` and `binary`: this environment's own build directory, `build/<env>/` ( `errand.configure( build = … )` moves it ). The build also gets it as `ERRAND_BUILD_DIR` |
| `args` | extra arguments passed to the binary |

`::name` picks cases by name, globs included, and each case runs alone: `binary "the case"`. The
case's `[tags]` are entry tags, for `-e`.

`build` runs **once before any entry of that runner**, in the environment the entries run in: not
once per file, and not once per process under `-j`, which would have several of them writing the
same binary at the same time. Leave it out if something else already built them. errand compiles
nothing itself.
