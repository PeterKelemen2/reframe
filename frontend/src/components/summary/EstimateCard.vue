<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import Card from '@/components/base/Card.vue'
import { useRange } from '@/components/range/useRange'
import { formatDuration } from '@/components/shell/format'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'

import { type Estimate, estimateSize } from './estimate'
import { formatBytes } from './format'
import { useJobSource } from './useJobSource'

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const { source } = useJobSource()
const range = useRange()

const estimate = computed<Estimate | null>(() => {
  const job = editor.job
  if (job === null) return null
  if (job.video?.rate_control?.mode !== 'bitrate' && !job.video?.passthrough) {
    return { kind: 'quality' }
  }
  if (source.value === null) return { kind: 'unknown', reason: 'duration' }
  // In a group the file's range is its override, which the shown job may leave out.
  return estimateSize({ ...job, range: range.range.value }, source.value, system.definitions)
})
</script>

<template>
  <Card
    class="summary-card summary-estimate"
    :title="t('summary.estimate.title')"
    data-card="estimate"
  >
    <template v-if="estimate">
      <template v-if="estimate.kind === 'size'">
        <p class="summary-estimate__size" data-field="size">
          {{ t('summary.estimate.about', { size: formatBytes(estimate.bytes, t) }) }}
        </p>
        <p class="summary-card__note" data-field="basis">
          {{
            t('summary.estimate.basis', {
              video: Math.round(estimate.videoKbps),
              audio: Math.round(estimate.audioKbps),
              duration: formatDuration(estimate.seconds),
            })
          }}
        </p>
        <p v-if="estimate.unknownTracks > 0" class="summary-card__note" data-field="unknown">
          {{ t('summary.estimate.unknownTracks', estimate.unknownTracks) }}
        </p>
      </template>
      <template v-else-if="estimate.kind === 'quality'">
        <p class="summary-estimate__size" data-field="size">
          {{ t('summary.estimate.dependsOnContent') }}
        </p>
        <p class="summary-card__note">{{ t('summary.estimate.qualityHint') }}</p>
      </template>
      <p v-else class="summary-estimate__size" data-field="size">
        {{
          estimate.reason === 'video'
            ? t('summary.estimate.noVideoBitrate')
            : t('summary.estimate.noDuration')
        }}
      </p>
      <p class="summary-card__note" data-field="range">
        {{
          range.length.value === null
            ? t('summary.estimate.rangeNoLength', { range: range.label.value })
            : t('summary.estimate.range', {
                range: range.label.value,
                length: range.length.value,
              })
        }}
      </p>
    </template>
  </Card>
</template>

<style scoped>
.summary-estimate__size {
  margin: 0;
  font-size: var(--rf-font-size-xl);
  font-weight: var(--rf-font-weight-bold);
}
</style>
