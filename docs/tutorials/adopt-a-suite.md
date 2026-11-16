---
search: false
sidebar: false
aside: false
---

# Adopt an existing suite

This page moved: [Adopting a suite](/guide/runners/adopting).

<script setup>
import { onMounted } from 'vue'
import { withBase } from 'vitepress'
// the old anchors, to where each one went
const moved = {
  "the-three-lines": "/guide/runners/adopting#the-three-lines",
  "try-it": "/guide/runners/adopting#running-it",
  "what-adopting-them-buys": "/guide/runners/#what-adopting-them-buys",
  "guessing-and-writing-the-guess-down": "/guide/runners/adopting#letting-errand-write-the-lines",
  "compiling-and-finding-the-binary": "/guide/runners/adopting#building-and-finding-the-binary",
  "what-to-notice": "/guide/runners/adopting#what-to-notice"
}
onMounted( () => {
  const to = moved[ decodeURIComponent( location.hash.slice( 1 ) ) ] || "/guide/runners/adopting"
  location.replace( withBase( to ) )
} )
</script>
