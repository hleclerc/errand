# Nix, Guix

## Nix

```python
Nix( flake = ".", shell = None )     # nix develop <flake>[#<shell>] -c …
```

## Guix

```python
Guix( manifest = None, packages = [ ] )    # guix shell -m <manifest> -- …
```

With no manifest, `packages` is passed instead.
