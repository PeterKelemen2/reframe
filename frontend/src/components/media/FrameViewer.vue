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

import ScrollStage from './ScrollStage.vue'
import SplitCompare from './SplitCompare.vue'
import { boxWidth } from './zoom'

const { t, n, locale } = useI18n()
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

// The next output frame takes the last one's place while it renders, so the page does not jump.
const lastOutput = ref<FrameLink | null>(null)
watch(
  () => preview.output,
  (frame) => {
    if (frame !== null) lastOutput.value = frame
  },
)
watch(
  () => preview.sourceId,
  () => {
    lastOutput.value = null
  },
)
const pendingBox = computed(() => {
  const frame = lastOutput.value ?? preview.current
  if (frame === null) return undefined
  const pictures = preview.viewMode === 'side' ? 2 : 1
  return {
    width: boxWidth(frame, preview.zoom, pictures),
    aspectRatio: `${frame.width * pictures} / ${frame.height}`,
  }
})

const hasFrames = computed(() => preview.sourceId !== null && !preview.noVideo)

// The button goes away while the frames are made: the stage, where they show, takes the focus.
const stage = useTemplateRef<{ focus(): void }>('stage')

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
    <h3 v-if="hasFrames" class="frame-viewer__title" data-field="frame-title">
      {{ t(`preview.title.${preview.viewMode}`) }}
    </h3>
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
    <template v-else-if="preview.noVideo">
      <p class="frame-viewer__state" data-state="no-video">
        {{ t('preview.noVideo') }}
      </p>
      <slot name="programme" />
    </template>
    <template v-else>
      <!-- A tab stop while zoomed (the arrow keys scroll it); it keeps the focus while the next
           frame is on its way. -->
      <ScrollStage
        ref="stage"
        class="frame-viewer__stage"
        :class="{ 'frame-viewer__stage--pixels': preview.zoom !== 'fit' }"
        role="group"
        :label="t('preview.stage')"
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
          class="frame-viewer__state frame-viewer__pending"
          :style="pendingBox"
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
      </ScrollStage>
      <slot name="programme" />
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
      <p
        v-if="position !== null"
        class="frame-viewer__position"
        aria-live="polite"
        data-field="position"
      >
        {{ position }}
      </p>
    </template>

    <form v-if="hasFrames" class="frame-viewer__seek" data-field="seek" @submit.prevent="seek">
      <label :for="seekId">{{ t('preview.seek.label') }}</label>
      <InputNumber
        v-model="seekValue"
        :locale="locale"
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

.frame-viewer__title {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  font-weight: var(--rf-font-weight-medium);
}

.frame-viewer__controls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
}

/* Joined segments on the booth, the chosen one filled with ink: the picture keeps the colour. */
.frame-viewer__controls :deep(.p-selectbutton) {
  --p-selectbutton-border-radius: var(--rf-radius-md);
  --p-togglebutton-sm-padding: 0;
  --p-togglebutton-content-sm-padding: 0.25rem 0.5rem;
  --p-togglebutton-background: transparent;
  --p-togglebutton-border-color: var(--p-form-field-border-color);
  --p-togglebutton-color: var(--rf-color-text);
  --p-togglebutton-hover-background: var(--rf-color-surface-hover);
  --p-togglebutton-hover-color: var(--rf-color-text);
  --p-togglebutton-checked-background: var(--rf-color-primary);
  --p-togglebutton-checked-border-color: var(--rf-color-primary);
  --p-togglebutton-checked-color: var(--rf-color-on-primary);
  --p-togglebutton-content-checked-background: transparent;
  --p-togglebutton-content-checked-shadow: none;

  background: transparent;
}

.frame-viewer__controls :deep(.p-togglebutton) {
  font-weight: var(--rf-font-weight-medium);
  white-space: nowrap;
}

.frame-viewer__controls :deep([data-field='view-mode']) {
  flex: 1 1 100%;
}

.frame-viewer__controls :deep([data-field='view-mode'] .p-togglebutton) {
  flex: 1 1 auto;
}

.frame-viewer__state {
  display: grid;
  justify-items: start;
  gap: var(--rf-space-2);
  margin: 0;
  color: var(--rf-color-text-muted);
}

.frame-viewer__pending {
  place-content: center;
  justify-items: center;
  max-width: none;
  border-radius: var(--rf-radius-sm);
  background: var(--rf-color-surface-hover);
}

.frame-viewer__picture,
.frame-viewer__pending,
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
  /* One row: the frames are a sequence in time. A long one scrolls instead of wrapping. */
  display: grid;
  grid-auto-columns: minmax(1.5rem, 1fr);
  grid-auto-flow: column;
  gap: var(--rf-space-1);
  overflow-x: auto;
}

.frame-viewer__thumb {
  overflow: hidden;
  padding: 0;
  border: 0;
  border-radius: 2px;
  background: #000;
  cursor: pointer;
}

.frame-viewer__thumb img {
  display: block;
  width: 100%;
  object-fit: contain;
}

.frame-viewer__thumb:hover img {
  opacity: 0.85;
}

/* The current frame is marked in ink, not a colour: a ring with a gap of the booth around it. */
.frame-viewer__thumb--current {
  box-shadow:
    0 0 0 1px var(--rf-color-booth),
    0 0 0 3px var(--rf-color-text);
}

.frame-viewer__thumb:focus-visible {
  outline: 2px solid var(--p-focus-ring-color);
  outline-offset: 5px;
}

/* At 100 % and more each source pixel is a block: smoothing would blur what is checked. */
.frame-viewer__stage--pixels :deep(img) {
  image-rendering: pixelated;
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
