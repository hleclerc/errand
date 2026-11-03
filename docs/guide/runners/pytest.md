# Pytest

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
[expression language](/reference/expressions) that `-t` uses on environments.

## A missing pytest is installed when the environment is errand's

::: info install = "auto"
Into a venv, a micromamba environment or a container, a missing pytest is installed and errand says
so. Into the **system** interpreter it declines and tells you what to run: that one is shared with
everything else on the machine, and it is not errand's to change.
:::

`install = False` turns this off entirely.
