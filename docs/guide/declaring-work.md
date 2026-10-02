# Declaring work

An **entry** is a piece of work that produces something. You declare it next to the code it
exercises, with a guard that reads like `if __name__ == "__main__":` but does more — several per
file, mixable freely, each identified by its **call site** so that two can share a name:

```python
from errand import entry, Param

if p := entry( "solve", n = Param( 1000, help = "problem size" ) ):
    p.results[ "seconds" ] = solve( p.n )
    ( p.out_dir / "residual.png" ).write_bytes( plot( ) )
    assert p.results[ "seconds" ] < 60
```

`errand` imports the file once to find its entries, then re-imports it once per selected entry, so
every body runs isolated and every failure is caught on its own.

The walrus form hands back the resolved parameters, the output directory, and a `results` dict to
drop numbers into. An entry can assert, record numbers and write files to look at, all three at
once — there is no rule that a benchmark may not fail, or that a test may not produce a picture.

## What the guard gives you

| | |
|---|---|
| `p.<name>` | each declared [parameter](./matrices), resolved: the default, or what the command line asked for |
| `p.out_dir` | this run's own directory, already created. Write anything you like into it |
| `p.results` | a dict to drop numbers and strings into; it ends up in `result.yaml` |

`p.results` takes anything. Numeric values are summarized (min and max) at every level above the
run, which is what makes two dates or two machines comparable without you declaring anything.

Outside errand — a file you ran by hand — `out_dir()` answers `./out`, so an ad-hoc run still has
somewhere to put its files.

## The four traits

Four traits say how an entry should be treated:

| trait | what it decides | default |
|---|---|---|
| `bulk` | picked up by a bare `errand`, with no pattern | `True` |
| `keep` | its numbers are kept and compared date to date | `False` |
| `exclusive` | it needs the machine to itself | `False` |
| `stable_path` | `latest/` is what you are meant to open | `False` |

## test, bench, experiment

Setting the traits by hand every time would be tedious, so three ordinary functions set them for
you:

```python
from errand import test, bench, experiment, Param

if test( "addition" ):                       # bulk
    assert 1 + 1 == 2

if p := bench( "solve", n = Param( 1000 ) ): # keep, exclusive, not bulk
    p.results[ "seconds" ] = solve( p.n )

if p := experiment( "the shape of it" ):     # stable_path, not bulk
    plot( ).savefig( p.out_dir / "shape.png" )
```

| | it must | traits |
|---|---|---|
| `test` | pass | `bulk` |
| `bench` | be fast — and its numbers are kept | `keep`, `exclusive`, not `bulk` |
| `experiment` | be looked at — `latest/` is the path to open | `stable_path`, not `bulk` |

They are three lines of Python over `entry`, and you can write a fourth of your own the same way.
Note that a bare `errand` runs **only the tests**: a benchmark or an experiment is named, or asked
for with `-k bench` / `-k exp`.

Override a trait on the spot when the preset is not quite right:

```python
if p := experiment( "the big one", exclusive = True ):   # a picture that needs the whole GPU
if p := bench( "cheap probe", exclusive = False ):       # a number that does not
```

## Resources

An entry says what it needs, and nothing gets to ignore it:

```python
if p := bench( "solve" ):                            # exclusive: the machine to itself
if p := test( "wide", cpus = 4, ram = "8G" ):        # a share of it
if p := test( "on the card", gpus = 1 ):
```

`cpus`, `ram` and `gpus` are counted against what the host has. This is what the
[queue](./machine) enforces, and what a [`Slurm`](./remote) layer hands over to the scheduler when
there is one.

## Tags on an entry

Entries carry free-form tags, and `--entry-tags` / `-e` filters on them with the
[expression language](/reference/expressions):

```python
if test( "the slow one", tags = [ "slow", "gpu" ] ):
    ...
```

```bash
errand -e 'slow & !gpu'
```

`-e` picks *what* runs; `-t` picks *where* (see [Tags](./tags)). They take the same expressions.

::: tip Entry tags and environment tags are different things
An entry tag is a word you wrote on the work. An environment tag says what a *place* is. They never
mix, and they have one flag each so you can always tell which you meant.
:::

## Two rules about files

**A file that declares work is not a module to import from.** Importing one from another declares
everything in it twice, and errand says so rather than running the copies; put what is shared in a
file that declares nothing.

**Its own directory is on the import path while it is read**, so `test_primes.py` can
`import primes` from beside it. Work is declared next to the code it exercises; which directory you
happened to start `errand` from is not supposed to change what a file can import. The path is
borrowed for the import and put back afterwards.

## Something that is not a test at all

There is no mechanism for project-specific subcommands, because there does not need to be one:
something you want to run is an entry, and `bulk = False` keeps it out of the way until you name it.

```python
if entry( "docs", bulk = False ):
    build_docs( )
```

```bash
errand docs
```

## Next

[Running it](./running) — how to ask for one entry, a file, a glob, or everything.
