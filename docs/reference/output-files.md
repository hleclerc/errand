---
search: false
sidebar: false
aside: false
---

# Output files

This page moved: [Where the output goes](/guide/output).

<script setup>
import { onMounted } from 'vue'
import { withBase } from 'vitepress'
// the old anchors, to where each one went
const moved = {
  "result-yaml": "/guide/output#what-lands-in-a-run-directory",
  "output-txt": "/guide/output#what-lands-in-a-run-directory",
  "summary-yaml": "/guide/output#summaries",
  "latest": "/guide/output#the-three-parts-of-a-run-s-name",
  "what-else-is-on-disk": "/guide/output#what-else-is-on-disk",
  "writing-your-own-files": "/guide/output#what-lands-in-a-run-directory"
}
onMounted( () => {
  const to = moved[ decodeURIComponent( location.hash.slice( 1 ) ) ] || "/guide/output"
  location.replace( withBase( to ) )
} )
</script>
