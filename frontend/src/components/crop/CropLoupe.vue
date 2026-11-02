<script setup lang="ts">
import { computed, onBeforeUnmount, useTemplateRef, watch } from 'vue'

import { useCropStore } from '@/stores/crop'
import { usePreviewStore } from '@/stores/preview'
import { useUiStore } from '@/stores/ui'

import { useFrameBitmap } from './frames'
import { drawView, LOUPE_SIZE, loupeView, NO_CROP, prepareCanvas, viewLayout } from './magnifier'

/** The source pixels under the pointer, magnified, in manual crop on the Dimensions tab. */
const preview = usePreviewStore()
const crop = useCropStore()
const ui = useUiStore()

const active = computed(() => ui.activeTab === 'dimensions' && crop.editable)
const { bitmap } = useFrameBitmap(() => (active.value ? preview.current : null))
const canvas = useTemplateRef<HTMLCanvasElement>('canvas')

const position = computed(() => {
  const point = preview.pointer
  const size = crop.sourceSize
  if (point === null || size === null || bitmap.value === null) return null
  return {
    left: `${(point.x / size.width) * 100}%`,
    top: `${(point.y / size.height) * 100}%`,
  }
})

function draw(): void {
  const point = preview.pointer
  const size = crop.sourceSize
  const image = bitmap.value
  if (canvas.value === null || point === null || size === null || image === null) return
  const view = loupeView(point)
  const layout = viewLayout(view, crop.rect ?? NO_CROP, size)
  drawView(
    prepareCanvas(canvas.value, layout.width, layout.height),
    image,
    layout,
    view.zoom,
    false,
  )
}

// Pointer events come faster than the screen shows them: draw once per frame, the last position.
let pending = 0
function schedule(): void {
  if (pending !== 0) return
  pending = requestAnimationFrame(() => {
    pending = 0
    draw()
  })
}

watch([position, () => crop.rect], schedule, { flush: 'post' })
onBeforeUnmount(() => cancelAnimationFrame(pending))
</script>

<template>
  <div
    v-if="position !== null"
    class="crop-loupe"
    :style="position"
    aria-hidden="true"
    data-crop-loupe
  >
    <canvas
      ref="canvas"
      class="crop-loupe__canvas"
      :style="{ width: `${LOUPE_SIZE}px`, height: `${LOUPE_SIZE}px` }"
    />
  </div>
</template>

<style scoped>
.crop-loupe {
  position: absolute;
  overflow: hidden;
  border: 2px solid #fff;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgb(0 0 0 / 0.6);
  background: #000;
  transform: translate(-50%, -50%);
  pointer-events: none;
}

.crop-loupe__canvas {
  display: block;
}
</style>
