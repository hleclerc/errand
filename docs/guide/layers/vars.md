# Vars

```python
Vars( values )
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

`{root}` in a value is the project's root **where the command runs**: its copy on a machine reached by
`Ssh`, its copy in a Windows guest (on the guest's data disk, `E:\Projects-rsync`), the project itself
here. A path into the project stays right wherever errand puts the copy:

```python
errand.Env( [ LMO, WINDOWS, errand.Vars( { "PYTHONPATH": "{root}\\loom\\src;{root}\\errand" } ) ] )
```

Nothing else between braces is touched: `"{fp}"` stays `"{fp}"`.
