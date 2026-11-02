<script setup lang="ts">
import Button from 'primevue/button'
import InputNumber from 'primevue/inputnumber'
import Message from 'primevue/message'
import SelectButton from 'primevue/selectbutton'
import { computed, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { FrameLink } from '@/api/types'
import CropLoupe from '@/components/crop/CropLoupe.vue'
import CropOverlay from '@/components/dimensions/CropOverlay.vue'
import { useCropStore } from '@/stores/crop'
import { usePreviewStore, type ViewMode, type Zoom } from '@/stores/preview'

import SplitCompare from './SplitCompare.vue'

const { t, n } = useI18n()
const preview = usePreviewStore()
const crop = useCropStore()
const seekId = useId()

const views = computed(() =>
  (['source', 'output', 'split', 'side'] as const).map((value) => ({
    value,
    label: t(`preview.view.${value}`),
  })),
)
const zooms = computed(() =>
  (['fit', 1, 2] as const).map((value) => ({
    value,
    label: t(`preview.zoom.${value === 'fit' ? 'fit' : value * 100}`),
  })),
)

function time(seconds: number): string {
  return t('preview.seconds', { seconds: n(seconds, { maximumFractionDigits: 3 }) })
}

/** The width of a picture box: the panel's width at `fit` (no taller than the screen allows). */
function boxWidth(frame: FrameLink, zoom: Zoom, pictures = 1): string {
  if (zoom === 'fit')
    return pictures === 1 ? `min(100%, ${(60 * frame.width) / frame.height}vh)` : '100%'
  return `${frame.width * zoom * pictures}px`
}

const position = computed(() => {
  const frame = preview.current
  if (frame === null) return null
  if (preview.index === null) return time(frame.timestamp)
  return t('preview.position', {
    n: preview.index + 1,
    count: preview.strip.length,
    time: time(frame.timestamp),
  })
})

// An image that failed and was not asked for again shows its state instead.
const broken = ref<string | null>(null)
watch(
  () => [preview.current?.url, preview.output?.url, preview.viewMode],
  () => {
    broken.value = null
  },
)

function failed(frame: FrameLink): void {
  if (!preview.imageFailed(frame)) broken.value = frame.url
}

const hasFrames = computed(() => preview.sourceId !== null && !preview.noVideo)

// The button goes away while the frames are made: the stage, where they show, takes the focus.
const stage = useTemplateRef<HTMLElement>('stage')

function retry(again: () => unknown): void {
  stage.value?.focus()
  void again()
}

const seekValue = ref<number | null>(null)

function seek(): void {
  if (seekValue.value !== null) void preview.seek(seekValue.value)
}

function pointerAt(event: PointerEvent): void {
  const frame = preview.current
  const box = (event.currentTarget as HTMLElement).getBoundingClientRect()
  if (frame === null || box.width === 0 || box.height === 0) return
  preview.pointer = {
    x: ((event.clientX - box.left) / box.width) * frame.width,
    y: ((event.clientY - box.top) / box.height) * frame.height,
  }
}

// A render repeats the source's notes (how an HDR picture is mapped).
const notes = computed(() => [
  ...new Set([...preview.notes, ...(preview.viewMode === 'source' ? [] : preview.renderNotes)]),
])
</script>

<template>
  <div class="frame-viewer">
    <div v-if="hasFrames" class="frame-viewer__controls">
      <SelectButton
        :model-value="preview.viewMode"
        :options="views"
        option-label="label"
        option-value="value"
        :allow-empty="false"
        size="small"
        :pt="{ root: { 'aria-label': t('preview.view.label') } }"
        data-field="view-mode"
        @update:model-value="preview.viewMode = $event as ViewMode"
      />
      <SelectButton
        :model-value="preview.zoom"
        :options="zooms"
        option-label="label"
        option-value="value"
        :allow-empty="false"
        size="small"
        :pt="{ root: { 'aria-label': t('preview.zoom.label') } }"
        data-field="zoom"
        @update:model-value="preview.zoom = $event as Zoom"
      />
    </div>

    <p v-if="preview.sourceId === null" class="frame-viewer__state" data-state="empty">
      {{ t('preview.empty') }}
    </p>
    <p v-else-if="preview.noVideo" class="frame-viewer__state" data-state="no-video">
      {{ t('preview.noVideo') }}
    </p>
    <template v-else>
      <!-- A tab stop while zoomed (the arrow keys scroll it); it keeps the focus while the next
           frame is on its way. -->
      <div
        ref="stage"
        class="frame-viewer__stage"
        role="group"
        :aria-label="t('preview.stage')"
        :tabindex="preview.zoom === 'fit' ? -1 : 0"
        data-field="stage"
        :data-view="preview.viewMode"
      >
        <p
          v-if="preview.loading && preview.strip.length === 0"
          class="frame-viewer__state"
          role="status"
          data-state="loading"
          aria-busy="true"
        >
          {{ t('preview.loading') }}
        </p>
        <div v-else-if="preview.error !== null" class="frame-viewer__state" data-state="error">
          <Message severity="error" :closable="false">
            {{ t('preview.failed', { reason: preview.error }) }}
          </Message>
          <Button
            :label="t('preview.retry')"
            severity="secondary"
            size="small"
            data-action="retry"
            @click="retry(preview.reload)"
          />
        </div>
        <p v-else-if="preview.current === null" class="frame-viewer__state" data-state="no-frames">
          {{ t('preview.noFrames') }}
        </p>
        <p v-else-if="broken !== null" class="frame-viewer__state" data-state="image-failed">
          {{ t('preview.imageFailed') }}
        </p>
        <div
          v-else-if="preview.viewMode === 'source'"
          class="frame-viewer__picture"
          :style="{
            width: boxWidth(preview.current, preview.zoom),
            aspectRatio: `${preview.current.width} / ${preview.current.height}`,
          }"
        >
          <img
            class="frame-viewer__image"
            :src="preview.current.url"
            :alt="t('preview.picture', { time: time(preview.current.timestamp) })"
            draggable="false"
            data-field="frame"
            @load="preview.imageLoaded(preview.current)"
            @error="failed(preview.current)"
          />
          <div
            class="frame-viewer__overlay"
            data-layer="overlay"
            @pointermove="pointerAt"
            @pointerleave="preview.pointer = null"
          >
            <CropOverlay />
            <CropLoupe />
          </div>
        </div>
        <div
          v-else-if="preview.renderError !== null"
          class="frame-viewer__state"
          data-state="render-failed"
        >
          <Message severity="error" :closable="false">
            {{ t('preview.renderFailed', { reason: preview.renderError }) }}
          </Message>
          <Button
            :label="t('preview.retry')"
            severity="secondary"
            size="small"
            data-action="render-again"
            @click="retry(preview.renderAgain)"
          />
        </div>
        <p
          v-else-if="preview.output === null"
          class="frame-viewer__state"
          role="status"
          data-state="rendering"
          aria-busy="true"
        >
          {{ t('preview.rendering') }}
        </p>
        <img
          v-else-if="preview.viewMode === 'output'"
          class="frame-viewer__image"
          :style="{ width: boxWidth(preview.output, preview.zoom) }"
          :src="preview.output.url"
          :alt="t('preview.outputPicture', { time: time(preview.output.timestamp) })"
          data-field="output"
          @load="preview.imageLoaded(preview.output)"
          @error="failed(preview.output)"
        />
        <SplitCompare
          v-else
          :style="{
            width: boxWidth(preview.output, preview.zoom, preview.viewMode === 'side' ? 2 : 1),
          }"
          :before="preview.current"
          :after="preview.output"
          :geometry="crop.geometry?.geometry ?? null"
          :layout="preview.viewMode === 'side' ? 'side' : 'split'"
          @failed="failed"
          @loaded="preview.imageLoaded"
        />
      </div>
      <p
        v-if="position !== null"
        class="frame-viewer__position"
        aria-live="polite"
        data-field="position"
      >
        {{ position }}
      </p>
      <div
        v-if="preview.strip.length > 0"
        class="frame-viewer__strip"
        role="group"
        :aria-label="t('preview.strip')"
        :aria-busy="preview.loading"
      >
        <button
          v-for="(frame, at) in preview.strip"
          :key="frame.key"
          type="button"
          class="frame-viewer__thumb"
          :class="{ 'frame-viewer__thumb--current': at === preview.index }"
          :aria-label="t('preview.frame', { time: time(frame.timestamp) })"
          :aria-current="at === preview.index ? 'true' : undefined"
          data-field="thumb"
          @click="preview.select(at)"
        >
          <img
            :src="frame.url"
            alt=""
            draggable="false"
            :style="{ aspectRatio: `${frame.width} / ${frame.height}` }"
            @load="preview.imageLoaded(frame)"
            @error="failed(frame)"
          />
        </button>
      </div>
    </template>

    <form v-if="hasFrames" class="frame-viewer__seek" data-field="seek" @submit.prevent="seek">
      <label :for="seekId">{{ t('preview.seek.label') }}</label>
      <InputNumber
        v-model="seekValue"
        :input-id="seekId"
        :min="0"
        :min-fraction-digits="0"
        :max-fraction-digits="3"
        :use-grouping="false"
        size="small"
      />
      <Button
        type="submit"
        :label="t('preview.seek.go')"
        severity="secondary"
        size="small"
        :loading="preview.seeking"
      />
    </form>
    <p
      v-if="preview.seekNote !== null"
      class="frame-viewer__note"
      role="alert"
      data-field="seek-note"
    >
      {{ preview.seekNote }}
    </p>
    <ul v-if="notes.length > 0" class="frame-viewer__notes" data-field="notes">
      <li v-for="note in notes" :key="note">{{ note }}</li>
    </ul>
  </div>
