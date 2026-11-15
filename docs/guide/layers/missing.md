# Missing

An environment that cannot be reached from this machine, declared anyway so that it says why.

```python
errand.envs[ "mylib-macos" ] = errand.Env( [
    errand.Missing( "a Mac reachable by ssh", hint = "name one in mylib-hosts.py ( `mac = Ssh( host = ... )` )" ),
] )
```

It is what a [package that provides environments](../environments#environments-a-package-provides)
declares rather than nothing when the machine errand starts on has no way to the place: a host nobody
named, a tool that is not installed. Declaring nothing would leave the user with
`no environment named mylib-macos`; this says what is lacking ( `what` ) and what to write where ( `hint` ).

```bash
errand envs
```

```text
  mylib-linux   cuda            apptainer:mylib.sif -> vars
  mylib-macos                   missing: a Mac reachable by ssh                 unreachable
```

Asked for by name ( `--env mylib-macos`, `errand setup mylib-macos` ), it stops the command before
anything is pushed, built or run — with every other unreachable environment of the command, at
once:

```text
mylib-macos: needs a Mac reachable by ssh
  name one in mylib-hosts.py ( `mac = Ssh( host = ... )` )
```

Chosen by tag ( `--cuda`, `-t 'driver=jax'` ), an unreachable environment is only left out, unless
it is all that was chosen.

## What a layer requires of its place

`Missing` is for what can be told from here. What can only be told over there — whether
`apptainer` is installed on the machine an `Ssh` leads to — is a layer's `requires( ctx )`:
`[ ( shell test, what is lacking ) ]`, checked at the place, one shell line for all the layers that
run there, before anything is built. A test that fails stops the command:

```text
  box: on build-box: apptainer, not found ( apptainer:mylib.sif )
```

`Apptainer` requires its executable ( `exe` ); `Docker` and `Podman` their engine, and that it
answers ( `docker info` ). The [`Windows`](./windows) layer says what the machine that boots it lacks
on its own: QEMU, KVM, rsync.
