---
search: false
sidebar: false
aside: false
---

# Running elsewhere

This page moved: [Ssh: running elsewhere](/guide/layers/ssh).

<script setup>
import { onMounted } from 'vue'
import { withBase } from 'vitepress'
// the old anchors, to where each one went
const moved = {
  "the-paths-are-computed-before-the-run-happens": "/guide/layers/ssh#the-paths-are-computed-before-the-run-happens",
  "through-an-interactive-shell": "/guide/layers/ssh#through-an-interactive-shell",
  "options-go-to-ssh-and-to-rsync": "/guide/layers/ssh#options-go-to-ssh-and-to-rsync",
  "what-gets-pushed": "/guide/layers/ssh#what-gets-pushed",
  "building-over-there": "/guide/layers/ssh#building-over-there",
  "adding-an-allocation": "/guide/layers/ssh#adding-an-allocation",
  "results-are-pulled-not-pushed": "/guide/layers/ssh#results-are-pulled-not-pushed",
  "what-only-this-machine-can-supply": "/guide/layers/ssh#what-only-this-machine-can-supply"
}
onMounted( () => {
  const to = moved[ decodeURIComponent( location.hash.slice( 1 ) ) ] || "/guide/layers/ssh"
  location.replace( withBase( to ) )
} )
</script>
