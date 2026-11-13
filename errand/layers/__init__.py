"""Layers: how to get from "run this program" to the actual subprocess.

A stack reads outside-in -- `[ Ssh( … ), Apptainer( … ), Vars( … ) ]` is ssh
around apptainer around the command -- and is folded innermost-first. There is
always a current interpreter, and most layers are a way to override it.

A layer may do three things, and only the first is required:

    wrap( cmd, ctx )   rewrite the command    -- every layer
    probe/create       say whether it is there, and build it   -- Micromamba, …
    detach( … )        launch and let go, for `--batch`        -- Ssh, Slurm, …

`Vars` and the tags of an environment are deliberately different things: a tag
SELECTS an environment, a layer ACTS once it is chosen. Keeping them apart is
what lets `--grid=, --fp 32,64` mean two runs rather than one variable written twice.

One file per family:

    base          a command, its context, folding, fingerprints, `under`
    families      `Layer`, its families, and `Artefact`
    overlays      Vars, Module, Nix, Guix
    launchers     Mpi, Preload
    interpreters  Venv, Micromamba, Conda, Uv
    containers    Apptainer, Docker, Podman
    schedulers    Slurm, and waiting for a job
    gateways      Ssh, push and fetch
    hosts         Here and Over: where a layer's own work runs
    stacks        questions about a whole stack
"""
from __future__ import annotations

from .base import _how, _install_steps, _quiet, Command, compose, Context, file_stamp, fingerprint, Here, INTERPRETERS, sh, SITE_STAMP, under
from .families import Artefact, batch_of, Container, Gateway, Interpreter, is_scheduler, Launcher, Layer, Overlay, Scheduler
from .overlays import Guix, Module, Nix, Vars
from .launchers import Mpi, Preload, preload_of
from .interpreters import Conda, fetch_micromamba, Micromamba, MICROMAMBA_URL, Uv, Venv
from .containers import _BuiltElsewhere, Apptainer, Docker, Podman, relay, replace_line
from .schedulers import run_on, Slurm, slurm_seconds, watch_dir, watch_job
from .gateways import _remote, _rsh, fetch, own_paths, push, RSYNC_EXCLUDES, Ssh, ssh_options, Unreachable
from .hosts import _NO_AGENT, host_of, Over
from .stacks import chooses_python, container_of, interpreters_of, mpi_of, NODE_LOCAL, ssh_of, vm_of, warnings_for


__all__ = [
    'Command',
    'Context',
    'Layer',
    'Overlay',
    'Launcher',
    'Interpreter',
    'Container',
    'Scheduler',
    'Gateway',
    'Artefact',
    'compose',
    'fingerprint',
    'sh',
    'file_stamp',
    'SITE_STAMP',
    'INTERPRETERS',
    'under',
    'Vars',
    'Preload',
    'preload_of',
    'Venv',
    'Micromamba',
    'MICROMAMBA_URL',
    'fetch_micromamba',
    'Conda',
    'Uv',
    'Apptainer',
    '_BuiltElsewhere',
    'replace_line',
    'relay',
    'Docker',
    'Podman',
    'Nix',
    'Guix',
    'Module',
    'Mpi',
    'Slurm',
    'RSYNC_EXCLUDES',
    'own_paths',
    'Ssh',
    '_rsh',
    '_remote',
    'push',
    'fetch',
    '_how',
    'Here',
    'Over',
    '_NO_AGENT',
    'host_of',
    '_install_steps',
    '_quiet',
    'NODE_LOCAL',
    'is_scheduler',
    'batch_of',
    'slurm_seconds',
    'watch_dir',
    'run_on',
    'watch_job',
    'warnings_for',
    'container_of',
    'interpreters_of',
    'chooses_python',
    'mpi_of',
    'ssh_of',
    'vm_of',
]
