<script setup lang="ts">
import { TriangleAlert, X } from '@lucide/vue'
import Button from 'primevue/button'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Schemas, SourceEntry } from '@/api/types'
import StatusDot from '@/components/base/StatusDot.vue'
import { fileName } from '@/components/shell/format'

import { sourceSummary } from './panel'

/** One source in the panel: alone, or as a member of a batch group (`member`, `label`). */
const props = defineProps<{
  entry: SourceEntry
  member?: Schemas['GroupMember']
  /** The member's episode label (`E05`). */
  label?: string
}>()

const emit = defineEmits<{ remove: []; reprobe: [] }>()

const { t } = useI18n()

const name = computed(() => fileName(props.entry.path))
const summary = computed(() => sourceSummary(props.entry).join(' · '))
const warnings = computed(() => props.entry.source?.warnings ?? [])
const near = computed(() => props.member?.match === 'near')
</script>

<template>
  <div class="source-item" :data-path="entry.path">
    <div class="source-item__head">
      <template v-if="member">
        <StatusDot
          :tone="near ? 'warn' : 'ok'"
          :label="near ? t('sources.group.near') : t('sources.group.exact')"
          :data-match="member.match"
        />
        <span class="source-item__label">{{ label }}</span>
        <span v-if="label !== name" class="source-item__file" :title="entry.path">{{ name }}</span>
      </template>
      <span v-else class="source-item__name" :title="entry.path">{{ name }}</span>
      <Button
        class="source-item__remove"
        severity="secondary"
        text
        rounded
        size="small"
        tabindex="-1"
        :aria-label="t('sources.panel.remove', { name })"
        v-tooltip.left="t('sources.panel.remove', { name })"
        data-action="remove"
        @click.stop="emit('remove')"
      >
        <template #icon><X :size="14" aria-hidden="true" /></template>
      </Button>
    </div>
    <p v-if="!member && summary" class="source-item__summary" data-field="summary">
      {{ summary }}
    </p>
    <ul v-if="near && member?.differences?.length" class="source-item__differences">
      <li v-for="line in member.differences" :key="line" data-field="difference">{{ line }}</li>
    </ul>
    <div v-if="entry.source === null" class="source-item__stale" data-state="stale">
      <span>{{ t('sources.panel.stale') }}</span>
      <Button
        :label="t('sources.panel.reprobe')"
        link
        size="small"
        tabindex="-1"
        data-action="reprobe"
        @click.stop="emit('reprobe')"
      />
    </div>
    <ul
      v-if="warnings.length"
      class="source-item__warnings"
      :aria-label="t('sources.panel.warnings')"
    >
      <li v-for="(warning, index) in warnings" :key="index" data-field="warning">
        <TriangleAlert :size="14" aria-hidden="true" />
        <span>{{ warning }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.source-item {
  display: grid;
  gap: 0.125rem;
  min-width: 0;
}

.source-item__head {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
  min-width: 0;
}

.source-item__name,
.source-item__file {
  overflow: hidden;
  flex: 1;
  min-width: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-item__name {
  font-weight: var(--rf-font-weight-medium);
}

.source-item__label {
  font-variant-numeric: tabular-nums;
  font-weight: var(--rf-font-weight-medium);
}

.source-item__file {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.source-item__remove {
  flex: none;
  width: 1.75rem;
  height: 1.75rem;
  margin-inline-start: auto;
  opacity: 0;
}

.source-item:hover .source-item__remove,
:focus-within > .source-item .source-item__remove,
:focus > .source-item .source-item__remove {
  opacity: 1;
}

.source-item__summary {
  overflow: hidden;
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-item__differences,
.source-item__warnings {
  display: grid;
  gap: 0.125rem;
  margin: 0;
  padding: 0;
  font-size: var(--rf-font-size-sm);
  list-style: none;
}

.source-item__differences {
  padding-inline-start: calc(0.625rem + var(--rf-space-2));
  color: var(--rf-color-text-muted);
}

.source-item__warnings li {
  display: flex;
  align-items: flex-start;
  gap: var(--rf-space-1);
  color: var(--p-status-warn-color);
}

.source-item__warnings li > svg {
  flex: none;
  margin-top: 0.2em;
}

.source-item__stale {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0 var(--rf-space-2);
  color: var(--p-status-error-color);
  font-size: var(--rf-font-size-sm);
}
</style>
