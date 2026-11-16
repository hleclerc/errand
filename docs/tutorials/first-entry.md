---
search: false
sidebar: false
aside: false
---

# errand's own entries

This page moved: [Writing entries](/guide/declaring-work).

<script setup>
import { onMounted } from 'vue'
import { withBase } from 'vitepress'
// the old anchors, to where each one went
const moved = {
  "the-code-knows-nothing-about-this": "/guide/declaring-work",
  "the-work": "/guide/declaring-work#the-guard-is-the-entry",
  "it-must-pass": "/guide/declaring-work#test-bench-track-experiment",
  "numbers-to-follow": "/guide/declaring-work#test-bench-track-experiment",
  "it-must-be-looked-at": "/guide/declaring-work#test-bench-track-experiment",
  "try-it": "/guide/declaring-work",
  "what-you-get-back": "/guide/declaring-work#what-a-run-leaves",
  "what-to-notice": "/guide/declaring-work"
}
onMounted( () => {
  const to = moved[ decodeURIComponent( location.hash.slice( 1 ) ) ] || "/guide/declaring-work"
  location.replace( withBase( to ) )
} )
</script>
