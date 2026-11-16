# Missing

```python
Missing( what, hint = None, when = None )
```

An environment this machine cannot reach, declared anyway so that it says why.

```python
errand.envs[ "mylib-macos" ] = errand.Env( [
    errand.Missing( "a Mac reachable by ssh", hint = "name one in errand-vars.py ( `mac_host = \"...\"` )" ),
] )
```

It is what a [package that provides environments](../environments#environments-a-package-provides)
declares, instead of nothing, when there is no way to the place from here: a host nobody named, a
tool that is not installed. Declaring nothing would leave the user with
`no environment named mylib-macos`. This says what is lacking ( `what` ) and what to write where
( `hint` ).

```bash
errand envs
```

```text
  mylib-linux   cuda   apptainer:mylib.sif
  mylib-macos          missing: a Mac reachable by ssh  unreachable
```

Asked for by name ( `--env mylib-macos`, `errand setup mylib-macos` ), it stops the command before
anything is pushed, built or run, together with every other unreachable environment of the command:

```text
mylib-macos: needs a Mac reachable by ssh
  name one in errand-vars.py ( `mac_host = "..."` )
```

Chosen by tag ( `--cuda`, `-t 'driver=jax'` ), an unreachable environment is only left out, unless
it is all that was chosen.

## What only the place can tell

`Missing` is for what can be told from here. Whether `apptainer` is installed on the machine an `Ssh`
leads to can only be told over there. Each layer says what it needs of its place in its
`requires( ctx )`: a list of `( shell test, what is lacking )`, checked there in one shell line for
all the layers that run there, before anything is built. A test that fails stops the command:

```text
  box: on build-box: apptainer, not found ( apptainer:mylib.sif )
```

`Apptainer` needs its executable; `Docker` and `Podman` their engine, and that it answers. The
[`Windows`](./windows) layer says what the machine that boots it lacks: QEMU, KVM, rsync.
