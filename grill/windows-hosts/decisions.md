# errand on Windows and ssh to native Windows: decisions

- **Shape**: `[ Ssh( host = "winbox" ), WindowsBox( python, msvc, provision, fetch, also, root ) ]`. `Ssh` says how to reach the host, `WindowsBox` what is there, as `[ Ssh( lmo ), Windows( cpus ) ]` for the VM. `WindowsBox` first means this machine, errand started on Windows. An `Ssh` alone that reaches a Windows is detected at first contact and says to add `WindowsBox()`.
- **What errand installs on a box**: everything in `C:\errand\` (rsync MSYS2, errand's sources, uv + python); nothing on the PATH or in the registry. `python = None` finds `py -3` / `python`; a version is installed by uv in errand's directory. `provision` only by `errand setup`, recorded on the machine (ADR 0004); `run` refuses while it is missing or stale. `msvc = False` by default.
- **Copies**: the pinned MSYS2 rsync now (both ends when errand runs on Windows); ADR 0006 removes it later.
- **errand started on Windows**: bare, `Vars`, `Venv`, `Uv` locally; `Ssh` to POSIX and what follows it; `WindowsBox`; agents over TCP + token. Layers needing a POSIX machine here are refused clearly. `Here.shell` lines on these paths rewritten in Python; a `sh` line left there raises naming it.
- **loom**: `Here()` on Windows = `[ Vars ]` + a `requires` for clang ( run `windows-tools.ps1` once ); a box is completed like the VM (python, provision via `errand setup`, tools path, `LOOM_CACHE_DIR` in errand's directory); template gets the box as a commented alternative; the `Missing` for these go.
- **Tests**: unit tests on the Mac; real ones with lmo's Windows VM used as a native box over `-J lmo`, and errand started inside the guest; the VM may be started on lmo when nothing else runs there.

## Settled while implementing (2026-11-14)
- **No sh on the box**: errand's own steps there are cmd.exe lines, scp and PowerShell (`-EncodedCommand`); a pinned busybox was dropped (a third-party exe to run on someone's machine).
- **A venv in `C:\errand\venv`**: made from the found or uv Python; commands and provisioning run with it (uv's Pythons are externally managed, and a machine's own Python is never written to). loom's pip line and `SSL_CERT_FILE` point into it.
- **Records here**: the box's setup record is kept in the project's `errand-outputs/builds/records` here, named after the host; the truth is a `C:\errand\ready\<fingerprint>` file on the box, which `probe` and every run check.
- **`setup_only`**: `errand run` never installs on a box (it stops and names `errand setup --env …`); only `errand setup` does.
- **PATH in one cmd.exe line**: the venv goes inside the command's own `PATH` (cmd.exe expands every `%PATH%` of a line before running it).
- **Not done**: `WindowsBox` first ( this Windows itself ) — refused with a message; `Ssh` from Windows to a POSIX machine is written (MSYS2 rsync locally, `/c/...` paths) but not run for real.
- **Ssh from Windows to POSIX** (run 2026-11-14, from lmo's Windows VM to lmo): MSYS2's rsync needs MSYS2's ssh as `-e` (Windows' `ssh.exe` reads MSYS2's pipes as closed); seven more pinned packages (openssh, heimdal-libs, OpenSSL 4, …), unpacked with Windows' bsdtar. errand's other ssh calls keep Windows' `ssh.exe` (its agent). MSYS2's home is the Windows profile (`db_home: windows`).
- **Remote root from Windows**: POSIX, absolute: `root`, else the place under the home folder kept under the remote home, else `~/errand-work/<name>`; the remote `$HOME` asked once per host. `L.remote_path` keeps paths of the other machine POSIX (Context/Over/driver).
- **Pulls on Windows**: `--no-links` (a run's `latest` link needs developer mode).
- **Console needed**: under a console-less ssh session into Windows, `ssh.exe` hangs when its stdout is a pipe; fine in a terminal.
