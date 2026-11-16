# Venv, Uv

## Venv

```python
Venv( python = "python", requirements = None, pip = [ ], create = False )
```

A given interpreter: a venv's python, or any installed one.

```python
errand.Env( [ errand.Venv( python = ".venv-313/bin/python", requirements = "requirements.txt", create = True ) ] )
```

| | |
|---|---|
| `python` | the interpreter to run |
| `requirements` | a file, relative to the project root, installed with pip |
| `pip` | more packages, on top |
| `create` | make the venv when `python` points inside one that does not exist |

## Uv

```python
Uv( path = ".venv", python = None, requirements = None, pip = [ ] )
```

A uv-managed venv of the project, at `path` relative to the project root. `python` is the version
uv installs it with.

uv does not need to be installed: where it is neither on the `PATH` nor in `~/.local/bin` or
`~/.cargo/bin`, errand fetches one from astral.sh into its cache over there
( `~/.cache/errand/uv`, never on the `PATH`, never in a shell profile ), the one it makes its own
Python with. A cluster's nodes are such a place.

Both are [built and kept current](../upkeep) from what they declare.
