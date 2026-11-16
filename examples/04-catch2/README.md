# 04 — a Catch2 suite, built with CMake

Two Catch2 suites over a small header-only library, built by an ordinary `CMakeLists.txt`. errand
compiles nothing itself: it runs **your** build, during the preparation, then runs each binary.

```
CMakeLists.txt         your build: one binary per tests/test_*.cpp, Catch2 found or fetched
include/stats.hpp      the library under test
tests/test_stats.cpp   ordinary Catch2, with a benchmark
tests/test_edges.cpp   a second suite, a second binary
errand-project.py      where the sources are, how to build, where the binaries land
```

It needs CMake and a C++17 compiler. Catch2 v3 is used when installed, otherwise CMake fetches it
into the build directory the first time ( once, about 20 s ).

## Try it

```bash
cd examples/04-catch2

errand run                                  # default_run: build, then every suite
errand run tests/test_stats.cpp::median     # one case: a Catch2 test spec, handed to the binary
errand run 'tests/test_stats.cpp::~[slow]'  # everything but the slow case
errand run -o tests/test_stats.cpp          # with an output directory: catch2.xml, result.yaml
```

## Two phases: compile, then run

```
  build ( catch2 ): cmake -S . -B build/default -DCMAKE_BUILD_TYPE=Release
  build ( catch2 ): cmake --build build/default --parallel
  built in 19.5 s

========== 2 entries  default  … ==========
PASS test_edges.cpp (test_edges.cpp)
PASS test_stats.cpp (test_stats.cpp)
```

- **The build runs during the preparation**, once for the whole command, before any test starts:
  not once per suite, and not once per process under `-j`, which would have several of them writing
  the same binary. A build that fails stops the command and shows the compiler's output.
- **It runs in the place the tests run.** With an environment on another machine or in a Slurm
  allocation, the compiler is that place's. To compile in one allocation and run in another, the
  environment gives the preparation its own layers ( `prepare = [ … ]`, see
  [Preparing, then running](../../docs/guide/environments.md#preparing-then-running) ).
- **`{build_dir}` is the environment's own**, `build/<env>/`: two environments never share a
  binary, so a number is never measured on a binary built for somewhere else.
- **Incremental is your build's business.** The second run says `built in 1.7 s`: CMake found
  nothing to redo. errand does not decide what is stale.

## A source is one run of its binary

`tests/test_stats.cpp` is one run of `build/default/test_stats`. What follows `::` is a Catch2 test
spec, handed to the binary as it is written: `::median`, `::var*`, `::[stats]~[slow]`. The record of
the run holds what the binary reported:

```yaml
status: PASS
results: { mean_10k_ns: 9079.9, median_10k_ns: 9371.57, passed: 5, failed: 0, assertions: 6 }
```

The benchmark numbers are Catch2's own measures, dated and per machine, next to everything else
errand records. A failure names the case and the expression:

```
FAIL test_stats.cpp - 1 assertion(s) failed in variance far from zero. stats::variance( x ) == … -- expanded: 0.25000025000025 == Approx( 0.25 )
```

Nothing in the suite changed: `./build/default/test_stats` still runs it on its own.
