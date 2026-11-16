# Writing a runner

```python
import errand
from errand import Level

class Mine( errand.Runner ):
    name           = "mine"
    level          = Level.FRAMEWORK   # the highest `suitability` can answer
    takes_selector = True              # it hands a `::name` on to its tool
    jobs           = False             # True: `run` hands `ctx.jobs` to its tool

    def suitability( self, path ) -> Level: ...   # how well it fits this file
    def prepare( self, entries, ctx ):            # once, during the preparation. -> None, or why not
        return None
    def run( self, entry, ctx ) -> Outcome: ...
```

Registered with `errand.runners[ "mine" ] = Mine( )`, under which name `-r mine` picks it ( see
[the list of runners](./#the-list-of-runners) ).

`level` is the highest `Level` it can answer ( `NONE`, `FALLBACK`, `LANGUAGE`, `FRAMEWORK`,
`ERRAND` ): it lets a walk over a whole tree ask only the runners that could make a file
discoverable. `self.root` is the project root.

A file is one run ( ADR 0011 ): `run` gets an entry whose `key` is the file, and the `::name` of the
target as `ctx.selector`, to hand to its tool in the tool's own words. Without `takes_selector`, a
`::name` is refused. A runner whose run is not one per file ( cargo: one per test target ) overrides
`collect( specs )`, and makes its entries with `self.entry( name =, file =, key = )`.

What it starts, it starts with `self.tool( "name", ctx )`: the environment's own name for the tool
( `Env( tools = … )` ), or the place's. A command line written by the user fills `{name}` with
`self.fill_tools( line, ctx )`.

A tool that writes a JUnit report gives its verdict with `errand.runner.junit_outcome( path )`:
counts by status, the failed cases by name.

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

`RunContext` carries the `root`, the `out_dir` this run is writing into, its `params`, the `env`
for the child, the `build_dir`, the `selector` — the `::name` part, when there was one —, the
environment's `tools`, and `jobs`, the workers `-j` gives a single run.

## Still to ship

GoogleTest, doctest, ctest, JavaScript.

Discovery over a large tree is not free, and will be cached against file mtimes. Later; it is an
optimization, not a design question.
