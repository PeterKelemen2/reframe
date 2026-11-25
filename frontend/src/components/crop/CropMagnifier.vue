<script setup lang="ts">
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import { useElementSize } from '@vueuse/core'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import SelectButton from 'primevue/selectbutton'
import { computed, onBeforeUnmount, ref, shallowRef, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { formatTime } from '@/components/chapters/chapters'
import { type Edge, EDGES, NO_CROP } from '@/components/dimensions/grid'
import { useCropStore } from '@/stores/crop'
import { usePreviewStore } from '@/stores/preview'
import { useUiStore } from '@/stores/ui'

import CropCheckGrid from './CropCheckGrid.vue'
import { useFrameBitmap } from './frames'
import {
  drawView,
  fittedLength,
  isHorizontal,
  type MagnifierZoom,
  prepareCanvas,
  STRIP_LENGTH,
  stripRange,
  stripView,
  viewLayout,
  ZOOMS,
} from './magnifier'

const { t } = useI18n()
const preview = usePreviewStore()
const crop = useCropStore()
const ui = useUiStore()
const id = useId()

const zoom = ref<MagnifierZoom>(4)
const grid = ref(false)
const zoomOptions = computed(() =>
  ZOOMS.map((value) => ({ value, label: t('crop.magnifier.zoomFactor', { zoom: value }) })),
)

const { bitmap, failed } = useFrameBitmap(() => preview.current)
const rect = computed(() => crop.rect ?? NO_CROP)

// The top and bottom strips are as long as their column is wide, less the canvas border.
const topFigure = shallowRef<HTMLElement | null>(null)
const { width: room } = useElementSize(topFigure)
const horizontalLength = computed(() => fittedLength(room.value - 2))

function lengthOf(edge: Edge): number {
  return isHorizontal(edge) ? horizontalLength.value : STRIP_LENGTH
}

const strips = computed(() => {
  const size = crop.sourceSize
  if (size === null) return []
  return EDGES.map((edge) => {
    const view = stripView(edge, rect.value, size, zoom.value, null, lengthOf(edge))
    const [first, last] = stripRange(edge, view, size)
    const range = t(isHorizontal(edge) ? 'crop.magnifier.rows' : 'crop.magnifier.columns', {
      first,
      last,
    })
    return {
      edge,
      range,
      width: view.box.width * zoom.value,
      height: view.box.height * zoom.value,
    }
  })
})

const frameLabel = computed(() => {
  const index = preview.index
  if (index !== null) {
    return t('crop.magnifier.frame', { n: index + 1, count: preview.strip.length })
  }
  const current = preview.current
  return current === null
    ? ''
    : t('crop.magnifier.frameAt', { time: formatTime(current.timestamp) })
})

const atStart = computed(() => preview.strip.length === 0 || preview.index === 0)
const atEnd = computed(
  () => preview.strip.length === 0 || preview.index === preview.strip.length - 1,
)

const canvases: Partial<Record<Edge, HTMLCanvasElement>> = {}

function keep(edge: Edge, element: unknown): void {
  if (element instanceof HTMLCanvasElement) canvases[edge] = element
  else delete canvases[edge]
}

function keepFigure(edge: Edge, element: unknown): void {
  if (edge === 'top') topFigure.value = element instanceof HTMLElement ? element : null
}

function draw(): void {
  const image = bitmap.value
  const size = crop.sourceSize
  if (image === null || size === null) return
  const pointer = preview.pointer
  for (const edge of EDGES) {
    const canvas = canvases[edge]
    if (canvas === undefined) continue
    // Along the line the strip follows the pointer over the panel's picture.
    const centre = pointer === null ? null : isHorizontal(edge) ? pointer.x : pointer.y
    const view = stripView(edge, rect.value, size, zoom.value, centre, lengthOf(edge))
    const layout = viewLayout(view, rect.value, size)
    drawView(
      prepareCanvas(canvas, layout.width, layout.height),
      image,
      layout,
      zoom.value,
      grid.value,
    )
  }
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

watch(
  [bitmap, rect, () => crop.sourceSize, zoom, grid, () => preview.pointer, horizontalLength],
  schedule,
  { flush: 'post' },
)
onBeforeUnmount(() => {
  cancelAnimationFrame(pending)
  // A check left open would come back with the magnifier, unasked.
  ui.cropCheckOpen = false
})
</script>

<template>
  <section class="crop-magnifier" :aria-labelledby="`${id}-title`" data-crop-magnifier>
    <header class="crop-magnifier__controls">
      <h3 :id="`${id}-title`" class="crop-magnifier__title">{{ t('crop.magnifier.title') }}</h3>
      <SelectButton
        v-model="zoom"
        :options="zoomOptions"
        option-label="label"
        option-value="value"
        :allow-empty="false"
        :pt="{ root: { 'aria-label': t('crop.magnifier.zoom') } }"
        data-field="magnifier-zoom"
      />
      <div class="crop-magnifier__grid">
        <Checkbox v-model="grid" binary :input-id="`${id}-grid`" data-field="magnifier-grid" />
        <label :for="`${id}-grid`">{{ t('crop.magnifier.grid') }}</label>
      </div>
    </header>
    <p v-if="failed" class="crop-magnifier__state" role="alert">
      {{ t('crop.magnifier.failed') }}
    </p>
    <p v-else-if="bitmap === null" class="crop-magnifier__state">
      {{ t('crop.magnifier.loading') }}
    </p>
    <div class="crop-magnifier__strips">
      <figure
        v-for="strip in strips"
        :key="strip.edge"
        :ref="(element) => keepFigure(strip.edge, element)"
        class="crop-magnifier__strip"
        :class="`crop-magnifier__strip--${strip.edge}`"
        :data-edge="strip.edge"
      >
        <figcaption class="crop-magnifier__caption">
          <span>{{ t(`crop.magnifier.edge.${strip.edge}`) }}</span>
          <span class="crop-magnifier__range" data-range>{{ strip.range }}</span>
        </figcaption>
        <canvas
          :ref="(element) => keep(strip.edge, element)"
          class="crop-magnifier__canvas"
          role="img"
          :aria-label="
            t('crop.magnifier.strip', {
              edge: t(`crop.magnifier.edge.${strip.edge}`),
              zoom,
              range: strip.range,
            })
          "
          :style="{ width: `${strip.width}px`, height: `${strip.height}px` }"
        />
      </figure>
    </div>
    <nav class="crop-magnifier__frames" :aria-label="t('crop.magnifier.frames')">
      <!-- Not `disabled`: a button disabled under the focus drops it to the page. The store
           does not step past the ends. -->
      <Button
        severity="secondary"
        outlined
        size="small"
        class="crop-magnifier__step"
        :aria-label="t('crop.magnifier.previous')"
        :aria-disabled="atStart || undefined"
        data-action="frame-previous"
        @click="preview.step(-1)"
      >
        <ChevronLeft :size="16" aria-hidden="true" />
      </Button>
      <span class="crop-magnifier__frame" aria-live="polite" data-frame-label>{{
        frameLabel
      }}</span>
      <Button
        severity="secondary"
        outlined
        size="small"
        class="crop-magnifier__step"
        :aria-label="t('crop.magnifier.next')"
        :aria-disabled="atEnd || undefined"
        data-action="frame-next"
        @click="preview.step(1)"
      >
        <ChevronRight :size="16" aria-hidden="true" />
      </Button>
      <Button
        size="small"
        :label="t('crop.magnifier.check')"
        :disabled="preview.strip.length === 0"
        data-action="check-crop"
        @click="ui.cropCheckOpen = true"
      />
    </nav>
    <CropCheckGrid v-model:visible="ui.cropCheckOpen" />
  </section>
</template>

<style scoped>
.crop-magnifier {
  display: grid;
  gap: var(--rf-space-3);
  container-type: inline-size;
}

.crop-magnifier__controls,
.crop-magnifier__frames,
.crop-magnifier__grid {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-3);
}

.crop-magnifier__grid {
  gap: var(--rf-space-2);
}

.crop-magnifier__title {
  margin: 0;
  font-size: var(--rf-font-size-md);
  font-weight: var(--rf-font-weight-medium);
}

.crop-magnifier__state {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.crop-magnifier__strips {
  display: grid;
  grid-template-areas:
    'top left right'
    'bottom left right'
    '. left right';
  grid-template-rows: auto auto 1fr;
  grid-template-columns: minmax(0, 1fr) max-content max-content;
  align-items: start;
  gap: var(--rf-space-3) var(--rf-space-4);
}

/* Beside the side strips the top and bottom ones would be too short to show much: they take
   the whole width, and the side strips go below them, side by side when they fit. */
@container (width < 31rem) {
  .crop-magnifier__strips {
    display: flex;
    flex-wrap: wrap;
  }

  .crop-magnifier__strip--top,
  .crop-magnifier__strip--bottom {
    flex-basis: 100%;
  }
}

.crop-magnifier__strip {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
}

.crop-magnifier__strip--top {
  grid-area: top;
}

.crop-magnifier__strip--bottom {
  grid-area: bottom;
}

.crop-magnifier__strip--left {
  grid-area: left;
}

.crop-magnifier__strip--right {
  grid-area: right;
}

.crop-magnifier__caption {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0 var(--rf-space-2);
  font-size: var(--rf-font-size-sm);
}

.crop-magnifier__strip--left .crop-magnifier__caption,
.crop-magnifier__strip--right .crop-magnifier__caption {
  flex-direction: column;
}

.crop-magnifier__range {
  color: var(--rf-color-text-muted);
  font-variant-numeric: tabular-nums;
}

/* The border goes outside the drawing: inside it, the canvas would be scaled down and smoothed. */
.crop-magnifier__canvas {
  display: block;
  /* A canvas the page scales (a fractional device pixel ratio) keeps its pixels square. */
  image-rendering: pixelated;
  box-sizing: content-box;
  border: 1px solid var(--rf-color-border);
  background: var(--rf-color-surface);
}

/* It keeps the focus at an end of the frames: the icon and the border fade, not the focus ring. */
.crop-magnifier__step[aria-disabled='true'] {
  border-color: color-mix(
    in srgb,
    var(--p-button-outlined-secondary-border-color) calc(var(--p-disabled-opacity) * 100%),
    transparent
  );
  pointer-events: none;
}

.crop-magnifier__step[aria-disabled='true'] > * {
  opacity: var(--p-disabled-opacity);
}

.crop-magnifier__frame {
  min-width: 7rem;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
</style>
