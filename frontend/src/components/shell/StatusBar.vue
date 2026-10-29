<script lang="ts">
/** The CSS variable with the status bar's height while it is shown (toasts keep clear of it). */
export const STATUS_BAR_HEIGHT = '--shell-status-bar-height'
</script>

<script setup lang="ts">
import { ListPlus, ListVideo, Play, Plus } from '@lucide/vue'
import { useResizeObserver } from '@vueuse/core'
import vTooltip from 'primevue/tooltip'
import { computed, onBeforeUnmount, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'

import { useQueueActions } from '@/composables/useQueueActions'
import { useEditorStore } from '@/stores/editor'
import { useQueueStore } from '@/stores/queue'

import ConnectionStatus from './ConnectionStatus.vue'
import FocusSafeButton from './FocusSafeButton'
import ValidationSummary from './ValidationSummary.vue'

const { t } = useI18n()
const editor = useEditorStore()
const queue = useQueueStore()
const actions = useQueueActions()
const { canAdd, canAddAll, canStart } = actions

const outputPath = computed(() => editor.job?.output?.path || null)

const root = useTemplateRef<HTMLElement>('root')
useResizeObserver(root, ([entry]) => {
  const height = entry?.borderBoxSize?.[0]?.blockSize ?? entry?.contentRect.height ?? 0
  document.documentElement.style.setProperty(STATUS_BAR_HEIGHT, `${Math.ceil(height)}px`)
})
onBeforeUnmount(() => document.documentElement.style.removeProperty(STATUS_BAR_HEIGHT))

const queueSummary = computed(() => {
  const { running, paused, waiting } = queue.counts
  const parts: string[] = []
  if (running > 0) parts.push(t('shell.queue.running', { n: running }))
  if (paused > 0) parts.push(t('shell.queue.paused', { n: paused }))
  if (waiting > 0) parts.push(t('shell.queue.waiting', { n: waiting }))
  return parts.length === 0
    ? t('shell.queue.idle')
    : t('shell.queue.summary', { parts: parts.join(' · ') })
})
</script>

<template>
  <section ref="root" class="status-bar" :aria-label="t('shell.status.label')">
    <div class="status-bar__output" data-field="output">
      <span class="status-bar__caption">{{ t('shell.status.output') }}</span>
      <span
        v-if="outputPath"
        v-tooltip.top="outputPath"
        class="status-bar__path"
        data-field="output-path"
      >
        <span dir="ltr">{{ outputPath }}</span>
      </span>
      <span v-else class="status-bar__path status-bar__path--none">
        {{ t('shell.status.noOutput') }}
      </span>
    </div>
    <ValidationSummary v-if="editor.job !== null" />
    <ConnectionStatus />
    <RouterLink to="/queue" class="status-bar__queue" data-field="queue">
      <ListVideo :size="16" aria-hidden="true" />
      {{ queueSummary }}
    </RouterLink>
    <div class="status-bar__actions">
      <FocusSafeButton
        class="status-bar__add"
        size="small"
        :label="t('shell.queue.add')"
        :disabled="!canAdd"
        aria-keyshortcuts="Control+Enter"
        @click="actions.addCurrent()"
      >
        <template #icon>
          <Plus :size="16" aria-hidden="true" />
        </template>
      </FocusSafeButton>
      <FocusSafeButton
        class="status-bar__add-all"
        size="small"
        severity="secondary"
        outlined
        :label="t('shell.queue.addAll')"
        :disabled="!canAddAll"
        @click="actions.addAll()"
      >
        <template #icon>
          <ListPlus :size="16" aria-hidden="true" />
        </template>
      </FocusSafeButton>
      <FocusSafeButton
        class="status-bar__start"
        size="small"
        severity="secondary"
        outlined
        :label="t('shell.queue.start')"
        :disabled="!canStart"
        @click="actions.start()"
      >
        <template #icon>
          <Play :size="16" aria-hidden="true" />
        </template>
      </FocusSafeButton>
    </div>
  </section>
</template>

<style scoped>
.status-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-4);
  padding: var(--rf-space-2) var(--rf-space-3);
  border-top: 1px solid var(--rf-color-border);
  background: var(--rf-color-surface);
  font-size: var(--rf-font-size-sm);
}

.status-bar__output {
  display: flex;
  flex: 1 1 16rem;
  align-items: baseline;
  gap: var(--rf-space-2);
  min-width: 0;
}

.status-bar__caption {
  color: var(--rf-color-text-muted);
}

.status-bar__path {
  overflow: hidden;
  font-family: var(--rf-font-mono);
  text-overflow: ellipsis;
  white-space: nowrap;
  /* The file name at the end matters most: the ellipsis cuts the start of the path. */
  direction: rtl;
  text-align: left;
}

.status-bar__path--none {
  font-family: inherit;
  color: var(--rf-color-text-muted);
  direction: ltr;
}

.status-bar__queue {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
  color: var(--rf-color-text-muted);
}

.status-bar__queue:hover {
  color: var(--rf-color-text);
}

.status-bar__actions {
  display: flex;
  gap: var(--rf-space-2);
  margin-left: auto;
}
</style>
