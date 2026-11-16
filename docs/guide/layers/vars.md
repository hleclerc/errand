# Vars

```python
Vars( values, when = None )
```

Environment variables for the child process.

```python
errand.Env( [ errand.Micromamba( "myenv" ), errand.Vars( { "OMP_NUM_THREADS": "8" } ) ] )
```

`values` is a dict, or a **function of the selected tags** that returns one. That is how one
environment covers a whole dimension instead of being split into one environment per value:

```python
Vars( lambda t: { "MYPROJ_FTYPE": f"FP{ t.get( 'fp', '64' ) }" } )
```

Values are turned into strings. See [Tags only select](../tags#tags-only-select).
