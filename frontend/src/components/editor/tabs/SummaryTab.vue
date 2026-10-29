<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import EstimateCard from '@/components/summary/EstimateCard.vue'
import IssuesCard from '@/components/summary/IssuesCard.vue'
import OutputCard from '@/components/summary/OutputCard.vue'
import PictureCard from '@/components/summary/PictureCard.vue'
import SourceCard from '@/components/summary/SourceCard.vue'
import TracksCard from '@/components/summary/TracksCard.vue'
import VideoCard from '@/components/summary/VideoCard.vue'
import { useEditorStore } from '@/stores/editor'

const { t } = useI18n()
const editor = useEditorStore()
</script>

<template>
  <section class="editor-tab summary-tab" data-tab="summary">
    <p v-if="editor.job === null" class="summary-tab__empty" data-state="empty">
      {{ editor.loading ? t('summary.loading') : t('summary.noJob') }}
    </p>
    <div v-else class="summary-tab__grid">
      <SourceCard />
      <OutputCard />
      <PictureCard />
      <VideoCard />
      <TracksCard />
      <IssuesCard />
      <EstimateCard />
    </div>
  </section>
</template>

<style scoped>
.summary-tab {
  padding: var(--rf-space-4);
}

.summary-tab__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 20rem), 1fr));
  grid-auto-flow: row dense;
  gap: var(--rf-space-4);
  align-items: start;
}

.summary-tab__empty {
  margin: 0;
  color: var(--rf-color-text-muted);
}
</style>

<style>
/* Shared by the Summary's cards. */
.summary-tab .summary-card--wide {
  grid-column: 1 / -1;
}

.summary-tab .summary-card__note {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.summary-tab .summary-card__notes {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
  padding-inline-start: var(--rf-space-4);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.summary-tab .summary-card__subtitle {
  margin: 0;
  font-size: var(--rf-font-size-sm);
  font-weight: var(--rf-font-weight-bold);
}

.summary-tab .summary-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.summary-tab .summary-chip {
  display: inline-block;
  padding: 0 var(--rf-space-2);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-pill);
  font-size: var(--rf-font-size-sm);
  line-height: 1.75rem;
  white-space: nowrap;
}

.summary-tab .summary-chip--off {
  color: var(--rf-color-text-muted);
}
</style>
