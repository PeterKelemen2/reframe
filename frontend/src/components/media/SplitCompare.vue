<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { FrameLink, Geometry } from '@/api/types'

const props = withDefaults(
  defineProps<{
    /** The source frame. */
    before: FrameLink
    /** The output picture at the same time: a rendered output frame or a frame of a clip. */
    after: FrameLink
    /** The job's geometry: `before` is shown cropped, turned and flipped as `after` is. */
    geometry: Geometry | null
    layout?: 'split' | 'side'
  }>(),
  { layout: 'split' },
)

const emit = defineEmits<{
  /** An image did not load (its link may have expired). */
  failed: [frame: FrameLink]
  loaded: [frame: FrameLink]
}>()

const { t } = useI18n()
/** How much of the width shows `before`, in per cent. */
const position = ref(50)

/**
 * `before` drawn in an SVG whose view box is the cropped and turned source picture, stretched
 * to the output's box: both show the same picture area, even when the output is scaled.
 */
const view = computed(() => {
  const crop = props.geometry?.crop ?? { top: 0, bottom: 0, left: 0, right: 0 }
  const rotation = props.geometry?.filter_rotation ?? 0
  const flip = props.geometry?.flip_horizontal === true ? -1 : 1
  const width = props.before.width - crop.left - crop.right
  const height = props.before.height - crop.top - crop.bottom
  const sideways = rotation === 90 || rotation === 270
  const boxWidth = sideways ? height : width
  const boxHeight = sideways ? width : height
  return {
    crop,
    viewBox: `0 0 ${boxWidth} ${boxHeight}`,
    transform:
      `translate(${boxWidth / 2} ${boxHeight / 2}) scale(${flip} 1) rotate(${rotation}) ` +
      `translate(${-width / 2} ${-height / 2})`,
  }
})

const aspect = computed(() => `${props.after.width} / ${props.after.height}`)
</script>

<template>
  <div class="split-compare" :class="`split-compare--${layout}`" :data-layout="layout">
    <figure class="split-compare__pane">
      <div class="split-compare__frame" :style="{ aspectRatio: aspect }">
        <img
          v-if="layout === 'split'"
          class="split-compare__after"
          :src="after.url"
          :alt="t('preview.compare.after')"
          draggable="false"
          @load="emit('loaded', after)"
          @error="emit('failed', after)"
        />
        <svg
          class="split-compare__before"
          :viewBox="view.viewBox"
          preserveAspectRatio="none"
          :style="layout === 'split' ? { clipPath: `inset(0 ${100 - position}% 0 0)` } : undefined"
          role="img"
          :aria-label="t('preview.compare.before')"
          data-part="before"
        >
          <image
            :href="before.url"
            :x="-view.crop.left"
            :y="-view.crop.top"
            :width="before.width"
            :height="before.height"
            :transform="view.transform"
            preserveAspectRatio="none"
            @load="emit('loaded', before)"
            @error="emit('failed', before)"
          />
        </svg>
        <template v-if="layout === 'split'">
          <span class="split-compare__label split-compare__label--before" aria-hidden="true">
            {{ t('preview.compare.before') }}
          </span>
          <span class="split-compare__label split-compare__label--after" aria-hidden="true">
            {{ t('preview.compare.after') }}
          </span>
          <input
            v-model.number="position"
            class="split-compare__range"
            type="range"
            min="0"
            max="100"
            step="1"
            :aria-label="t('preview.compare.position')"
            :aria-valuetext="t('preview.compare.valueText', { percent: position })"
          />
          <span
            class="split-compare__divider"
            :style="{ left: `${position}%` }"
            aria-hidden="true"
          />
        </template>
      </div>
      <figcaption v-if="layout === 'side'">{{ t('preview.compare.before') }}</figcaption>
    </figure>
    <figure v-if="layout === 'side'" class="split-compare__pane">
      <div class="split-compare__frame" :style="{ aspectRatio: aspect }">
        <img
          class="split-compare__after"
          :src="after.url"
          :alt="t('preview.compare.after')"
          @load="emit('loaded', after)"
          @error="emit('failed', after)"
        />
      </div>
      <figcaption>{{ t('preview.compare.after') }}</figcaption>
    </figure>
  </div>
</template>

<style scoped>
.split-compare {
  width: 100%;
}

.split-compare--side {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--rf-space-2);
}

.split-compare figure {
  margin: 0;
}

.split-compare__frame {
  position: relative;
  overflow: hidden;
  width: 100%;
  background: #000;
}

.split-compare__after,
.split-compare__before {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
}

.split-compare__label {
  position: absolute;
  top: var(--rf-space-1);
  padding: 0 var(--rf-space-1);
  border-radius: var(--rf-radius-sm);
  background: rgb(0 0 0 / 0.6);
  color: #fff;
  font-size: var(--rf-font-size-xs);
  pointer-events: none;
}

.split-compare__label--before {
  left: var(--rf-space-1);
}

.split-compare__label--after {
  right: var(--rf-space-1);
}

.split-compare__divider {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  margin-left: -1px;
  background: #fff;
  box-shadow: 0 0 0 1px rgb(0 0 0 / 0.5);
  pointer-events: none;
}

.split-compare__range {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  opacity: 0;
  cursor: ew-resize;
}

/* Inside the frame, over the pictures: its `overflow: hidden` cuts a ring drawn outside.
   White beside black: one of them stands out on any picture. */
.split-compare__frame:has(.split-compare__range:focus-visible)::after {
  content: '';
  position: absolute;
  inset: 0;
  box-shadow:
    inset 0 0 0 2px #fff,
    inset 0 0 0 4px #000;
  pointer-events: none;
}

.split-compare__pane figcaption {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  text-align: center;
}
</style>