</template>

<style scoped>
.frame-viewer {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--rf-space-3);
}

.frame-viewer__controls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
}

.frame-viewer__state {
  display: grid;
  justify-items: start;
  gap: var(--rf-space-2);
  margin: 0;
  color: var(--rf-color-text-muted);
}

.frame-viewer__stage {
  overflow: auto;
  max-height: 70vh;
}

.frame-viewer__stage:focus-visible {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: 2px;
}

.frame-viewer__picture,
.frame-viewer__stage > .frame-viewer__image,
.frame-viewer__stage > .split-compare {
  margin-inline: auto;
}

.frame-viewer__picture {
  position: relative;
  max-width: none;
  background: #000;
}

.frame-viewer__image {
  display: block;
  width: 100%;
  height: auto;
}

.frame-viewer__picture > .frame-viewer__image {
  height: 100%;
}

.frame-viewer__overlay {
  position: absolute;
  inset: 0;
}

.frame-viewer__position,
.frame-viewer__note {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  font-variant-numeric: tabular-nums;
}

.frame-viewer__strip {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(4rem, 1fr));
  gap: var(--rf-space-1);
}

.frame-viewer__thumb {
  padding: 0;
  border: 2px solid transparent;
  border-radius: var(--rf-radius-sm);
  background: #000;
  cursor: pointer;
}

.frame-viewer__thumb img {
  display: block;
  width: 100%;
  object-fit: contain;
}

.frame-viewer__thumb--current {
  border-color: var(--rf-color-primary);
}

.frame-viewer__thumb:focus-visible {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: 2px;
}

.frame-viewer__seek {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
}

.frame-viewer__seek label {
  font-size: var(--rf-font-size-sm);
}

.frame-viewer__seek :deep(.p-inputnumber-input) {
  width: 7rem;
}

.frame-viewer__notes {
  margin: 0;
  padding-left: var(--rf-space-4);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}
</style>
