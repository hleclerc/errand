# Windows

```python
Windows( iso = None, key = None, index = 1, cpus = 4, ram = "8G", disk = "64G",
         msvc = True, python = None, provision = [ ], fetch = [ ], keep = "0", data = "32G", root = None )
```

**First, or right after the `Ssh` of the machine that boots it.** A Windows virtual machine under
QEMU, which errand installs, boots, reaches over ssh and stops. Everything is optional:

```python
errand.envs[ "win" ] = errand.Env( [ errand.Windows( fetch = [ "build" ] ) ] )
```

```bash
errand setup --env win                         # the install: once, 20 to 60 minutes
errand run --env win cmake -B build -G Ninja   # then: commands, through cmd.exe
errand run --env win cmake --build build
errand vm stop                                 # let go of it now, whoever still holds it
```

With no `iso` and no `key` it is **Windows Server 2025, evaluation edition**: downloaded from
Microsoft, no licence needed for 180 days, and reinstalled by errand before it runs out. Server Core
by default — no desktop, which nothing run over ssh needs. `msvc` puts the Visual Studio build tools
in it (cl, link, msbuild, cmake, ninja) and calls `vcvars64` before every command.

| | |
|---|---|
| `iso`, `key`, `index` | another Windows: a path or a URL, its product key, which image of the ISO |
| `cpus`, `ram` | the size of the machine — how it is *booted*, so changing it reinstalls nothing |
| `python` | a python.org release, `"3.13.1"`, installed and on `PATH` |
| `provision` | more to install: a `.ps1` of the project, or a line of PowerShell |
| `fetch` | paths of the project brought back after each command — `build`, `dist` |
| `keep` | how long it stays up once no errand process holds it any more — `"15m"` to keep it warm between commands |
| `data` | a disk kept from one boot to the next, as `E:`, where the project lands — so a build is there for the next command. Grows up to this size; `None`: everything on `C:`, reset at each boot |
| `root` | where the project goes over there; `E:/<project name>`, or `C:/errand/<project name>` without `data` |

What it costs, and when:

- **The install** is a build like any other layer's: `errand setup` does it, a changed declaration redoes
  it, `--dry-run` says it would. The disk image goes to `~/.cache/errand/windows/`, named by what it
  was installed from, so projects declaring the same Windows share one.
- **A boot** starts from a fresh copy-on-write layer over that image — nothing a run left behind
  survives a restart — and the machine then stays up while an errand process that used it is
  alive, then `keep` more (none by default: a boot is about half a minute). All that time
  it holds its cores and memory, so it holds them **in the queue**, and shows in `errand queue`.
- **A command** costs an rsync of the project in — what changed since the last command, onto `E:`;
  all of it with `data = None` — and a tar of `fetch` out. Nothing is deleted over there: a file
  removed from the project stays on `E:` until the disk goes. Commands on one machine take turns.

The rsync of the guest is MSYS2's, pinned and put in the image by the install; the machine that runs
QEMU downloads it, and unpacks it with `zstd`. It needs `qemu-system-x86_64`, `qemu-img`, `rsync`
and `zstd`, and an **x86-64 host**: KVM on Linux, HVF on an Intel
Mac. Without hardware virtualization it works, in hours. When QEMU is missing, or `/dev/kvm` is there
but not yours (the usual case over ssh), errand says which command fixes it on that machine.

Apple Silicon cannot boot it, but can reach a machine that does — an `Ssh` in front:

```python
errand.envs[ "win" ] = errand.Env( [ errand.Ssh( host = "x86-box", root = "/home/me/proj" ),
                                     errand.Windows( fetch = [ "build" ] ) ] )
```

The layer does its own work through the machine `Ssh` leads to — `ctx.host`, a way to run a shell
line over there and read its answer — and decides everything here: nothing of errand runs over
there. The disks and the guest's key live in that machine's cache; the state, the locks and the
keeper live on this one, so `errand vm stop` stops those machines too. The queue counts a machine
only when it runs here.
`ERRAND_VM_VNC=1` shows the screen on `vnc://127.0.0.1:5901`, for watching an install go wrong.

Not yet: entries ( `errand run --env win` with a `::` target ) and `--batch` — errand itself is a unix
program. A command is what a virtual machine takes for now.
