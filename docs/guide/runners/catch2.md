# Catch2

```python
Catch2( dir = None, pattern = "test_*.cpp", build = None,
        binary = None, args = ( ), zones = None )
```

A source is **one run of its binary**. `build` runs during the preparation, in the place the binary
will run, and a build that fails stops the command before anything runs.

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
| `build` | the command **you** already build with, or a list of them, run in order. Runs once, during the preparation |
| `binary` | where a source's executable lands. `{stem}` is the source's name, `{dir}` its directory. Default: beside it, without the extension |
| `{build_dir}` | in `build` and `binary`: this environment's own build directory, `build/<env>/` ( `errand.configure( build = … )` moves it ). The build also gets it as `ERRAND_BUILD_DIR` |
| `args` | extra arguments passed to the binary |
| `zones` | where its tool writes outside the run's directory: `{ "/htmlcov": "back" }`. See [What a tool writes elsewhere](./#what-a-tool-writes-elsewhere) |

`::spec` is a Catch2 test spec, handed to the binary as it is written: `::adds`, `::mult*`,
`::[math]~[slow]`. The run's record holds the cases that passed and failed, the assertions, and the
numbers of Catch2's own benchmarks.

`build` runs **once before any run of that runner**, in the environment the entries run in: not
once per file, and not once per process under `-j`, which would have several of them writing the
same binary at the same time. Leave it out if something else already built them. errand compiles
nothing itself.


## Example: a CMake build, then the binaries

[`examples/04-catch2`](https://github.com/hleclerc/errand/tree/main/examples/04-catch2) is two Catch2
suites built by an ordinary `CMakeLists.txt`, one binary per `tests/test_*.cpp`:

```python
# errand-project.py
errand.runners.replace( errand.Catch2(
    dir     = "tests",
    build   = [ "cmake -S . -B {build_dir} -DCMAKE_BUILD_TYPE=Release",
                "cmake --build {build_dir} --parallel" ],
    binary  = "{build_dir}/{stem}",
) )
```

`errand run` compiles first, then runs:

```
  build ( catch2 ): cmake -S . -B build/default -DCMAKE_BUILD_TYPE=Release
  build ( catch2 ): cmake --build build/default --parallel
  built in 19.5 s

========== 2 entries  default  … ==========
PASS test_edges.cpp (test_edges.cpp)
PASS test_stats.cpp (test_stats.cpp)
```

- The build is part of the **preparation**: it runs once for the command, before any test starts,
  in the place the tests run. If it fails, nothing runs, and the compiler's output is shown.
- `{build_dir}` is `build/<env>/`: each environment compiles into its own directory.
- Deciding what to recompile is CMake's job. The second run says `built in 1.7 s`.
- To compile in one allocation and run in another, give the preparation its own layers:
  [Preparing, then running](/guide/environments#preparing-then-running).

The record of `tests/test_stats.cpp` holds what the binary reported, Catch2's benchmarks included:

```yaml
results: { mean_10k_ns: 9079.9, median_10k_ns: 9371.57, passed: 5, failed: 0, assertions: 6 }
```
