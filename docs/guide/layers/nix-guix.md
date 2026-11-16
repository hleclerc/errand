# Nix, Guix

## Nix

```python
Nix( flake = ".", shell = None, when = None )
```

Runs the command as `nix develop <flake>[#<shell>] -c …`.

## Guix

```python
Guix( manifest = None, packages = [ ], when = None )
```

Runs the command as `guix shell -m <manifest> -- …`, or `guix shell <packages> -- …` without a
manifest.
