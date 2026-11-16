# Module

```python
Module( "gcc/13", "cuda/12", when = None )
```

Lmod or environment modules: how a cluster picks a toolchain. The command runs as
`module load gcc/13 && module load cuda/12 && exec …`.

`module` is a shell function, not a program, so the layer goes through a login shell ( `sh -lc` ) for
it to exist at all.
