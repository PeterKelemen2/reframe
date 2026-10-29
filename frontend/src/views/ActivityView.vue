<script setup lang="ts">
import { Eraser } from '@lucide/vue'
import Button from 'primevue/button'
import SelectButton from 'primevue/selectbutton'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import StatusDot from '@/components/base/StatusDot.vue'
import { ACTIVITY_KINDS, type ActivityKind, describeEntry } from '@/components/queue/activityLines'
import { useActivityStore } from '@/stores/activity'

const { t, locale } = useI18n()
const activity = useActivityStore()

type Filter = ActivityKind | 'all'
const filter = ref<Filter>('all')

function kindLabel(kind: Filter): string {
  switch (kind) {
    case 'all':
      return t('queue.activity.kinds.all')
    case 'jobs':
      return t('queue.activity.kinds.jobs')
    case 'queue':
      return t('queue.activity.kinds.queue')
    case 'system':
      return t('queue.activity.kinds.system')
    case 'warnings':
      return t('queue.activity.kinds.warnings')
    case 'notifications':
      return t('queue.activity.kinds.notifications')
    case 'tasks':
      return t('queue.activity.kinds.tasks')
  }
}

const filters = computed(() =>
  (['all', ...ACTIVITY_KINDS] as Filter[]).map((value) => ({ value, label: kindLabel(value) })),
)

const time = computed(() => new Intl.DateTimeFormat(locale.value, { timeStyle: 'medium' }))

function jobName(jobId: string): string {
  return activity.jobName(jobId) ?? t('queue.activity.unknownJob', { id: jobId.slice(0, 8) })
}

/** Newest first. */
const lines = computed(() =>
  activity.entries
    .flatMap((entry) => {
      const line = describeEntry(entry, t, jobName)
      return line === null ? [] : [{ entry, line }]
    })
    .filter(({ line }) => filter.value === 'all' || line.kind === filter.value)
    .toReversed(),
)
</script>

<template>
  <main class="activity-view" data-view="activity">
    <header class="activity-view__header">
      <h1 class="activity-view__title">{{ t('app.views.activity') }}</h1>
      <SelectButton
        v-model="filter"
        :options="filters"
        option-label="label"
        option-value="value"
        :allow-empty="false"
        :pt="{ root: { 'aria-label': t('queue.activity.filter') } }"
        data-field="filter"
      />
      <Button
        class="activity-view__clear"
        size="small"
        severity="secondary"
        outlined
        data-action="clear"
        :label="t('queue.activity.clear')"
        :disabled="activity.entries.length === 0"
        @click="activity.clear()"
      >
        <template #icon><Eraser :size="16" aria-hidden="true" /></template>
      </Button>
    </header>
    <div class="activity-view__body">
      <p v-if="lines.length === 0" class="activity-view__empty" data-state="empty">
        {{ filter === 'all' ? t('queue.activity.empty') : t('queue.activity.noneOfKind') }}
      </p>
      <ol v-else class="activity-view__list" :aria-label="t('queue.activity.label')">
        <li
          v-for="{ entry, line } in lines"
          :key="entry.id"
          class="activity-view__entry"
          :data-kind="line.kind"
          :data-type="entry.event.type"
        >
          <time class="activity-view__time" :datetime="entry.at.toISOString()">
            {{ time.format(entry.at) }}
          </time>
          <StatusDot :tone="line.tone" :label="kindLabel(line.kind)" />
          <div class="activity-view__text">
            <span data-field="text">{{ line.text }}</span>
            <span v-if="line.detail" class="activity-view__detail" data-field="detail">
              {{ line.detail }}
            </span>
          </div>
        </li>
      </ol>
    </div>
  </main>
</template>

<style scoped>
.activity-view {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.activity-view__header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-3) var(--rf-space-5);
  padding: var(--rf-space-4);
}

.activity-view__title {
  margin: 0;
  font-size: var(--rf-font-size-2xl);
}

.activity-view__clear {
  margin-inline-start: auto;
}

.activity-view__body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0 var(--rf-space-4) var(--rf-space-4);
}

.activity-view__empty {
  color: var(--rf-color-text-muted);
}

.activity-view__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.activity-view__entry {
  display: grid;
  grid-template-columns: auto auto 1fr;
  align-items: baseline;
  gap: var(--rf-space-3);
  padding: var(--rf-space-2) 0;
  border-bottom: 1px solid var(--rf-color-border);
}

.activity-view__time {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  font-variant-numeric: tabular-nums;
}

.activity-view__text {
  display: grid;
  min-width: 0;
}

.activity-view__detail {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  overflow-wrap: anywhere;
}
</style>
