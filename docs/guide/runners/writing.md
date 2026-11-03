# Writing a runner

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

Registered with `errand.runners[ "mine" ] = Mine( )`, under which name `-r mine` picks it.
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
