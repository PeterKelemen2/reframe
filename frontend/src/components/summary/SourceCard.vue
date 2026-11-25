<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import Card from '@/components/base/Card.vue'
import KeyValue from '@/components/base/KeyValue.vue'
import { useRange } from '@/components/range/useRange'
import { fileName, formatDuration } from '@/components/shell/format'
import { useEditorStore } from '@/stores/editor'

import { formatBitrate, formatBytes, videoLine } from './format'
import { useJobSource } from './useJobSource'

const { t, n } = useI18n()
const editor = useEditorStore()
const { entry, source } = useJobSource()
const { label: rangeLabel, length: rangeLength } = useRange()

const video = computed(() => source.value?.video?.[0] ?? null)

const name = computed(() => fileName(entry.value?.path ?? editor.job?.source.path ?? ''))
const container = computed(() => source.value?.container ?? null)
const size = computed(() => {
  const bytes = container.value?.size
  return bytes == null ? null : formatBytes(bytes, t, n)
})
const bitrate = computed(() => {
  const value = container.value?.bitrate
  return value == null ? null : formatBitrate(value, t, n)
})
const line = computed(() =>
  video.value === null ? null : videoLine(video.value, t, n).join(' · '),
)
const tracks = computed(() => {
  const media = source.value
  if (media === null) return null
  return t('summary.source.trackCounts', {
    audio: t('summary.source.audioTracks', media.audio?.length ?? 0),
    subtitles: t('summary.source.subtitleTracks', media.subtitles?.length ?? 0),
  })
})
const range = computed(() =>
  rangeLength.value === null
    ? rangeLabel.value
    : t('summary.source.rangeValue', { range: rangeLabel.value, length: rangeLength.value }),
)
const chapters = computed(() => {
  const count = source.value?.chapters?.length
  return count === undefined ? null : count === 0 ? t('summary.source.noChapters') : n(count)
})
</script>

<template>
  <Card class="summary-card summary-source" :title="t('summary.source.title')" data-card="source">
    <div class="summary-source__body">
      <dl class="rf-kv-list">
        <KeyValue :label="t('summary.source.file')">
          <span class="summary-source__name" data-field="file">{{ name }}</span>
        </KeyValue>
        <template v-if="source">
          <KeyValue
            :label="t('summary.source.container')"
            :value="container?.display_name ?? container?.format_name"
          />
          <KeyValue
            :label="t('summary.source.duration')"
            :value="formatDuration(container?.duration)"
          />
          <KeyValue :label="t('summary.source.size')" :value="size" />
          <KeyValue :label="t('summary.source.bitrate')" :value="bitrate" />
          <KeyValue :label="t('summary.source.video')">
            <span data-field="video-line">{{ line ?? t('summary.source.noVideo') }}</span>
          </KeyValue>
          <KeyValue :label="t('summary.source.tracks')">
            <span data-field="tracks">{{ tracks }}</span>
          </KeyValue>
          <KeyValue :label="t('summary.source.chapters')">
            <span data-field="chapters">{{ chapters }}</span>
          </KeyValue>
          <KeyValue :label="t('summary.source.range')">
            <span data-field="range">{{ range }}</span>
          </KeyValue>
        </template>
      </dl>
      <p v-if="!source" class="summary-card__note" data-state="not-probed">
        {{ entry ? t('summary.source.changed') : t('summary.source.notOpen') }}
      </p>
    </div>
  </Card>
</template>

<style scoped>
.summary-source__body {
  display: grid;
  gap: var(--rf-space-3);
}

.summary-source__name {
  font-weight: var(--rf-font-weight-medium);
}
</style>
