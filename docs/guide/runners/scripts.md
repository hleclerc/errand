# Scripts and executables

```python
Python( )        # the interpreter of the place it runs in
Executable( )    # run as it is: a file of the project, or a command of the place
```

```bash
errand run scripts/plot.py          # Python
errand run ./bench --size 4096      # Executable: a file of the project
errand run make -j8                 # Executable: a command on the place's PATH
```

A target without `::` goes to one of these: one entry, the whole file or command, named after it. A
first word that names an interpreter ( `python`, `python3` ) is the place's. A `.sh` is an
executable like any other: it needs its execute bit and a shebang.

Output is the run's output, the exit code the status ( 77 is a skip ), and `ERRAND_OUT_DIR` is set
to the run's directory when `-o` or `--out` asked for one ( see [Results and records](/guide/output) ).
What follows the target is its own and passes through as written. See
[Running](/guide/running) for the rest.
