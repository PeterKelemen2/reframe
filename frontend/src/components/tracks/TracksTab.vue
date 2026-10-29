<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import Section from '@/components/base/Section.vue'
import TrackTable from '@/components/media/TrackTable.vue'
import { useJobSource } from '@/components/summary/useJobSource'
import { useEditorStore } from '@/stores/editor'

import type { TrackList } from './ops'
import OutputTrackList from './OutputTrackList.vue'

/** The Audio or Subtitles tab: the source's tracks, then the job's output tracks. */
const props = defineProps<{ list: TrackList }>()

const { t } = useI18n()
const editor = useEditorStore()
const { source } = useJobSource()

const streams = computed(() =>
  props.list === 'audio' ? (source.value?.audio ?? []) : (source.value?.subtitles ?? []),
)
</script>

<template>
  <section class="editor-tab tracks-tab" :data-tab="list">
    <p v-if="editor.job === null" class="tracks-tab__empty" data-state="empty">
      {{ editor.loading ? t('tracks.loading') : t('tracks.noJob') }}
    </p>
    <template v-else>
      <Section :title="t('tracks.source.title')">
        <p v-if="source === null" class="tracks-tab__empty" data-state="no-source">
          {{ t('tracks.source.unknown') }}
        </p>
        <TrackTable v-else :kind="list === 'audio' ? 'audio' : 'subtitle'" :streams="streams" />
      </Section>
      <OutputTrackList :list="list" />
    </template>
  </section>
</template>

<style scoped>
.tracks-tab {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--rf-space-5);
  padding: var(--rf-space-4);
}

.tracks-tab__empty {
  margin: 0;
  color: var(--rf-color-text-muted);
}
</style>
