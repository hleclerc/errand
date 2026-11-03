# Vars

```python
Vars( values: dict | callable )
```

Environment variables for the child.

`values` may be a **callable taking the selected tags**, which is how a single environment covers a
whole dimension instead of being split into one environment per value:

```python
Vars( lambda t: { "MYPROJ_FTYPE": f"FP{ t.get( 'fp', '64' ) }" } )
```

See [Tags only select](../tags#tags-only-select).
