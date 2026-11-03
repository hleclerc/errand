# Scripts and executables

```python
Python( )        # sys.executable of the place it runs in
Executable( )    # run as it is: a file of the project, or a command of the place
```

One entry each, the whole file or command, named after it; taken for a target without `::`. A first
word that names an interpreter ( `python`, `python3` ) is the place's. A `.sh` is an executable like
any other: it needs its execute bit and a shebang. Output is the run's output, the exit code the
status ( 77 is a skip ), and `ERRAND_OUT_DIR` is set to the directory of the run when `-o` or
`--out` asked for one.
