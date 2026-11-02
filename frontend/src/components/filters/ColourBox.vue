<script setup lang="ts">
import Button from 'primevue/button'
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'

import type { FilterDef } from '@/api/types'
import KeyValue from '@/components/base/KeyValue.vue'
import { colourName, hdrNames } from '@/components/summary/format'
import { useJobSource } from '@/components/summary/useJobSource'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useValidationStore } from '@/stores/validation'

import { colourOutcome, sourceColour } from './colour'
import { implementationOf, presetOf } from './filters'

/** The shown file's colours, what Colorspace and Tone mapping make of them, and the fix. */
const props = defineProps<{ filter: FilterDef; disabled: boolean }>()

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const validation = useValidationStore()
const { source } = useJobSource()
const headingId = useId()

const stream = computed(() => source.value?.video?.[0] ?? null)

function named(name: string | null, value: string | null | undefined): string {
  if (!value) return t('filters.colour.notTagged')
  return name !== null && name !== value ? t('filters.colour.named', { name, value }) : value
}

const rows = computed(() => {
  const video = stream.value
  if (video === null) return []
  const color = video.color ?? {}
  const range = color.range
  const shown = [
    {
      key: 'primaries',
      value: named(colourName({ primaries: color.primaries }), color.primaries),
    },
    { key: 'transfer', value: named(colourName({ transfer: color.transfer }), color.transfer) },
    { key: 'matrix', value: named(null, color.matrix) },
    {
      key: 'range',
      value:
        range === 'tv'
          ? t('filters.colour.limited', { range })
          : range === 'pc'
            ? t('filters.colour.full', { range })
            : t('filters.colour.notTagged'),
    },
    {
      key: 'bitDepth',
      value:
        typeof video.bit_depth === 'number'
          ? t('filters.colour.bits', { bits: video.bit_depth })
          : t('filters.colour.notTagged'),
    },
    {
      key: 'hdr',
      value: hdrNames(video.hdr).join(', ') || t('filters.colour.sdr'),
    },
  ]
  const mastering = video.hdr?.mastering_display
  if (mastering) {
    shown.push(
      {
        key: 'mastering',
        value: t('filters.colour.primariesValue', {
          rx: mastering.red_x,
          ry: mastering.red_y,
          gx: mastering.green_x,
          gy: mastering.green_y,
          bx: mastering.blue_x,
          by: mastering.blue_y,
          wx: mastering.white_x,
          wy: mastering.white_y,
        }),
      },
      {
        key: 'luminance',
        value: t('filters.colour.luminanceValue', {
          min: mastering.min_luminance,
          max: mastering.max_luminance,
        }),
      },
    )
  }
  const light = video.hdr?.content_light
  if (light) {
    shown.push({
      key: 'contentLight',
      value: t('filters.colour.contentLightValue', { cll: light.max_cll, fall: light.max_fall }),
    })
  }
  return shown
})

const sentence = computed(() => {
  const video = stream.value
  const filters = editor.job?.filters
  if (video === null || filters === undefined) return null
  const config = filters.colorspace ?? null
  const implementation = implementationOf(props.filter, config, system.capabilities)
  const preset = config === null ? null : presetOf(implementation, config)
  const from = sourceColour(video) ?? t('filters.colour.untagged')
  const to = preset?.label ?? config?.preset ?? ''
  const outcome = colourOutcome(video, filters, preset?.custom === true)
  switch (outcome.kind) {
    case 'keep':
      return t('filters.colour.keep', { from })
    case 'tonemapOnly':
      return t('filters.colour.tonemapOnly', { from })
    case 'custom':
      return t('filters.colour.custom', { from })
  }
  if (!outcome.toSdr) return t('filters.colour.convert', { from, to })
  return outcome.tonemapped
    ? t('filters.colour.convertToneMapped', { from, to })
    : t('filters.colour.convertSdr', { from, to })
})

// The server decides when tone mapping is missing; its fix is the button.
const washedOut = computed(
  () =>
    validation
      .issuesFor('filters.colorspace')
      .find((issue) => issue.code === 'filter.hdr_without_tonemap') ?? null,
)
</script>

<template>
  <section class="colour-box" :aria-labelledby="headingId" data-box="source-colour">
    <h4 :id="headingId" class="colour-box__title">{{ t('filters.colour.title') }}</h4>
    <p v-if="stream === null" class="colour-box__empty">{{ t('filters.colour.noSource') }}</p>
    <template v-else>
      <dl class="rf-kv-list colour-box__values">
        <KeyValue
          v-for="row in rows"
          :key="row.key"
          :label="t(`filters.colour.${row.key}`)"
          :value="row.value"
          :data-colour="row.key"
        />
      </dl>
      <p class="colour-box__sentence" data-colour-sentence>
        <span data-sentence>{{ sentence }}</span>
        <template v-if="washedOut !== null">
          <!-- The space keeps the two sentences apart for a screen reader. -->
          {{ ' ' }}
          <span class="colour-box__warning" data-washed-out>{{
            t('filters.colour.washedOut')
          }}</span>
          <span aria-hidden="true">→</span>
          <Button
            v-for="fix in washedOut.fixes ?? []"
            :key="fix.label"
            :label="fix.label"
            size="small"
            :disabled="disabled"
            data-action="fix"
            @click="editor.applyFix(fix)"
          />
        </template>
      </p>
    </template>
  </section>
</template>

<style scoped>
.colour-box {
  display: grid;
  gap: var(--rf-space-2);
  padding: var(--rf-space-3);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
  background: var(--rf-color-surface);
}

.colour-box__title {
  margin: 0;
  color: var(--rf-color-text);
  font-size: var(--rf-font-size-md);
  font-weight: var(--rf-font-weight-bold);
}

.colour-box__values {
  margin: 0;
  font-size: var(--rf-font-size-sm);
}

.colour-box__empty {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.colour-box__sentence {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-1) var(--rf-space-2);
  margin: 0;
  color: var(--rf-color-text);
}

.colour-box__warning {
  color: var(--p-status-warn-color);
}
</style>
