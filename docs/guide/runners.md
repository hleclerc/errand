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
  "scripts-and-executables": "/guide/runners/scripts",
  "writing-one-for-something-else": "/guide/runners/writing",
  "a-missing-tool-is-installed-when-the-environment-is-errand-s": "/guide/runners/pytest#a-missing-pytest-is-installed-when-the-environment-is-errand-s",
  "which-runner-takes-a-file": "/guide/runners/#which-runner-takes-a-file",
  "the-list-is-yours": "/guide/runners/#the-list-is-yours",
  "what-adopting-them-buys": "/guide/runners/#what-adopting-them-buys",
  "a-vocabulary-translated-not-replaced": "/guide/runners/#a-vocabulary-translated-not-replaced",
  "guessing-and-writing-the-guess-down": "/guide/runners/#guessing-and-writing-the-guess-down",
  "errand-compiles-nothing-itself": "/guide/runners/#errand-compiles-nothing-itself",
  "why-the-three-suites-behave-differently": "/guide/runners/#why-the-three-suites-behave-differently"
}
onMounted( () => {
  const to = moved[ decodeURIComponent( location.hash.slice( 1 ) ) ] || "/guide/runners/"
  location.replace( withBase( to ) )
} )
</script>
