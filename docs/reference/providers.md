# Providers

A provider puts a suite that already exists under errand. One line in
[`errandfile.py`](/guide/configuration) per suite — see [Other languages](/guide/providers) for what
that buys and why the three behave differently.

## Pytest

```python
Pytest( dirs = ( "tests", ), root = None, args = ( ),
        python = None, install = "auto", spec = "pytest" )
```

One entry **per test**. Collection asks pytest itself rather than guessing: its rules are its own,
and reimplementing them is how a runner starts quietly disagreeing with the tool it wraps. Nothing
is built, so this is cheap enough to do on the side that predicts the paths.

| | |
|---|---|
| `dirs` | where to collect from |
| `root` | the directory to collect relative to. Default `.` |
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
Catch2( dir = "tests", pattern = "test_*.cpp", build = None,
        binary = None, args = ( ) )
```

One entry **per source file**, not per test case. The cases of a compiled suite cannot be enumerated
without building it, and collection has to work before anything is built — and the list of entries
has to be known on *this* side of an [ssh hop](/guide/remote), so that the paths to rsync back can
be computed in advance.

A `::name` in the pattern is handed to the binary as its own filter, so naming one case still
reaches one case.

| | |
|---|---|
| `dir` | where the sources are |
| `pattern` | which of them are suites. Default `test_*.cpp` |
| `build` | the command **you** already build with. Runs once before any entry of this provider |
| `binary` | where a source's executable lands. `{stem}` is the source's name. Default `<dir>/<stem>` |
| `args` | extra arguments passed to the binary |

```python
provider( Catch2( dir = "cpp", build = "make -C cpp" ) )
provider( Catch2( dir = "cpp", build = "cmake --build build", binary = "build/{stem}" ) )
```

`build` runs **once before any entry of that provider** — not once per file, and not once per
parallel process, which under `-j` would have several of them writing the same binary at the same
time. Leave it out entirely if something else already built them.

## Cargo

```python
Cargo( manifest = "Cargo.toml", args = ( ), release = False )
```

One entry **per test target**. `cargo metadata` knows the targets without compiling any of them,
which is what makes this cheap enough to run on the side that predicts the paths. Naming a single
test still works: the `::name` part becomes the filter `cargo test` takes after `--`.

`cargo test` builds what it runs, so there is no `build` to declare.

## Writing one

A three-method protocol, plus an optional fourth:

```python
from errand import Provider, Outcome

class Mine( Provider ):
    name        = "mine"
    whole_files = False          # True when an entry IS a whole file

    def files( self ): ...               # candidate source files
    def collect( self, specs ): ...      # -> the entries
    def prepare( self, entries, ctx ):   # once, before any of them. -> None, or why not
        return None
    def run( self, entry, ctx ) -> Outcome: ...
```

`whole_files = True` says an entry is a whole file, as for a compiled suite. The `::name` of a spec
then belongs to the binary rather than to the entry, so the core must not filter entries by it —
`test_math::multiplies` would match nothing, the entry being called `test_math`.

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
