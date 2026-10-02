<script setup>
// A terminal that plays one of the scenes in scenes.js, and stays still if asked to.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { scenes } from './scenes.js'

const props = defineProps( { scene: { type: String, required: true }, caption: { type: String, default: '' } } )

const scene = scenes[ props.scene ]()
const at = ref( scene.frames.length - 1 )         // the last frame is the still one: no script, no motion
const playing = ref( false )
const root = ref( null )
let timer = null, seen = null, reduced = false

const html = computed( () => scene.frames[ at.value ].html )

function step() {
  at.value = ( at.value + 1 ) % scene.frames.length
  timer = setTimeout( step, scene.frames[ at.value ].ms )
}
function play() {
  if ( playing.value ) return
  playing.value = true
  at.value = 0
  timer = setTimeout( step, scene.frames[ 0 ].ms )
}
function pause() {
  playing.value = false
  clearTimeout( timer )
}
function toggle() { playing.value ? pause() : play() }
function replay() { pause(); play() }

onMounted( () => {
  reduced = window.matchMedia && window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches
  if ( reduced || !( 'IntersectionObserver' in window ) ) return
  let heard = false
  seen = new IntersectionObserver( ( [ e ] ) => { heard = true; e.isIntersecting ? play() : pause() }, { threshold: 0.4 } )
  seen.observe( root.value )
  // A view that never reports visibility ( a hidden pane, an embedded preview ) would otherwise
  // leave the recording still for ever; playing is the harmless way to be wrong.
  setTimeout( () => { if ( !heard ) play() }, 900 )
} )
onBeforeUnmount( () => { pause(); seen && seen.disconnect() } )
</script>

<template>
  <figure ref="root" class="term">
    <div class="term-bar">
      <span class="dots"><i /><i /><i /></span>
      <span class="term-title">{{ scene.title }}</span>
      <span class="term-ctl">
        <button type="button" :aria-label="playing ? 'Pause the recording' : 'Play the recording'" @click="toggle">{{ playing ? '❚❚' : '▶' }}</button>
        <button type="button" aria-label="Replay from the start" @click="replay">↺</button>
      </span>
    </div>
    <pre class="term-screen" :style="{ minWidth: scene.cols + 'ch', minHeight: scene.rows * 1.35 + 'em' }" v-html="html" aria-hidden="true"></pre>
    <figcaption v-if="caption">{{ caption }}</figcaption>
  </figure>
</template>
