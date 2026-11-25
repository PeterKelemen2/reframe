<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import Card from '@/components/base/Card.vue'
import KeyValue from '@/components/base/KeyValue.vue'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'

import { filterChips } from './filters'
import { formatAspect } from './format'
import { pipelineOf, type Size } from './pipeline'
import SummaryLink from './SummaryLink.vue'
import { useGeometry } from './useGeometry'

const { t, n } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const geometry = useGeometry()

function size({ width, height }: Size): string {
  return `${width}×${height}`
}

const pipeline = computed(() =>
  geometry.answer.value === null ? null : pipelineOf(geometry.answer.value),
)

/** `3840×2160 → crop 3840×1600 → scale 1920×800 · 2.40:1 · square pixels` */
const line = computed<string | null>(() => {
  const current = pipeline.value
  if (current === null) return null
  switch (current.kind) {
    case 'no-video':
      return t('summary.picture.noVideo')
    case 'copied':
      return t('summary.picture.copied', { size: size(current.source) })
  }
  const steps = [size(current.source)]
  if (current.crop) steps.push(t('summary.picture.crop', { size: size(current.crop) }))
  if (current.rotation !== 0) {
    steps.push(t('summary.picture.rotate', { degrees: current.rotation }))
  }
  if (current.scale) steps.push(t('summary.picture.scale', { size: size(current.scale) }))
  const pixels = current.par
    ? t('summary.picture.par', { par: `${current.par.num}:${current.par.den}` })
    : t('summary.picture.square')
  return [steps.join(' → '), formatAspect(current.aspect, t, n), pixels].join(' · ')
})

const tone = computed(() => {
  if (geometry.error.value !== null) return 'error'
  return pipeline.value?.kind === 'encoded' && pipeline.value.upscaled ? 'warn' : null
})
const notes = computed(() => (pipeline.value?.kind === 'encoded' ? pipeline.value.notes : []))

const crop = computed(() => editor.job?.dimensions?.crop ?? null)
const cropMode = computed(() =>
  crop.value === null ? null : t(`dimensions.crop.modes.${crop.value.mode}`),
)
/** The edges in the order of the inputs, or why there are none. */
const cropRect = computed(() => {
  const current = crop.value
  if (current === null || current.mode === 'none') return null
  if (!current.rect) return t('summary.picture.cropPending')
  return t('dimensions.crop.rect', { ...current.rect })
})

const chips = computed(() => filterChips(editor.job?.filters, system.definitions))
</script>

<template>
  <Card
    class="summary-card summary-picture"
    :title="t('summary.picture.title')"
    data-card="picture"
  >
    <div class="summary-picture__body">
      <dl class="rf-kv-list">
        <KeyValue :label="t('summary.picture.cropLabel')">
          <SummaryLink path="dimensions.crop">
            <span class="summary-picture__crop" data-field="crop">
              <span v-if="cropRect" :class="{ 'rf-mono': crop?.rect }">{{ cropRect }}</span
              >{{ ' ' }}
              <span v-if="cropMode" class="summary-picture__mode">
                {{ cropRect ? t('summary.picture.cropMode', { mode: cropMode }) : cropMode }}
              </span>
            </span>
          </SummaryLink>
        </KeyValue>
        <KeyValue :label="t('summary.picture.size')">
          <SummaryLink path="dimensions">
            <span
              class="summary-picture__pipeline"
              :class="tone && `summary-picture__pipeline--${tone}`"
              :aria-busy="geometry.pending.value"
              data-field="pipeline"
            >
              <template v-if="geometry.error.value !== null">
                {{ t('summary.picture.failed', { reason: geometry.error.value }) }}
              </template>
              <template v-else>{{ line ?? t('summary.picture.computing') }}</template>
            </span>
          </SummaryLink>
        </KeyValue>
      </dl>
      <p v-if="tone === 'warn'" class="summary-picture__upscaled">
        {{ t('summary.picture.upscaled') }}
      </p>
      <ul v-if="notes.length > 0" class="summary-card__notes">
        <li v-for="note in notes" :key="note">{{ note }}</li>
      </ul>
      <ul class="summary-chips" :aria-label="t('summary.picture.filters')" data-field="filters">
        <li v-for="chip in chips" :key="chip.id">
          <SummaryLink :path="`filters.${chip.id}`">
            <span
              class="summary-chip"
              :class="{ 'summary-chip--off': chip.value === null }"
              :data-filter="chip.id"
            >
              {{
                t('summary.picture.filter', {
                  label: chip.label,
                  value: chip.value ?? t('summary.picture.off'),
                })
              }}
            </span>
          </SummaryLink>
        </li>
      </ul>
    </div>
  </Card>
</template>

<style scoped>
.summary-picture__body {
  display: grid;
  gap: var(--rf-space-3);
}

.summary-picture__pipeline {
  font-family: var(--rf-font-mono);
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.summary-picture__crop {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 0 var(--rf-space-2);
}

.summary-picture__crop .rf-mono,
.summary-picture__pipeline {
  font-size: var(--rf-font-size-sm);
}

.summary-picture__mode {
  color: var(--rf-color-text-muted);
}

.summary-picture__pipeline--warn,
.summary-picture__upscaled {
  color: var(--p-status-warn-color);
}

.summary-picture__pipeline--error {
  color: var(--p-status-error-color);
}

.summary-picture__upscaled {
  margin: 0;
  font-size: var(--rf-font-size-sm);
}
</style>
