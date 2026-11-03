---
search: false
sidebar: false
aside: false
---

# Runners

This page moved: [Runners](/guide/runners/).

<script setup>
import { onMounted } from 'vue'
import { withBase } from 'vitepress'
// the old anchors, to where each one went
const moved = {
  "pytest": "/guide/runners/pytest",
  "catch2": "/guide/runners/catch2",
  "cargo": "/guide/runners/cargo",
  "python-executable": "/guide/runners/scripts",
  "writing-one": "/guide/runners/writing",
  "still-to-ship": "/guide/runners/writing#still-to-ship"
}
onMounted( () => {
  const to = moved[ decodeURIComponent( location.hash.slice( 1 ) ) ] || "/guide/runners/"
  location.replace( withBase( to ) )
} )
</script>
