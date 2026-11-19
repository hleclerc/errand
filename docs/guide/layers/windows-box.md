# WindowsBox

```python
WindowsBox( python = None, msvc = False, provision = [ ], fetch = [ ], also = [ ], root = None )
```

**Right after the `Ssh` that reaches a Windows machine.** A Windows that is already there, such as a
workstation or a build server with Windows' OpenSSH server. The `Ssh` says how to get there (host,
options, a jump host). The `WindowsBox` says what is there, as [`Windows`](./windows) does for a
machine errand boots:

```python
errand.envs[ "win" ] = errand.Env( [ errand.Ssh( host = "me@winbox" ), errand.WindowsBox() ] )
```

```bash
errand setup --env win          # once: a Python, the provisioning
errand run --env win tests/     # then: everything after it runs on Windows
```

Everything after the `WindowsBox` runs on Windows, the way it runs in errand's own virtual machine:

- each command is a cmd.exe line;
- the project is synced in, through an errand agent there, and kept between commands;
- an agent there runs the sessions;
- `fetch` and `--pull` bring results back.

| | |
|---|---|
| `python` | `None`: the Python the machine has (`py -3`, else `python`). `"3.13.1"`: that one, installed by uv into `C:\errand` |
| `msvc` | `vcvars64` before every command; the Build Tools must be there |
| `provision` | more to install, by `errand setup`: a `.ps1` of the project, or a line of PowerShell |
| `fetch` | paths of the project brought back after each command |
| `also` | sibling checkouts the work needs (`../loom`), copied in beside the project |
| `root` | where the project goes; `C:/errand/work/<project name>` |

**What errand puts on the machine** is all in `C:\errand`. Nothing goes on its `PATH` or in its
registry, so deleting that directory undoes everything:

| | |
|---|---|
| `C:\errand\uv`, `uv-python` | uv and the Python it installs, for a `python = "3.13.1"` |
| `C:\errand\venv` | a venv of that Python. The commands and the provisioning run with it, so the machine's own Python is never written to |
| `C:\errand\src` | errand's own sources, as on any machine errand reaches |
| `C:\errand\ready` | one file per declaration set up |
| `C:\errand\work` | the projects' copies |

**Setting up is `errand setup`'s, never a run's.** A run on a box that is not set up for its current
declaration stops before anything else and gives the command that sets it up. A changed `python`,
`msvc` or `provision` (a `.ps1` is fingerprinted by its content) means setting it up again. The
record of it is kept here, under `errand-outputs/builds/records`, and named after the host.

**What the machine needs:**

- an OpenSSH server whose shell is cmd.exe, the default;
- `ssh <host> echo ok` working from this terminal;
- network access, if uv has a Python to download there.

This machine needs `ssh` and `scp`.

**An `Ssh` alone that reaches a Windows** is noticed on the first line errand sends. errand stops
there and says to add the `WindowsBox`, before anything is copied or created on that machine.

## errand started on Windows

errand also runs *on* Windows, with these layers:

- no layer, `Vars`, `Venv` and `Uv`, which run on Windows itself;
- an `Ssh` to a POSIX machine, followed by any layers that run there.

Its own local steps (records, a build's output, the agent) are done in Python, since there is no
`sh` to read them. Files cross through the agent over there, as from any other machine, and
Windows' own `ssh.exe` starts it: a key in Windows' ssh-agent, `~/.ssh/config` and the known hosts
all work as they do for `ssh` at the prompt.

The project goes to a POSIX path over there: `root`, or the project's place under the home folder,
kept under the remote one (`C:\Users\me\Projects\x` → `~/Projects/x`), else `~/errand-work/<name>`.
Links in a run's outputs (`latest`) are left over there, since Windows makes them only in developer
mode.

errand on Windows must run in a console (a terminal window). Under an ssh session into Windows,
which has none, Windows' `ssh.exe` hangs as soon as its output is a pipe.

A layer that needs a POSIX machine where it runs (`Micromamba`, a container, a scheduler, a module)
is refused before anything runs, with a message saying to put an `Ssh` to a POSIX machine before it.
A `WindowsBox` first in its stack, meaning this machine itself, is not supported yet.
