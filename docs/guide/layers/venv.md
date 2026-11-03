# Venv, Uv

## Venv

```python
Venv( python = "python", requirements = None, pip = [ ], create = False )
```

A specific interpreter: a venv's python, or any installed one. `create = True` makes the venv if
`python` points inside one that is missing. `requirements` is a path relative to the project root.

## Uv

```python
Uv( path = ".venv", python = None, requirements = None, pip = [ ] )
```

A uv-managed venv in the project. `path` is relative to the project root.
