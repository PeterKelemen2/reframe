<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import EstimateCard from '@/components/summary/EstimateCard.vue'
import IssuesCard from '@/components/summary/IssuesCard.vue'
import JobTypeCard from '@/components/summary/JobTypeCard.vue'
import OutputCard from '@/components/summary/OutputCard.vue'
import PictureCard from '@/components/summary/PictureCard.vue'
import SourceCard from '@/components/summary/SourceCard.vue'
import TracksCard from '@/components/summary/TracksCard.vue'
import VideoCard from '@/components/summary/VideoCard.vue'
import { useEditorStore } from '@/stores/editor'
import { useValidationStore } from '@/stores/validation'

const { t } = useI18n()
const editor = useEditorStore()
const validation = useValidationStore()

const hasIssues = computed(() => validation.issues.length > 0)
</script>

<template>
  <section class="editor-tab summary-tab" data-tab="summary">
    <!-- The cards' titles are h3: without this level the outline skips from h1 to h3. -->
    <h2 class="rf-sr-only">{{ t('summary.heading') }}</h2>
    <p v-if="editor.job === null" class="summary-tab__empty" data-state="empty">
      {{ editor.loading ? t('summary.loading') : t('summary.noJob') }}
    </p>
    <!-- What the job writes, in the order of the output file; the source's own facts come last. -->
    <div v-else class="summary-tab__grid">
      <IssuesCard v-if="hasIssues" />
      <TracksCard />
      <PictureCard />
      <VideoCard />
      <JobTypeCard />
      <OutputCard />
      <EstimateCard />
      <SourceCard />
      <IssuesCard v-if="!hasIssues" />
    </div>
  </section>
</template>

<style scoped>
.summary-tab {
  container-type: inline-size;
  padding: var(--rf-space-4);
}

.summary-tab__grid {
  display: grid;
  /* Wide enough for the Video card's values on one line, such as "Constant quality RF 22". */
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 22rem), 1fr));
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
