# Catch2

```python
Catch2( dir = None, pattern = "test_*.cpp", build = None,
        binary = None, args = ( ) )
```

One entry **per test case**. `build` runs during the preparation, in the place the cases will run,
and the binary is then asked for its cases ( `--list-tests --reporter xml`, or
`--list-test-names-only` for Catch2 v2 ). A build that fails, or a binary that cannot list itself,
costs its files' rows and nothing else.

A `::name` in the target is handed to the binary as its own filter, so naming one case still
reaches one case.

| | |
|---|---|
| `dir` | the directory its sources must be under. Default: anywhere |
| `pattern` | which of them are suites. Default `test_*.cpp` |
| `build` | the command **you** already build with. Runs once before any entry of this runner |
| `binary` | where a source's executable lands. `{stem}` is the source's name, `{dir}` its directory. Default: beside it |
| `{build_dir}` | in `build` and `binary`: this environment's own build directory, `build/<env>/` ( `errand.configure( build = … )` moves it ). The build also gets it as `ERRAND_BUILD_DIR` |
| `args` | extra arguments passed to the binary |

```python
# errand-project.py
errand.runners.replace( errand.Catch2( dir = "cpp", build = "make -C cpp" ) )
# or
errand.runners.replace( errand.Catch2( dir = "cpp", build = "cmake --build build", binary = "build/{stem}" ) )
```

`build` runs **once before any entry of that runner**, in the environment the entries run in — not once per file, and not once per
parallel process, which under `-j` would have several of them writing the same binary at the same
time. Leave it out entirely if something else already built them.

Your compiler, your flags and your layout stay yours: errand compiles nothing itself, and asking it
to know about your build would be asking it to have opinions it has no way to hold.
