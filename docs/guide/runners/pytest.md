# Pytest

```python
Pytest( dirs = None, patterns = ( "test_*.py", "*_test.py" ), args = ( ),
        python = None, install = "auto", spec = "pytest", zones = None )
```

A file is **one run of pytest**. What is in it is pytest's business: errand does not list the tests,
it hands pytest what was typed.

- `x.py` runs the whole file.
- `x.py::test_y` and `x.py::TestA::test_y[3]` are node ids, handed to pytest as they are.
- `x.py::test_a*` is a pattern: errand asks pytest what the file holds ( `--collect-only` ) and
  runs what matches. A pattern that matches nothing is an error that shows what is there.

The run's record holds pytest's verdict, read from its JUnit report: how many passed, failed and
were skipped, and the names of the failed ones with the first failure's message.

| | |
|---|---|
| `dirs` | the directories its files must be under, relative to the project root. Default: anywhere |
| `patterns` | the file names it takes |
| `args` | extra arguments passed to pytest |
| `zones` | where its tool writes outside the run's directory: `{ "/htmlcov": "back" }`. See [What a tool writes elsewhere](./#what-a-tool-writes-elsewhere) |
| `python` | the interpreter to run pytest with. Default: the environment's `tools[ "python" ]`, else the one errand runs with, in the place |
| `install` | `"auto"`: install pytest when the environment is errand's to install into; `True`, `False` |
| `spec` | what to install, when it installs. `"pytest"`, or a pinned spec |

```python
# errand-project.py
errand.runners.replace( errand.Pytest( dirs = [ "tests" ] ) )
```

Marks are pytest's own filter, written after the target, with pytest's arguments:

```bash
errand run 'tests/**::*' -m "not slow"
```

`-e` filters errand's own entries, and is refused with pytest targets rather than ignored.

## A missing pytest is installed when the environment is errand's

::: info install = "auto"
Into a venv, a micromamba environment or a container, a missing pytest is installed and errand says
so. Into the **system** interpreter it declines and tells you what to run: that one is shared with
everything else on the machine, and it is not errand's to change.
:::

`install = False` turns this off entirely; `install = True` installs even into the system
interpreter.
