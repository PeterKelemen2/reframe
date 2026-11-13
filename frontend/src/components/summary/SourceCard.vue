<script setup lang="ts">
import { ImageOff } from '@lucide/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import Card from '@/components/base/Card.vue'
import KeyValue from '@/components/base/KeyValue.vue'
import { useRange } from '@/components/range/useRange'
import { fileName, formatDuration } from '@/components/shell/format'
import { useEditorStore } from '@/stores/editor'

import { formatBitrate, formatBytes, videoLine } from './format'
import { useJobSource } from './useJobSource'
import { useThumbnail } from './useThumbnail'

const { t } = useI18n()
const editor = useEditorStore()
const { sourceId, entry, source } = useJobSource()
const { label: rangeLabel, length: rangeLength } = useRange()

const video = computed(() => source.value?.video?.[0] ?? null)
const thumbnail = useThumbnail(sourceId, () => video.value !== null)

const name = computed(() => fileName(entry.value?.path ?? editor.job?.source.path ?? ''))
const container = computed(() => source.value?.container ?? null)
const size = computed(() => {
  const bytes = container.value?.size
  return bytes == null ? null : formatBytes(bytes, t)
})
const bitrate = computed(() => {
  const value = container.value?.bitrate
  return value == null ? null : formatBitrate(value, t)
})
const line = computed(() => (video.value === null ? null : videoLine(video.value, t).join(' · ')))
const tracks = computed(() => {
  const media = source.value
  if (media === null) return null
  return [
    t('summary.source.audioTracks', media.audio?.length ?? 0),
    t('summary.source.subtitleTracks', media.subtitles?.length ?? 0),
  ].join(' · ')
})
const range = computed(() =>
  rangeLength.value === null
    ? rangeLabel.value
    : t('summary.source.rangeValue', { range: rangeLabel.value, length: rangeLength.value }),
)
const chapters = computed(() => {
  const count = source.value?.chapters?.length
  return count === undefined ? null : count === 0 ? t('summary.source.noChapters') : String(count)
})
</script>

<template>
  <Card class="summary-card summary-source" :title="t('summary.source.title')" data-card="source">
    <div class="summary-source__body">
      <div class="summary-source__thumb" :data-state="thumbnail.url.value ? 'ready' : 'empty'">
        <img
          v-if="thumbnail.url.value"
          :src="thumbnail.url.value"
          :alt="t('summary.source.thumbnail', { name })"
          @error="thumbnail.failed()"
        />
        <span v-else-if="!thumbnail.loading.value" class="summary-source__no-thumb">
          <ImageOff :size="24" aria-hidden="true" />
          <span class="rf-sr-only">{{ t('summary.source.noThumbnail') }}</span>
        </span>
      </div>
      <dl class="rf-kv-list summary-source__facts">
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
.summary-source__facts {
  flex: 999 1 18rem;
}

.summary-source__body > .summary-card__note {
  flex-basis: 100%;
}

.summary-source__body {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: var(--rf-space-3) var(--rf-space-4);
}

.summary-source__thumb {
  flex: 1 1 12rem;
  max-width: 18rem;
  display: grid;
  place-items: center;
  overflow: hidden;
  aspect-ratio: 16 / 9;
  border-radius: var(--rf-radius-md);
  background: var(--p-status-off-background);
  color: var(--rf-color-text-muted);
}

.summary-source__thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.summary-source__name {
  font-weight: var(--rf-font-weight-medium);
}
</style>
