# Runners

A runner is what runs a kind of file. `errand.runners` holds the ones below, and a project edits it
in [`errand-project.py`](/guide/configuration) — see [Runners](/guide/runners) for how a file is
given to one, and why the suites behave differently.

| runner | level | takes | one entry per |
|---|---|---|---|
| `Errand()` | `ERRAND` | a `.py` that imports errand | `if test( … ):` |
| `Pytest()` | `FRAMEWORK` | `test_*.py`, `*_test.py` | test |
| `Catch2()` | `FRAMEWORK` | `test_*.cpp` that mentions catch | test case, after a build |
| `Cargo()` | `FRAMEWORK` | the source root of a test target of the nearest `Cargo.toml` | target |
| `Python()` | `LANGUAGE` | a `.py`, named in full | file |
| `Shell()` | `LANGUAGE` | a `.sh` ( run by `sh` ) or `.bash`, named in full | file |
| `Executable()` | `FALLBACK` | anything executable, named in full | file |

The highest level wins; a tie at the top is an error naming the runners. `ERRAND` and `FRAMEWORK`
files are found by globs, directories and a bare `errand run`; the others only when named.

```python
errand.runners.replace( runner )   # in place of the runners of its kind; -> runner
errand.runners.append( runner )    # beside them
errand.runners.remove( runner )    # and any other list operation
```

## Pytest

```python
Pytest( dirs = None, patterns = ( "test_*.py", "*_test.py" ), args = ( ),
        python = None, install = "auto", spec = "pytest" )
```

One entry **per test**. Collection asks pytest itself rather than guessing: its rules are its own,
and reimplementing them is how a runner starts quietly disagreeing with the tool it wraps. Nothing
is built, so collecting is cheap.

| | |
|---|---|
| `dirs` | the directories its files must be under, relative to the project root. Default: anywhere |
| `patterns` | the file names it takes |
| `args` | extra arguments passed to pytest |
| `python` | the interpreter to run pytest with. Default: the current one |
| `install` | `"auto"` — install pytest when the environment is errand's to install into; `True`, `False` |
| `spec` | what to install, when it installs. `"pytest"`, or a pinned spec |

A `@pytest.mark.slow` **is** an entry tag, so `-e '!slow'` filters it with the same
[expression language](./expressions) that `-t` uses on environments.

::: info install = "auto"
Into a venv, a micromamba environment or a container, a missing pytest is installed and errand says
so. Into the **system** interpreter it declines and tells you what to run: that one is shared with
everything else on the machine, and it is not errand's to change.
:::

## Catch2

```python
Catch2( dir = None, pattern = "test_*.cpp", build = None,
        binary = None, args = ( ) )
```

One entry **per test case**. `build` runs during the preparation, in the place the cases will run,
and the binary is then asked for its cases ( `--list-tests --reporter xml`, or
`--list-test-names-only` for Catch2 v2 ). A build that fails, or a binary that cannot list itself,
costs its files' rows and nothing else.

A `::name` in the pattern is handed to the binary as its own filter, so naming one case still
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

## Cargo

```python
Cargo( manifest = None, args = ( ), release = False )
```

One entry **per test target**; its file is the target's source root ( `src/lib.rs`,
`tests/foo.rs` ), and its crate the nearest `Cargo.toml` above it, or `manifest` when given.
`cargo metadata` knows the targets without compiling any of them,
which is what makes collecting cheap. Naming a single
test still works: the `::name` part becomes the filter `cargo test` takes after `--`.

`cargo test` builds what it runs, so there is no `build` to declare.

## Python, Shell, Executable

```python
Python( )        # sys.executable of the place it runs in
Shell( )         # sh for a .sh, bash for a .bash
Executable( )    # run as it is
```

One entry each, the whole file, named after it; taken only when named in full. Output is the run's
output, the exit code the status, and `ERRAND_OUT_DIR` is set to the directory of the run.

## Writing one

```python
import errand
from errand import Level

class Mine( errand.Runner ):
    name           = "mine"
    level          = Level.FRAMEWORK   # the highest `suitability` can answer
    whole_files    = False             # True when an entry IS a whole file
    takes_selector = False             # ...and it hands a `::name` on to it

    def suitability( self, path ) -> Level: ...   # how well it fits this file
    def collect( self, specs ): ...               # -> the entries of the files it was given
    def prepare( self, entries, ctx ):            # once, before any of them. -> None, or why not
        return None
    def run( self, entry, ctx ) -> Outcome: ...
```

`level` is what lets a walk over a whole tree ask only the runners that could make a file
discoverable. A runner with `builds_to_collect = True` has `prepare` called before `collect`, during
the preparation, with `self.context.build_dir` saying where the build goes. `specs` are `( files, name_glob )` pairs over the files this runner won; `self.root` is
the project root, and `self.entry( name =, file =, key = )` makes an entry of this runner's.

With `whole_files = True`, the `::name` of a target belongs to the file rather than to the entry, so
the core does not filter entries by it: with `takes_selector = True` it reaches `run` as
`ctx.selector`, and without it is refused.

**Building belongs in `prepare`, not in `run`**: a suite is built once, not once per file, and `-j`
would otherwise have several processes writing the same binary at the same time.

```python
@dataclass
class Outcome:
    status : str                  # PASS | FAIL | SKIP
    error  : str | None = None
    results: dict = { }           # numbers; they land in result.yaml
    output : str = ""
```

`RunContext` carries the `root`, the `out_dir` this entry is writing into, its `params`, the `env`
for the child, and the `selector` — the `::name` part, when there was one.

## Still to ship

GoogleTest, doctest, ctest, JavaScript.

Discovery over a large tree is not free, and will be cached against file mtimes. Later; it is an
optimization, not a design question.
