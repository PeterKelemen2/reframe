<script setup lang="ts">
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import SelectButton from 'primevue/selectbutton'
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { formatTime } from '@/components/chapters/chapters'
import { useCropStore } from '@/stores/crop'
import { usePreviewStore } from '@/stores/preview'

import CropCheckGrid from './CropCheckGrid.vue'
import { useFrameBitmap } from './frames'
import {
  drawView,
  type Edge,
  EDGES,
  type MagnifierZoom,
  NO_CROP,
  prepareCanvas,
  stripRange,
  stripView,
  viewLayout,
  ZOOMS,
} from './magnifier'

const { t } = useI18n()
const preview = usePreviewStore()
const crop = useCropStore()
const id = useId()

const zoom = ref<MagnifierZoom>(4)
const grid = ref(false)
const checking = ref(false)
const zoomOptions = computed(() =>
  ZOOMS.map((value) => ({ value, label: t('crop.magnifier.zoomFactor', { zoom: value }) })),
)

const { bitmap, failed } = useFrameBitmap(() => preview.current)
const rect = computed(() => crop.rect ?? NO_CROP)

const strips = computed(() => {
  const size = crop.sourceSize
  if (size === null) return []
  return EDGES.map((edge) => {
    const view = stripView(edge, rect.value, size, zoom.value, null)
    const [first, last] = stripRange(edge, view, size)
    const range = t(
      edge === 'top' || edge === 'bottom' ? 'crop.magnifier.rows' : 'crop.magnifier.columns',
      { first, last },
    )
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

const canvases: Partial<Record<Edge, HTMLCanvasElement>> = {}

function keep(edge: Edge, element: unknown): void {
  if (element instanceof HTMLCanvasElement) canvases[edge] = element
  else delete canvases[edge]
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
    const centre =
      pointer === null ? null : edge === 'top' || edge === 'bottom' ? pointer.x : pointer.y
    const view = stripView(edge, rect.value, size, zoom.value, centre)
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

watch([bitmap, rect, () => crop.sourceSize, zoom, grid, () => preview.pointer], schedule, {
  flush: 'post',
})
onBeforeUnmount(() => cancelAnimationFrame(pending))
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
      <Button
        severity="secondary"
        outlined
        size="small"
        :aria-label="t('crop.magnifier.previous')"
        :disabled="preview.strip.length === 0 || preview.index === 0"
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
        :aria-label="t('crop.magnifier.next')"
        :disabled="preview.strip.length === 0 || preview.index === preview.strip.length - 1"
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
        @click="checking = true"
      />
    </nav>
    <CropCheckGrid v-model:visible="checking" />
  </section>
</template>

<style scoped>
.crop-magnifier {
  display: grid;
  gap: var(--rf-space-3);
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
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: var(--rf-space-4);
}

.crop-magnifier__strip {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
}

.crop-magnifier__caption {
  display: flex;
  justify-content: space-between;
  gap: var(--rf-space-2);
  font-size: var(--rf-font-size-sm);
}

.crop-magnifier__range {
  color: var(--rf-color-text-muted);
  font-variant-numeric: tabular-nums;
}

.crop-magnifier__canvas {
  display: block;
  border: 1px solid var(--rf-color-border);
  background: var(--rf-color-surface);
}

.crop-magnifier__frame {
  min-width: 7rem;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
</style>
