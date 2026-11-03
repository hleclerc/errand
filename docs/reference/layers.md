---
search: false
sidebar: false
aside: false
---

# Layers

This page moved: [Layers](/guide/layers/).

<script setup>
import { onMounted } from 'vue'
import { withBase } from 'vitepress'
// the old anchors, to where each one went
const moved = {
  "vars": "/guide/layers/vars",
  "interpreter-selecting-layers": "/guide/layers/",
  "venv": "/guide/layers/venv",
  "micromamba": "/guide/layers/micromamba",
  "conda": "/guide/layers/micromamba#conda",
  "uv": "/guide/layers/venv#uv",
  "nix": "/guide/layers/nix-guix",
  "guix": "/guide/layers/nix-guix#guix",
  "module": "/guide/layers/module",
  "container-layers": "/guide/layers/containers",
  "apptainer": "/guide/layers/containers#apptainer",
  "docker-podman": "/guide/layers/containers#docker-podman",
  "going-elsewhere": "/guide/layers/",
  "ssh": "/guide/layers/ssh",
  "slurm": "/guide/layers/slurm",
  "several-ranks": "/guide/layers/slurm#several-ranks",
  "waiting-from-afar-watch": "/guide/layers/slurm#waiting-from-afar-watch",
  "windows": "/guide/layers/windows",
  "other-batch-systems": "/guide/layers/slurm#inside-an-allocation-errand-does-not-queue",
  "several-processes": "/guide/layers/mpi",
  "mpi": "/guide/layers/mpi"
}
onMounted( () => {
  const to = moved[ decodeURIComponent( location.hash.slice( 1 ) ) ] || "/guide/layers/"
  location.replace( withBase( to ) )
} )
</script>
